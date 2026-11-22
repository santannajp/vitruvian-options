"""Quote and paper manage multi-leg BTC option strategies."""
import json
import sqlite3
import uuid
from contextlib import closing
from decimal import Decimal,InvalidOperation
import time
from decimal import ROUND_DOWN

import spreads
import derive
import math

DAY_MS=86400000


def d(value):
    x=Decimal(str(value))
    if not x.is_finite():raise ValueError('Valor numérico inválido.')
    return x


def validate(family,legs):
    if not isinstance(legs,list) or not legs:raise ValueError('Informe as pernas da estrutura.')
    if family in ('long_call','long_put'):
        expected='call' if family=='long_call' else 'put'
        if len(legs)!=1 or legs[0]['side']!='buy' or legs[0]['type']!=expected:raise ValueError('Opção simples exige uma perna comprada do tipo selecionado.')
    elif family in ('straddle','strangle'):
        if len(legs)!=2 or {x['type'] for x in legs}!={'call','put'} or any(x['side']!='buy' for x in legs):
            raise ValueError('Straddle/strangle exige call e put compradas.')
        if legs[0]['expiry']!=legs[1]['expiry']:raise ValueError('Call e put devem ter o mesmo vencimento.')
        same=d(legs[0]['strike'])==d(legs[1]['strike'])
        if (family=='straddle')!=same:raise ValueError('Straddle usa strikes iguais; strangle usa strikes diferentes.')
    elif family=='iron_condor':
        if len(legs)!=4 or {x['type'] for x in legs}!={'call','put'}:raise ValueError('Iron Condor exige duas puts e duas calls.')
        if len({x['expiry'] for x in legs})!=1:raise ValueError('Iron Condor exige o mesmo vencimento.')
        puts=sorted((x for x in legs if x['type']=='put'),key=lambda x:d(x['strike']))
        calls=sorted((x for x in legs if x['type']=='call'),key=lambda x:d(x['strike']))
        if [x['side'] for x in puts]!=['buy','sell'] or [x['side'] for x in calls]!=['sell','buy']:
            raise ValueError('Iron Condor exige put externa comprada, put interna vendida, call interna vendida e call externa comprada.')
        if not d(puts[0]['strike'])<d(puts[1]['strike'])<d(calls[0]['strike'])<d(calls[1]['strike']):
            raise ValueError('Strikes do Iron Condor devem ordenar asas externas e strikes internos.')
    elif family in ('calendar','diagonal'):
        if len(legs)!=2 or legs[0]['type']!=legs[1]['type'] or legs[0]['side']==legs[1]['side']:
            raise ValueError('Calendário/diagonal exige duas pernas do mesmo tipo e lados opostos.')
        long=next(x for x in legs if x['side']=='buy');short=next(x for x in legs if x['side']=='sell')
        if d(long['expiry'])<=d(short['expiry']):raise ValueError('A opção comprada deve vencer depois da opção vendida.')
        same=d(long['strike'])==d(short['strike'])
        if (family=='calendar')!=same:raise ValueError('Calendário usa strikes iguais; diagonal usa strikes diferentes.')
    else:raise ValueError('Estrutura não suportada.')


def _fee(venue,item,amount,price,index):
    if venue=='deribit':return amount*min(d(item['rate']),price*d(item['fee_cap']))
    return d(item['base_fee'])+min(d(item['rate'])*amount*index,price*amount*d(item['fee_cap']))


def _normal_cdf(x):
    return (1+math.erf(x/math.sqrt(2)))/2


def _bs_price(kind,spot,strike,days,volatility_percent):
    spot,strike,days,vol=map(float,(spot,strike,days,volatility_percent))
    if spot<0 or strike<=0 or vol<=0:raise ValueError('Spot não negativo, strike e volatilidade positivos são necessários.')
    if spot==0:return 0.0 if kind=='call' else strike
    t=max(0,days)/365
    if t==0:return max(0,spot-strike) if kind=='call' else max(0,strike-spot)
    sigma=vol/100;sigma_t=sigma*math.sqrt(t)
    d1=(math.log(spot/strike)+.5*sigma*sigma*t)/sigma_t;d2=d1-sigma_t
    if kind=='call':return spot*_normal_cdf(d1)-strike*_normal_cdf(d2)
    return strike*_normal_cdf(-d2)-spot*_normal_cdf(-d1)


def preview(data,fetch_snapshot=spreads.snapshot,now_ms=None):
    try:
        venue=str(data['venue']).lower();family=str(data['family']);size=d(data['size'])
        if venue not in ('derive','deribit') or size<=0:raise ValueError('Exchange e tamanho válidos são necessários.')
        now=d(now_ms if now_ms is not None else time.time()*1000)
        raw=data['legs'];items=[fetch_snapshot(venue,item['instrument']) for item in raw]
        legs=[]
        for requested,item in zip(raw,items):
            side=str(requested['side'])
            if side not in ('buy','sell'):raise ValueError('Lado de opção inválido.')
            if size<d(item['minimum']) or size%d(item['step']) or (item['maximum'] and size>d(item['maximum'])):
                raise ValueError(f'{item["name"]}: quantidade fora do lote.')
            if now-d(item['timestamp'])>30000:raise ValueError(f'{item["name"]}: livro desatualizado.')
            entry_book=item['asks'] if side=='buy' else item['bids']
            close_book=item['bids'] if side=='buy' else item['asks']
            if not entry_book:raise ValueError(f'{item["name"]}: sem oferta para entrar.')
            entry_price,entry_depth=map(d,entry_book[0])
            if entry_depth<size:raise ValueError(f'{item["name"]}: profundidade insuficiente para entrar.')
            exit_price=close_depth=None
            if close_book:
                exit_price,close_depth=map(d,close_book[0])
            index=d(item['index']);fee=_fee(venue,item,size,entry_price,index)
            legs.append({'instrument':item['name'],'side':side,'type':item['type'],'strike':str(item['strike']),
                         'expiry':item['expiry'],'size':str(size),'entry_price':str(entry_price),'entry_depth':str(entry_depth),
                         'exit_price':str(exit_price) if exit_price is not None else None,
                         'exit_depth':str(close_depth) if close_depth is not None else '0',
                         'fee':str(fee),'timestamp':item['timestamp'],'index':str(index),
                         'minimum':str(item['minimum']),'step':str(item['step'])})
        validate(family,legs)
        if len({item['expiry'] for item in legs})>1 and family not in ('calendar','diagonal'):
            raise ValueError('Pernas devem ter vencimento igual para esta estrutura.')
        index=d(legs[0]['index']);currency='BTC' if venue=='deribit' else 'USDC'
        entry_debit=sum((d(x['entry_price'])*size*(1 if x['side']=='buy' else -1)+d(x['fee']) for x in legs),Decimal(0))
        entry_usd=entry_debit*index if currency=='BTC' else entry_debit
        close_debit=sum(((-d(x['exit_price']) if x['side']=='buy' else d(x['exit_price']))*size+
                         _fee(venue,items[i],size,d(x['exit_price']),index) if x['exit_price'] is not None and d(x['exit_depth'])>=size else Decimal(0)
                         for i,x in enumerate(legs)),Decimal(0))
        exit_available=all(x['exit_price'] is not None and d(x['exit_depth'])>=size for x in legs)
        mark_pnl=-entry_debit-close_debit if exit_available else None
        mark_usd=mark_pnl*index if currency=='BTC' and mark_pnl is not None else mark_pnl
        strikes=sorted({d(x['strike']) for x in legs});prices=sorted({Decimal(0),max(Decimal(1),strikes[0]*Decimal('.8')),index,*strikes,(strikes[0]+strikes[-1])/2,strikes[-1]*Decimal('1.2'),strikes[-1]+(strikes[-1]-strikes[0])})
        scenarios=[]
        if family in ('calendar','diagonal'):
            volatility=d(data.get('volatility_percent','60'))
            vols=[d(x) for x in data.get('volatility_scenarios',[volatility*Decimal('.75'),volatility,volatility*Decimal('1.25')])]
            if volatility<=0 or any(v<=0 or v>500 for v in vols):raise ValueError('IV e cenários de volatilidade devem estar entre 0 e 500%.')
            near=next(x for x in legs if x['side']=='sell');far=next(x for x in legs if x['side']=='buy')
            executable_exit=(d(far['exit_price'])*size*(index if currency=='BTC' else Decimal(1))
                             if far['exit_price'] is not None and d(far['exit_depth'])>=size else None)
            days_remaining=(d(far['expiry'])-d(near['expiry']))/DAY_MS
            for price in prices:
                near_intrinsic=max(Decimal(0),price-d(near['strike'])) if near['type']=='call' else max(Decimal(0),d(near['strike'])-price)
                for vol in vols:
                    long_value=d(str(_bs_price(far['type'],price,d(far['strike']),days_remaining,vol)))*size
                    payout=long_value-near_intrinsic*size
                    scenarios.append({'btc_price_usd':str(price),'volatility_percent':str(vol),
                                      'remaining_leg_value_usd':str(long_value),
                                      'remaining_leg_exit_available':executable_exit is not None,
                                      'remaining_leg_executable_exit_usd':str(executable_exit) if executable_exit is not None else None,
                                      'remaining_leg_exit_depth':far['exit_depth'],
                                      'remaining_instrument':far['instrument'],'remaining_expiry':far['expiry'],
                                      'expired_short_intrinsic_usd':str(near_intrinsic*size),
                                      'pnl_at_expiry_usd':str(payout-entry_usd),
                                      'market_state':'baixa' if price<index else 'estabilidade' if price==index else 'alta'})
        else:
            for price in prices:
                payout=Decimal(0)
                for leg in legs:
                    intrinsic=max(Decimal(0),price-d(leg['strike'])) if leg['type']=='call' else max(Decimal(0),d(leg['strike'])-price)
                    payout+=(intrinsic*size)*(1 if leg['side']=='buy' else -1)
                scenarios.append({'btc_price_usd':str(price),'option_intrinsic_net_usd':str(payout),
                                  'pnl_at_expiry_usd':str(payout-entry_usd),
                                  'market_state':'baixa' if price<index else 'estabilidade' if price==index else 'alta'})
        values=[d(x['pnl_at_expiry_usd']) for x in scenarios]
        timestamps=[d(x['timestamp']) for x in legs]
        return {'venue':venue,'family':family,'size':str(size),'entry_currency':currency,'debit':str(entry_debit),
                'fees':str(sum((d(x['fee']) for x in legs),Decimal(0))),'reference_btc_usd':str(index),
                'expiry':min(x['expiry'] for x in legs),'remaining_expiry':max(x['expiry'] for x in legs),'legs':legs,'exit_available':exit_available,
                'close_debit':str(close_debit) if exit_available else None,'unrealized_pnl':str(mark_pnl) if mark_pnl is not None else None,'unrealized_currency':currency,
                'unrealized_pnl_usd':str(mark_usd) if mark_usd is not None else None,
                'maximum_loss_usd':None if family in ('calendar','diagonal') else str(min(Decimal(0),*values)),
                'maximum_loss_note':'Cenários amostrados não estabelecem perda máxima global da exposição entre vencimentos.' if family in ('calendar','diagonal') else 'Perda máxima estimada nos pontos de quebra do payoff.',
                'risk_estimate_usd':str(max(d(quote) for quote in [Decimal(0),-min(Decimal(0),*values),max(Decimal(0),entry_usd)])),
                'maximum_gain_usd':None if family in ('long_call','straddle','strangle','calendar','diagonal') else str(max(Decimal(0),*values)),
                'maximum_gain_note':'Ilimitado/modelo-dependente; veja cenários.' if family in ('long_call','straddle','strangle','calendar','diagonal') else 'Limitado pela estrutura.',
                'remaining_days_after_first_expiry':str(days_remaining) if family in ('calendar','diagonal') else None,
                'volatility_percent':str(volatility) if family in ('calendar','diagonal') else None,
                'scenarios':scenarios,'timestamp':str(min(timestamps)),
                'assumptions':'Calendário/diagonal: payoff intrínseco da perna curta no primeiro vencimento e Black-Scholes de taxa zero para a perna longa, com IV plana informada; demais famílias usam payoff no vencimento. Prêmio BTC convertido pelo índice de entrada; não replica margem ou settlement oficial.'}
    except (KeyError,TypeError,InvalidOperation) as exc:
        raise ValueError('Dados de estrutura de opções inválidos.') from exc


def open_paper(db_path,data,fetch_snapshot=spreads.snapshot):
    try:
        request_id=str(data.get('request_id') or uuid.uuid4()).strip()
        proposed=d(data['proposed_debit']);tolerance=d(data.get('tolerance_percent','2'))
        signature=json.dumps({k:v for k,v in data.items() if k!='request_id'},sort_keys=True)
        with closing(sqlite3.connect(db_path)) as con:
            try:old=con.execute('SELECT signature,payload FROM option_structures WHERE request_id=?',(request_id,)).fetchone()
            except sqlite3.OperationalError:old=None
            if old:
                if old[0]!=signature:raise ValueError('ID da estrutura reutilizado com outros dados.')
                return json.loads(old[1])
        quote=preview(data,fetch_snapshot)
        adverse=max(Decimal(0),d(quote['debit'])-proposed)
        slip=adverse/abs(proposed)*100 if proposed else (Decimal(0) if adverse==0 else Decimal('Infinity'))
        if tolerance<0 or slip>tolerance:raise ValueError(f'Recotação excede tolerância: {slip}% > {tolerance}%.')
        currency=quote['entry_currency'];risk=d(quote['risk_estimate_usd'])
        reserve=max(Decimal(0),d(quote['debit'])) if d(quote['debit'])>0 else (risk/d(quote['reference_btc_usd']) if currency=='BTC' else risk)
        token=currency;venue=quote['venue']
        with closing(sqlite3.connect(db_path,timeout=10)) as con,con:
            con.execute('BEGIN IMMEDIATE')
            con.execute('CREATE TABLE IF NOT EXISTS option_structures (request_id TEXT PRIMARY KEY,signature TEXT NOT NULL,status TEXT NOT NULL,payload TEXT NOT NULL)')
            old=con.execute('SELECT signature,payload FROM option_structures WHERE request_id=?',(request_id,)).fetchone()
            if old:
                if old[0]!=signature:raise ValueError('ID da estrutura reutilizado com outros dados.')
                return json.loads(old[1])
            wallet_row=con.execute('SELECT payload FROM funds WHERE id=1').fetchone()
            if not wallet_row:raise ValueError('Cadastre o caixa simulado primeiro.')
            wallet=json.loads(wallet_row[0]);balance=next((x for x in wallet['balances'] if x['token'].upper()==token and x['location'].lower()==venue),None)
            if not balance:raise ValueError(f'Cadastre saldo {token} em {venue}.')
            available=d(balance['available'])
            if reserve>available:raise ValueError(f'Orçamento insuficiente: disponível {available}; necessário {reserve} {token}.')
            balance['available']=str(available-reserve);balance['margem']=str(d(balance.get('margem','0'))+reserve)
            payload={'request_id':request_id,'status':'aberta','quote':quote,'reserved':str(reserve),'reserved_token':token,
                     'proposed_debit':str(proposed),'recotado':quote['debit'],'slippage_percent':str(slip),
                     'opened_legs':[{'instrument':x['instrument'],'side':x['side'],'quantity':quote['size'],
                                     'average_price':x['entry_price'],'fee':x['fee']} for x in quote['legs']],
                     'effective_fees':quote['fees'],'wallet':wallet}
            con.execute('UPDATE funds SET payload=? WHERE id=1',(json.dumps(wallet),))
            con.execute('INSERT INTO option_structures VALUES(?,?,?,?)',(request_id,signature,'aberta',json.dumps(payload)))
        return payload
    except (KeyError,TypeError,InvalidOperation,sqlite3.OperationalError) as exc:
        raise ValueError('Dados da estrutura simulada inválidos.') from exc


def list_paper(db_path):
    with closing(sqlite3.connect(db_path)) as con:
        try:rows=con.execute('SELECT payload FROM option_structures ORDER BY rowid DESC').fetchall()
        except sqlite3.OperationalError:return []
        result=[json.loads(row[0]) for row in rows]
        for item in result:
            try:events=con.execute('SELECT payload FROM structure_fill_events WHERE request_id=? ORDER BY observed_at DESC,event_id DESC',(item['request_id'],)).fetchall()
            except sqlite3.OperationalError:events=[]
            latest={}
            for event in events:
                data=json.loads(event[0]);latest.setdefault(data['instrument'],data)
            req=d(item['quote']['size']);legs=[]
            for leg in item['quote']['legs']:
                fill=latest.get(leg['instrument'],{'quantity':str(req),'average_price':leg['entry_price'],'fee':leg['fee'],'observed_at':None})
                legs.append({**fill,'instrument':leg['instrument'],'side':leg['side'],'residual_quantity':str(req-d(fill['quantity']))})
            item['opened_legs']=legs;item['reconciled']=all(d(x['quantity'])==d(legs[0]['quantity']) for x in legs)
            item['unhedged_quantity']=str(max((d(x['quantity']) for x in legs),default=Decimal(0))-min((d(x['quantity']) for x in legs),default=Decimal(0)))
            item['roll_blocked']=not item['reconciled']
    return result


def record_fill(db_path,data):
    try:
        event_id=str(data['event_id']).strip();request_id=str(data['request_id']).strip();instrument=str(data['instrument']).strip()
        observed_at=str(data['observed_at']).strip();quantity,price,fee=map(d,(data['quantity'],data['average_price'],data['fee']))
        if not event_id or not observed_at or min(quantity,price,fee)<0:raise ValueError('Preenchimento acumulado inválido.')
        payload={'event_id':event_id,'request_id':request_id,'instrument':instrument,'observed_at':observed_at,
                 'quantity':str(quantity),'average_price':str(price),'fee':str(fee)}
        encoded=json.dumps(payload,sort_keys=True)
        with closing(sqlite3.connect(db_path,timeout=10)) as con,con:
            con.execute('BEGIN IMMEDIATE')
            con.execute('CREATE TABLE IF NOT EXISTS structure_fill_events (event_id TEXT PRIMARY KEY,request_id TEXT NOT NULL,instrument TEXT NOT NULL,observed_at TEXT NOT NULL,payload TEXT NOT NULL)')
            row=con.execute('SELECT payload FROM option_structures WHERE request_id=?',(request_id,)).fetchone()
            if not row:raise ValueError('Estrutura não encontrada.')
            strategy=json.loads(row[0])
            if instrument not in [x['instrument'] for x in strategy['quote']['legs']] or quantity>d(strategy['quote']['size']):raise ValueError('Perna inexistente ou quantidade excedida.')
            old=con.execute('SELECT payload FROM structure_fill_events WHERE event_id=?',(event_id,)).fetchone()
            if old:
                if old[0]!=encoded:raise ValueError('ID de preenchimento reutilizado com outros dados.')
            else:con.execute('INSERT INTO structure_fill_events VALUES(?,?,?,?,?)',(event_id,request_id,instrument,observed_at,encoded))
        return next(x for x in list_paper(db_path) if x['request_id']==request_id)
    except (KeyError,TypeError,InvalidOperation,sqlite3.OperationalError) as exc:
        raise ValueError('Dados de reconciliação inválidos.') from exc


def _finalize(db_path,request_id,event_id,exit_debit,exit_fee,index,mode,settlement=None,now_ms=None,entry_debit_actual=None):
    with closing(sqlite3.connect(db_path,timeout=10)) as con,con:
        con.execute('BEGIN IMMEDIATE')
        con.execute('CREATE TABLE IF NOT EXISTS option_structure_closures (event_id TEXT PRIMARY KEY,request_id TEXT UNIQUE NOT NULL,payload TEXT NOT NULL)')
        old=con.execute('SELECT payload FROM option_structure_closures WHERE request_id=?',(request_id,)).fetchone()
        if old:return json.loads(old[0])
        row=con.execute('SELECT payload FROM option_structures WHERE request_id=?',(request_id,)).fetchone()
        wallet_row=con.execute('SELECT payload FROM funds WHERE id=1').fetchone()
        if not row or not wallet_row:raise ValueError('Estrutura ou caixa simulado não encontrada.')
        position=json.loads(row[0]);wallet=json.loads(wallet_row[0]);quote=position['quote']
        if entry_debit_actual is not None:position['entry_debit_actual']=str(entry_debit_actual)
        if position['status']!='aberta':raise ValueError('Estrutura já encerrada.')
        current_pnl=-d(position.get('entry_debit_actual',quote['debit']))-d(exit_debit)
        currency=quote['entry_currency'];pnl=current_pnl+d(position.get('settled_pnl_native','0'))
        pnl_usd=(current_pnl*d(index) if currency=='BTC' else current_pnl)+d(position.get('settled_pnl_usd','0'))
        balance=next((x for x in wallet['balances'] if x['token'].upper()==position['reserved_token'].upper() and x['location'].lower()==quote['venue']),None)
        if not balance:raise ValueError('Saldo reservado não encontrado.')
        reserve=d(position['reserved']);total=d(balance['total']);available=d(balance['available']);margin=d(balance.get('margem','0'))
        if reserve>margin or total+current_pnl<0:raise ValueError('Saldo ou margem insuficiente para conciliar encerramento.')
        balance['margem']=str(margin-reserve);balance['total']=str(total+current_pnl)
        balance['available']=str(total+current_pnl-sum((d(balance.get(k,'0')) for k in ('reserva','grid','premios','margem','apostas')),Decimal(0)))
        if d(balance['available'])<0:raise ValueError('Encerramento excederia o saldo livre após reservas.')
        payload={**position,'status':'encerrada','close_mode':mode,'closed_at':str(now_ms or time.time()*1000),
                 'event_id':event_id,'exit_debit':str(exit_debit),'exit_fees':str(exit_fee),'settlement':settlement,
                 'realized_pnl':str(pnl),'realized_pnl_usd':str(pnl_usd),'wallet':wallet}
        con.execute('UPDATE funds SET payload=? WHERE id=1',(json.dumps(wallet),))
        con.execute('UPDATE option_structures SET status=?,payload=? WHERE request_id=?',('encerrada',json.dumps(payload),request_id))
        con.execute('INSERT INTO option_structure_closures VALUES(?,?,?)',(event_id,request_id,json.dumps(payload)))
        return payload


def _position_flows(db_path,position,fetch_snapshot):
    detail=next(x for x in list_paper(db_path) if x['request_id']==position['request_id'])
    if not any(d(x['quantity'])>0 for x in detail['opened_legs']):raise ValueError('Nenhuma perna preenchida para encerrar.')
    quote=position['quote'];index=d(quote['reference_btc_usd']);entry=exit_debit=exit_fee=Decimal(0);fills={x['instrument']:x for x in detail['opened_legs']};closed=[]
    for original in quote['legs']:
        if any(x['instrument']==original['instrument'] for x in position.get('settled_legs',[])):
            continue
        fill=fills[original['instrument']];amount=d(fill['quantity'])
        if not amount:continue
        snap=fetch_snapshot(quote['venue'],original['instrument'])
        if d(time.time()*1000)-d(snap['timestamp'])>30000:raise ValueError(f'{original["instrument"]}: livro de saída desatualizado.')
        book=snap['bids'] if original['side']=='buy' else snap['asks']
        if not book:raise ValueError(f'{original["instrument"]}: sem oferta para encerrar.')
        price,depth=map(d,book[0])
        if depth<amount:raise ValueError(f'{original["instrument"]}: profundidade insuficiente para encerrar {amount}.')
        fee=_fee(quote['venue'],snap,amount,price,index)
        entry+=d(fill['average_price'])*amount*(1 if original['side']=='buy' else -1)+d(fill['fee'])
        exit_debit+=(-price if original['side']=='buy' else price)*amount+fee;exit_fee+=fee
        closed.append({'instrument':original['instrument'],'quantity':str(amount),'exit_price':str(price),'exit_fee':str(fee)})
    position['entry_debit_actual']=str(entry)
    return {'exit_debit':exit_debit,'exit_fee':exit_fee,'index':index,'entry_debit':entry,'closed_legs':closed}


def close_paper(db_path,request_id,event_id,fetch_snapshot=spreads.snapshot):
    try:
        request_id=str(request_id).strip();event_id=str(event_id).strip()
        with closing(sqlite3.connect(db_path)) as con:
            old=con.execute('SELECT payload FROM option_structure_closures WHERE request_id=?',(request_id,)).fetchone() if con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='option_structure_closures'").fetchone() else None
            row=con.execute('SELECT payload FROM option_structures WHERE request_id=?',(request_id,)).fetchone()
        if old:return json.loads(old[0])
        if not row:raise ValueError('Estrutura não encontrada.')
        position=json.loads(row[0]);detail=next(x for x in list_paper(db_path) if x['request_id']==request_id)
        flows=_position_flows(db_path,position,fetch_snapshot)
        return _finalize(db_path,request_id,event_id,str(flows['exit_debit']),str(flows['exit_fee']),str(flows['index']),'mercado',
                         {'closed_legs':flows['closed_legs'],'partial_exposure_closed':True},time.time()*1000,flows['entry_debit'])
    except (KeyError,TypeError,InvalidOperation,sqlite3.OperationalError) as exc:
        raise ValueError('Dados de encerramento inválidos.') from exc


def settle_paper(db_path,request_id,event_id,btc_price,fee='0',now_ms=None):
    try:
        with closing(sqlite3.connect(db_path)) as con:
            row=con.execute('SELECT payload FROM option_structures WHERE request_id=?',(str(request_id),)).fetchone()
        if not row:raise ValueError('Estrutura não encontrada.')
        position=json.loads(row[0]);quote=position['quote'];price=d(btc_price);fee=d(fee)
        if price<=0 or fee<0:raise ValueError('Preço de settlement positivo e taxa não negativa são necessários.')
        if len({int(x['expiry']) for x in quote['legs']})!=1:raise ValueError('Calendários e diagonais devem ser liquidados por perna.')
        if (time.time()*1000 if now_ms is None else now_ms)<int(quote['expiry']):raise ValueError('O vencimento ainda não ocorreu.')
        detail=next(x for x in list_paper(db_path) if x['request_id']==str(request_id))
        payout=Decimal(0);entry=Decimal(0);fills={x['instrument']:x for x in detail['opened_legs']}
        if not any(d(x['quantity'])>0 for x in detail['opened_legs']):raise ValueError('Nenhuma perna preenchida para liquidar.')
        for leg in quote['legs']:
            fill=fills[leg['instrument']];quantity=d(fill['quantity'])
            if not quantity:continue
            intrinsic=max(Decimal(0),price-d(leg['strike'])) if leg['type']=='call' else max(Decimal(0),d(leg['strike'])-price)
            payout+=intrinsic*quantity*(1 if leg['side']=='buy' else -1)
            entry+=d(fill['average_price'])*quantity*(1 if leg['side']=='buy' else -1)+d(fill['fee'])
        currency=quote['entry_currency'];exit_debit=-payout/price+fee if currency=='BTC' else -payout+fee
        position['entry_debit_actual']=str(entry)
        return _finalize(db_path,request_id,event_id,exit_debit,fee,price,'vencimento',
                         {'btc_price_usd':str(price),'intrinsic_net_usd':str(payout),'model':'intrínseco estimado por perna'},now_ms,entry)
    except (KeyError,TypeError,InvalidOperation,sqlite3.OperationalError) as exc:
        raise ValueError('Dados de settlement inválidos.') from exc


def settle_leg(db_path,request_id,event_id,instrument,btc_price,fee='0',now_ms=None):
    """Settle one expired leg of a calendar/diagonal and retain the later option."""
    try:
        request_id,event_id,instrument=map(str,(request_id,event_id,instrument));price=d(btc_price);fee=d(fee)
        if price<=0 or fee<0:raise ValueError('Preço de BTC positivo e taxa não negativa são necessários.')
        with closing(sqlite3.connect(db_path,timeout=10)) as con,con:
            con.execute('BEGIN IMMEDIATE')
            con.execute('CREATE TABLE IF NOT EXISTS option_structure_leg_settlements (event_id TEXT PRIMARY KEY,request_id TEXT NOT NULL,instrument TEXT NOT NULL,signature TEXT NOT NULL,payload TEXT NOT NULL,UNIQUE(request_id,instrument))')
            old=con.execute('SELECT signature,payload FROM option_structure_leg_settlements WHERE event_id=?',(event_id,)).fetchone()
            if old:
                signature=json.dumps({'request_id':request_id,'instrument':instrument,'btc_price':str(price),'fee':str(fee)},sort_keys=True)
                if old[0]!=signature:raise ValueError('ID de settlement reutilizado com outros dados.')
                return json.loads(old[1])
            row=con.execute('SELECT payload FROM option_structures WHERE request_id=?',(request_id,)).fetchone()
            wallet_row=con.execute('SELECT payload FROM funds WHERE id=1').fetchone()
            if not row or not wallet_row:raise ValueError('Estrutura ou carteira simulada não encontrada.')
            position=json.loads(row[0]);quote=position['quote']
            if quote['family'] not in ('calendar','diagonal'):raise ValueError('Settlement individual é reservado para calendários e diagonais.')
            if position['status']!='aberta':raise ValueError('Estrutura já encerrada.')
            leg=next((x for x in quote['legs'] if x['instrument']==instrument),None)
            if not leg:raise ValueError('Instrumento não pertence à estrutura.')
            if (time.time()*1000 if now_ms is None else now_ms)<int(leg['expiry']):raise ValueError('O vencimento desta perna ainda não ocorreu.')
            detail=next(x for x in list_paper(db_path) if x['request_id']==request_id)
            fill=next(x for x in detail['opened_legs'] if x['instrument']==instrument);quantity=d(fill['quantity'])
            if quantity<=0:raise ValueError('Esta perna não teve preenchimento.')
            if any(x['instrument']==instrument for x in position.get('settled_legs',[])):raise ValueError('Esta perna já foi liquidada.')
            if con.execute('SELECT 1 FROM option_structure_leg_settlements WHERE request_id=? AND instrument=?',(request_id,instrument)).fetchone():
                raise ValueError('Esta perna já foi liquidada.')
            intrinsic=max(Decimal(0),price-d(leg['strike'])) if leg['type']=='call' else max(Decimal(0),d(leg['strike'])-price)
            payout=intrinsic*quantity*(1 if leg['side']=='buy' else -1)
            entry=d(fill['average_price'])*quantity*(1 if leg['side']=='buy' else -1)+d(fill['fee'])
            currency=quote['entry_currency'];exit_debit=-payout/price+fee if currency=='BTC' else -payout+fee
            realized=-entry-exit_debit;realized_usd=realized*price if currency=='BTC' else realized
            wallet=json.loads(wallet_row[0]);balance=next((x for x in wallet['balances'] if x['token'].upper()==position['reserved_token'].upper() and x['location'].lower()==quote['venue']),None)
            if not balance:raise ValueError('Saldo de settlement não encontrado.')
            total=d(balance['total']);available=d(balance['available'])
            if total+realized<0 or available+realized<0:raise ValueError('Saldo livre insuficiente para realizar esta perna.')
            balance['total']=str(total+realized);balance['available']=str(available+realized)
            result={'event_id':event_id,'request_id':request_id,'instrument':instrument,'btc_price_usd':str(price),
                    'quantity':str(quantity),'intrinsic_usd':str(payout),'exit_fee':str(fee),
                    'realized_pnl':str(realized),'realized_pnl_usd':str(realized_usd),'currency':currency,
                    'remaining_instrument':next(x['instrument'] for x in quote['legs'] if x['instrument']!=instrument),
                    'remaining_expiry':max(x['expiry'] for x in quote['legs']),'model':'intrínseco estimado; conciliar com settlement da exchange'}
            position.setdefault('settled_legs',[]).append(result)
            position['settled_pnl_native']=str(d(position.get('settled_pnl_native','0'))+realized)
            position['settled_pnl_usd']=str(d(position.get('settled_pnl_usd','0'))+realized_usd)
            con.execute('UPDATE funds SET payload=? WHERE id=1',(json.dumps(wallet),))
            con.execute('UPDATE option_structures SET payload=? WHERE request_id=?',(json.dumps(position),request_id))
            signature=json.dumps({'request_id':request_id,'instrument':instrument,'btc_price':str(price),'fee':str(fee)},sort_keys=True)
            con.execute('INSERT INTO option_structure_leg_settlements VALUES(?,?,?,?,?)',(event_id,request_id,instrument,signature,json.dumps(result)))
            return {**position,'last_settlement':result}
    except (KeyError,TypeError,InvalidOperation,sqlite3.OperationalError) as exc:
        raise ValueError('Dados de settlement por perna inválidos.') from exc


def monitor(db_path,fetch_snapshot=spreads.snapshot):
    output=[]
    for position in list_paper(db_path):
        if position['status']!='aberta':
            output.append(position);continue
        quote=position['quote']
        try:
            flows=_position_flows(db_path,position,fetch_snapshot)
            current_pnl=-d(position.get('entry_debit_actual',quote['debit']))-flows['exit_debit']
            pnl=current_pnl+d(position.get('settled_pnl_native','0'))
            output.append({**position,'market_status':'atualizado','live_quote':flows,
                           'unrealized_pnl':str(pnl),'unrealized_pnl_usd':str((current_pnl*flows['index'] if quote['entry_currency']=='BTC' else current_pnl)+d(position.get('settled_pnl_usd','0')))})
        except (ValueError,OSError,TimeoutError,derive.WebSocketException) as exc:
            output.append({**position,'market_status':'indisponivel','market_error':str(exc)})
    return output
