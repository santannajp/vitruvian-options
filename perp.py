"""Paper BTC perpetual positions and executable option hedge estimates."""
import json
import sqlite3
import uuid
from contextlib import closing
from decimal import Decimal,InvalidOperation,ROUND_DOWN
import time

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


def hedge(db_path,data,now_ms=None,universe_fetch=spreads.universe,snapshot_fetch=spreads.snapshot,index_fetch=spreads.reference_index):
    try:
        position_id=str(data['position_id']).strip();hedge_percent=d(data['hedge_percent']);budget_usd=d(data['budget_usd'])
        now=Decimal(str(now_ms if now_ms is not None else time.time()*1000))
        with closing(sqlite3.connect(db_path)) as con:
            row=con.execute('SELECT payload FROM perp_positions WHERE position_id=?',(position_id,)).fetchone()
        if not row:raise ValueError('Perpétuo simulado não encontrado.')
        position=json.loads(row[0]);venue=position['venue'];side=position['side'];horizon=d(position['horizon_days'])
        if hedge_percent<0 or hedge_percent>100 or budget_usd<0:raise ValueError('Percentual e orçamento inválidos.')
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
        selected=min(eligible,key=lambda x:abs(d(x['strike'])-index))
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
                'risk_note':'Hedge de opção não impede liquidação do perpétuo por margem antes da liquidação da opção. Funding, taxas e payoff são cenários estimados; moedas e especificação de cada contrato devem ser conferidas.'}
        event_id=str(data.get('event_id') or uuid.uuid4()).strip();result['event_id']=event_id
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
