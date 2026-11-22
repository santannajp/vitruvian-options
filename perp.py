"""Paper BTC perpetual positions and executable option hedge estimates."""
import json
import sqlite3
import uuid
from contextlib import closing
from decimal import Decimal,InvalidOperation,ROUND_DOWN
import time
import math

import spreads

DAY_MS=86400000


def d(value):
    x=Decimal(str(value))
    if not x.is_finite():raise ValueError('Valor numérico inválido.')
    return x


def save_position(db_path,data):
    try:
        identifier=str(data.get('position_id') or uuid.uuid4()).strip();venue=str(data['venue']).lower()
        subaccount=str(data['subaccount']).strip();side=str(data['side'])
        quantity,multiplier,entry,liquidation,horizon,funding=map(d,(data['quantity'],data['multiplier_btc'],data['entry_price'],data.get('liquidation_price','0'),data['horizon_days'],data.get('funding_rate_percent_per_8h','0')))
        if not identifier or not subaccount or venue not in ('derive','deribit') or side not in ('long','short') or min(quantity,multiplier,entry,liquidation,horizon)<0 or quantity==0 or multiplier==0 or entry==0:
            raise ValueError('Perpétuo simulado ou subconta inválidos.')
        if liquidation and ((side=='long' and liquidation>=entry) or (side=='short' and liquidation<=entry)):
            raise ValueError('Preço de liquidação deve estar abaixo da entrada no long e acima no short.')
        payload={'position_id':identifier,'venue':venue,'subaccount':subaccount,'side':side,'quantity':str(quantity),
                 'multiplier_btc':str(multiplier),'effective_btc':str(quantity*multiplier),'entry_price':str(entry),
                 'liquidation_price':str(liquidation),'horizon_days':str(horizon),
                 'funding_rate_percent_per_8h':str(funding),'updated_at':str(time.time()*1000)}
        with closing(sqlite3.connect(db_path,timeout=10)) as con,con:
            con.execute('CREATE TABLE IF NOT EXISTS perp_positions (position_id TEXT PRIMARY KEY,payload TEXT NOT NULL)')
            con.execute('INSERT OR REPLACE INTO perp_positions VALUES(?,?)',(identifier,json.dumps(payload)))
        return payload
    except (KeyError,TypeError,InvalidOperation,sqlite3.OperationalError) as exc:
        raise ValueError('Dados da posição perpétua inválidos.') from exc


def positions(db_path):
    with closing(sqlite3.connect(db_path)) as con:
        try:rows=con.execute('SELECT payload FROM perp_positions ORDER BY rowid DESC').fetchall()
        except sqlite3.OperationalError:return []
    return [json.loads(row[0]) for row in rows]


def _fee(venue,item,amount,price,index):
    if venue=='deribit':return amount*min(d(item['rate']),price*d(item['fee_cap']))
    return d(item['base_fee'])+min(d(item['rate'])*amount*index,price*amount*d(item['fee_cap']))


def _cdf(value):
    return (1+math.erf(value/math.sqrt(2)))/2


def option_delta(kind,spot,strike,days,volatility_percent):
    spot,strike,days,vol=map(float,(spot,strike,days,volatility_percent))
    if spot<=0 or strike<=0 or vol<=0:raise ValueError('Preço, strike e volatilidade devem ser positivos para delta.')
    t=days/365
    if t<=0:
        call=1.0 if spot>strike else 0.0 if spot<strike else .5
    else:
        sigma=vol/100
        d1=(math.log(spot/strike)+0.5*sigma*sigma*t)/(sigma*math.sqrt(t))
        call=_cdf(d1)
    return call if kind=='call' else call-1


def hedge(db_path,data,now_ms=None,universe_fetch=spreads.universe,snapshot_fetch=spreads.snapshot,index_fetch=spreads.reference_index):
    try:
        position_id=str(data['position_id']).strip();hedge_percent=d(data['hedge_percent']);budget_usd=d(data['budget_usd'])
        event_id=str(data.get('event_id') or uuid.uuid4()).strip()
        mode=str(data.get('selection_mode','proximity'))
        delta_target=d(data.get('target_delta_abs','0.25'));distance_target=d(data.get('target_distance_percent','2'))
        volatility=d(data.get('volatility_percent','60'));size_tolerance=d(data.get('size_tolerance_percent','5'))
        renew_before=d(data.get('renewal_before_days','7'))
        now=Decimal(str(now_ms if now_ms is not None else time.time()*1000))
        with closing(sqlite3.connect(db_path)) as con:
            try:
                prior=con.execute('SELECT payload FROM perp_hedges WHERE event_id=?',(event_id,)).fetchone()
            except sqlite3.OperationalError:prior=None
            if prior:
                existing=json.loads(prior[0])
                request=existing.get('request',{})
                compare={k:str(data.get(k,'')) for k in ('position_id','hedge_percent','budget_usd','selection_mode','target_delta_abs','target_distance_percent','volatility_percent','size_tolerance_percent','renewal_before_days')}
                if request!=compare:raise ValueError('ID da renovação reutilizado com outros parâmetros.')
                return existing
            row=con.execute('SELECT payload FROM perp_positions WHERE position_id=?',(position_id,)).fetchone()
        if not row:raise ValueError('Perpétuo simulado não encontrado.')
        position=json.loads(row[0]);venue=position['venue'];side=position['side'];horizon=d(position['horizon_days'])
        if hedge_percent<0 or hedge_percent>100 or budget_usd<0 or mode not in ('proximity','delta','distance'):
            raise ValueError('Percentual, modo e orçamento inválidos.')
        if delta_target<0 or delta_target>1 or distance_target<0 or volatility<=0 or size_tolerance<0 or renew_before<0:
            raise ValueError('Alvo de delta, distância, volatilidade ou tolerâncias inválidos.')
        desired=d(position['effective_btc'])*hedge_percent/100
        index=d(index_fetch(venue));target_expiry=now+horizon*DAY_MS
        instruments=universe_fetch(venue,'*')
        option_type='put' if side=='long' else 'call'
        eligible_expiries=[d(x['expiry']) for x in instruments if x.get('type')==option_type and d(x['expiry'])>=target_expiry]
        if not eligible_expiries:raise ValueError(f'Sem {option_type} elegível para o horizonte de {horizon} dias.')
        expiry=min(eligible_expiries)
        eligible=[x for x in instruments if x.get('type')==option_type and d(x['expiry'])==expiry and
                  (d(x['strike'])<=index if side=='long' else d(x['strike'])>=index)]
        if not eligible:raise ValueError('Sem strike protetivo elegível ao lado do índice atual.')
        expiry_days=max(Decimal(0),(expiry-now)/DAY_MS)
        def selection_metric(item):
            strike=d(item['strike'])
            if mode=='proximity':return abs(strike-index)
            if mode=='distance':return abs((index-strike if side=='long' else strike-index)/index*100-distance_target)
            return abs(d(str(abs(option_delta(option_type,index,strike,expiry_days,volatility))))-delta_target)
        selected=min(eligible,key=selection_metric)
        quote=snapshot_fetch(venue,selected['name'])
        if now-d(quote['timestamp'])>30000:raise ValueError('Livro da opção de proteção desatualizado.')
        if not quote['asks']:raise ValueError('Sem oferta para comprar a opção de proteção.')
        ask,available=map(d,quote['asks'][0]);step=d(quote['step']);minimum=d(quote['minimum'])
        unit_cost=ask+ (min(d(quote['rate']),ask*d(quote['fee_cap'])) if venue=='deribit' else min(d(quote['rate'])*index,ask*d(quote['fee_cap'])))
        budget_native=budget_usd/index if venue=='deribit' else budget_usd
        base=d(quote.get('base_fee','0')) if venue=='derive' else Decimal(0)
        budget_capacity=max(Decimal(0),(budget_native-base)/unit_cost) if unit_cost else Decimal(0)
        amount=min(desired,available,budget_capacity)
        amount=(amount/step).to_integral_value(rounding=ROUND_DOWN)*step
        if amount<minimum:amount=Decimal(0)
        fee=_fee(venue,quote,amount,ask,index) if amount else Decimal(0)
        premium_native=ask*amount+fee
        premium_usd=premium_native*index if venue=='deribit' else premium_native
        covered=amount
        residual=max(Decimal(0),d(position['effective_btc'])-covered)
        notional=d(position['effective_btc'])*index
        cycles=horizon*3
        funding=-1 if side=='long' else 1
        funding_pnl=notional*d(position['funding_rate_percent_per_8h'])/100*cycles*funding
        prices={index*Decimal('0.8'),index,index*Decimal('1.2')}
        liq=d(position['liquidation_price'])
        if liq:prices.add(liq)
        scenarios=[]
        for price in sorted(prices):
            perp=(price-d(position['entry_price']))*d(position['effective_btc'])*(1 if side=='long' else -1)
            payout=(max(Decimal(0),d(quote['strike'])-price) if option_type=='put' else max(Decimal(0),price-d(quote['strike'])))*covered
            without=perp+funding_pnl
            with_option=without+payout-premium_usd
            scenarios.append({'btc_price_usd':str(price),'perp_pnl_usd':str(perp),'funding_pnl_usd':str(funding_pnl),
                              'option_intrinsic_usd':str(payout),'pnl_without_option_usd':str(without),
                              'pnl_with_option_usd':str(with_option),
                              'at_liquidation_price':bool(liq and price==liq)})
        result={'position':position,'venue':venue,'subaccount':position['subaccount'],'option':selected['name'],
                'option_type':option_type,'strike':str(quote['strike']),'expiry':quote['expiry'],
                'index_price':str(index),'timestamp':quote['timestamp'],'hedge_percent':str(hedge_percent),
                'requested_coverage_btc':str(desired),'covered_btc':str(covered),
                'covered_perpetual_contracts':str(covered/d(position['multiplier_btc'])) if position['multiplier_btc']!='0' else '0',
                'residual_exposure_btc':str(residual),'liquidation_price':position['liquidation_price'],
                'option_available_btc':str(available),'premium_native':str(premium_native),
                'premium_currency':'BTC' if venue=='deribit' else 'USDC','premium_usd':str(premium_usd),
                'fee_native':str(fee),'budget_usd':str(budget_usd),'funding_pnl_usd_estimate':str(funding_pnl),
                'funding_cycles_estimate':str(cycles),'scenarios':scenarios,
                'status':'sem_cobertura_no_lote' if amount==0 else 'simulado',
                'risk_note':'Hedge de opção não impede liquidação do perpétuo por margem antes da liquidação da opção. Delta usa Black-Scholes com taxa zero e IV constante informada; payoff é intrínseco estimado e não replica settlement, margem ou skew oficiais. Funding, taxas, multiplicador e moedas devem ser conferidos.'}
        signed_delta=d(str(option_delta(option_type,index,d(quote['strike']),expiry_days,volatility)))
        with closing(sqlite3.connect(db_path)) as con:
            try:previous_row=con.execute('SELECT payload FROM perp_hedges WHERE position_id=? ORDER BY rowid DESC LIMIT 1',(position_id,)).fetchone()
            except sqlite3.OperationalError:previous_row=None
        previous=json.loads(previous_row[0]) if previous_row else None
        renewal_reasons=[];renewal_action='inicial'
        if previous:
            prior_size=d(previous['position']['effective_btc']);size_change=abs(d(position['effective_btc'])-prior_size)/prior_size*100 if prior_size else Decimal(100)
            if size_change>size_tolerance:renewal_reasons.append(f'Exposição mudou {size_change}% acima da tolerância {size_tolerance}%.')
            if previous.get('option')!=selected['name']:renewal_reasons.append('O strike elegível mudou com o mercado ou alvo.')
            premium_change=abs(premium_usd-d(previous['premium_usd']))/max(Decimal('0.00000001'),d(previous['premium_usd']))*100
            if premium_change>size_tolerance:renewal_reasons.append(f'Prêmio mudou {premium_change}% acima da tolerância {size_tolerance}%.')
            if d(previous['expiry'])-now<=renew_before*DAY_MS:renewal_reasons.append('A proteção anterior entrou na janela de renovação.')
            if desired>d(previous['covered_btc']):renewal_reasons.append('O alvo de cobertura atual excede a cobertura anterior.')
            renewal_action='renovar' if renewal_reasons else 'manter'
        if amount<desired and amount>0:renewal_reasons.append('Orçamento ou profundidade cobre apenas parte do nominal desejado.')
        if amount==0:renewal_reasons.append('Orçamento ou lote mínimo não permite cobertura nesta cotação.')
        previous_close=None
        if previous:
            try:
                prior_quote=snapshot_fetch(venue,previous['option'])
                if now-d(prior_quote['timestamp'])>30000 or not prior_quote['bids']:
                    raise ValueError('Livro antigo desatualizado ou sem oferta de saída.')
                close_price,close_available=map(d,prior_quote['bids'][0]);close_amount=min(d(previous['covered_btc']),close_available)
                close_fee=_fee(venue,prior_quote,close_amount,close_price,index) if close_amount else Decimal(0)
                proceeds=close_price*close_amount-close_fee
                previous_close={'available_close_btc':str(close_amount),'residual_old_coverage_btc':str(d(previous['covered_btc'])-close_amount),
                                'proceeds_native':str(proceeds),'proceeds_usd':str(proceeds*index if venue=='deribit' else proceeds),
                                'timestamp':prior_quote['timestamp']}
            except (ValueError,KeyError,TypeError,InvalidOperation,OSError,TimeoutError):
                previous_close=None
                renewal_reasons.append('Não foi possível marcar a saída da cobertura anterior; custo líquido não disponível.')
        renewal_cost=premium_usd-d(previous_close['proceeds_usd']) if previous_close else None
        if previous and renewal_reasons:renewal_action='renovar'
        request={k:str(data.get(k,'')) for k in ('position_id','hedge_percent','budget_usd','selection_mode','target_delta_abs','target_distance_percent','volatility_percent','size_tolerance_percent','renewal_before_days')}
        result['request']=request;result['event_id']=event_id
        result.update({'selection_mode':mode,'delta':str(signed_delta),'absolute_delta':str(abs(signed_delta)),
                       'strike_distance_percent':str(abs(d(quote['strike'])-index)/index*100),
                       'selection_explanation':{'proximity':'strike elegível de menor distância ao índice',
                           'delta':f'delta absoluto mais próximo de {delta_target} pelo modelo Black-Scholes de volatilidade {volatility}%',
                           'distance':f'distância percentual mais próxima de {distance_target}% do índice'}[mode],
                       'previous_hedge_event_id':previous.get('event_id') if previous else None,
                       'renewal_action':renewal_action,'renewal_reasons':renewal_reasons,
                       'previous_close_quote':previous_close,
                       'renewal_cost_usd_estimate':str(renewal_cost) if renewal_cost is not None else None})
        with closing(sqlite3.connect(db_path,timeout=10)) as con,con:
            con.execute('CREATE TABLE IF NOT EXISTS perp_hedges (event_id TEXT PRIMARY KEY,position_id TEXT NOT NULL,payload TEXT NOT NULL)')
            previous=con.execute('SELECT payload FROM perp_hedges WHERE event_id=?',(event_id,)).fetchone()
            if previous:return json.loads(previous[0])
            con.execute('INSERT INTO perp_hedges VALUES(?,?,?)',(event_id,position_id,json.dumps(result)))
        return result
    except (KeyError,TypeError,InvalidOperation,sqlite3.OperationalError) as exc:
        raise ValueError('Dados ou resposta do mercado de hedge inválidos.') from exc


def hedge_history(db_path):
    with closing(sqlite3.connect(db_path)) as con:
        try:rows=con.execute('SELECT payload FROM perp_hedges ORDER BY rowid DESC').fetchall()
        except sqlite3.OperationalError:return []
    return [json.loads(row[0]) for row in rows]
