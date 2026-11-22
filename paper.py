"""Persistent paper trading for option spreads; this module never sends orders."""
import json
import sqlite3
import uuid
from contextlib import closing
from decimal import Decimal, InvalidOperation

import spreads


def _d(value):
    number = Decimal(str(value))
    if not number.is_finite():
        raise ValueError('Valor não finito.')
    return number


def open_spread(db_path, request, preview=spreads.preview):
    """Recot a strategy at executable top of book and atomically reserve paper cash."""
    try:
        request_id = str(request.get('request_id') or uuid.uuid4()).strip()
        venue, direction, entry = (str(request[key]).strip() for key in ('venue', 'direction', 'entry'))
        buy, sell, size = (str(request[key]).strip() for key in ('buy', 'sell', 'size'))
        token = str(request.get('token') or ('BTC' if venue == 'deribit' else 'USDC')).strip()
        tolerance = _d(request.get('tolerance_percent', '2'))
        proposed = _d(request['proposed_debit'])
        if not request_id or tolerance < 0 or tolerance > 100:
            raise ValueError('Identificador e tolerância entre 0 e 100% são obrigatórios.')
        if entry not in ('debito', 'credito') or (entry == 'debito' and proposed <= 0) or (entry == 'credito' and proposed >= 0):
            raise ValueError('Informe o preço líquido proposto com o sinal correspondente à entrada.')
        currency = 'BTC' if venue == 'deribit' else 'USDC'
        if token.upper() != currency:
            raise ValueError(f'A moeda do saldo deve ser {currency} para esta exchange.')
        identity = json.dumps({'venue':venue, 'direction':direction, 'entry':entry, 'buy':buy, 'sell':sell,
                               'size':size, 'token':token, 'proposed_debit':str(proposed),
                               'tolerance_percent':str(tolerance)}, sort_keys=True)
        with closing(sqlite3.connect(db_path, timeout=10)) as con:
            con.execute('CREATE TABLE IF NOT EXISTS paper_spreads (id INTEGER PRIMARY KEY AUTOINCREMENT, request_id TEXT UNIQUE NOT NULL, request TEXT NOT NULL, status TEXT NOT NULL, payload TEXT NOT NULL)')
            old = con.execute('SELECT request, payload FROM paper_spreads WHERE request_id=?', (request_id,)).fetchone()
            if old:
                if old[0] != identity:
                    raise ValueError('Identificador já usado para outra operação.')
                return json.loads(old[1])
        quote = preview(venue, direction, entry, buy, sell, size)
        recotado = _d(quote['debit'])
        adverse = max(Decimal(0), recotado - proposed) if entry == 'debito' else max(Decimal(0), proposed - recotado)
        reference = abs(proposed)
        slippage = adverse / reference * 100 if reference else (Decimal(0) if adverse == 0 else Decimal('Infinity'))
        if slippage > tolerance:
            payload = {'status': 'expirada', 'request_id':request_id, 'reason': 'Recotação excede a tolerância configurada.',
                    'proposed_debit': str(proposed), 'recotado': str(recotado), 'slippage_percent': str(slippage),
                    'tolerance_percent': str(tolerance), 'quote': quote}
            with closing(sqlite3.connect(db_path, timeout=10)) as con, con:
                con.execute('BEGIN IMMEDIATE')
                old = con.execute('SELECT request,payload FROM paper_spreads WHERE request_id=?', (request_id,)).fetchone()
                if old:
                    if old[0] != identity:
                        raise ValueError('Identificador já usado para outra operação.')
                    return json.loads(old[1])
                row = con.execute('SELECT payload FROM funds WHERE id=1').fetchone()
                payload['wallet_before'] = json.loads(row[0]) if row else None
                payload['wallet_after'] = payload['wallet_before']
                con.execute('INSERT INTO paper_spreads(request_id,request,status,payload) VALUES(?,?,?,?)',
                            (request_id,identity,'expirada',json.dumps(payload)))
            return payload
        currency = quote['entry_currency']
        risk_usd = _d(quote['risk_estimate_usd'])
        if entry == 'debito':
            reserve = max(Decimal(0), recotado)
        elif currency == 'BTC':
            reserve = risk_usd / _d(quote['reference_btc_usd'])
        else:
            reserve = risk_usd
        with closing(sqlite3.connect(db_path, timeout=10)) as con, con:
            con.execute('BEGIN IMMEDIATE')
            con.execute('CREATE TABLE IF NOT EXISTS paper_spreads (id INTEGER PRIMARY KEY AUTOINCREMENT, request_id TEXT UNIQUE NOT NULL, request TEXT NOT NULL, status TEXT NOT NULL, payload TEXT NOT NULL)')
            old = con.execute('SELECT request, payload FROM paper_spreads WHERE request_id=?', (request_id,)).fetchone()
            if old:
                if old[0] != identity:
                    raise ValueError('Identificador já usado para outra operação.')
                return json.loads(old[1])
            row = con.execute('SELECT payload FROM funds WHERE id=1').fetchone()
            if not row:
                raise ValueError('Cadastre o saldo de papel primeiro.')
            wallet = json.loads(row[0])
            balance = next((item for item in wallet['balances'] if item['token'].upper()==token.upper() and item['location'].lower()==venue.lower()), None)
            if not balance:
                raise ValueError(f'Cadastre saldo de {token} em {venue}.')
            available = _d(balance['available'])
            if reserve > available:
                raise ValueError(f'Orçamento insuficiente: disponível {available} {token}; necessário {reserve} {token}.')
            balance['available'] = str(available - reserve)
            balance['margem'] = str(_d(balance.get('margem','0')) + reserve)
            payload = {'status':'aberta', 'request_id':request_id, 'quote':quote, 'currency':currency,
                       'reserved':str(reserve), 'reserved_token':token, 'proposed_debit':str(proposed),
                       'recotado':str(recotado), 'slippage_percent':str(slippage), 'opened_legs':[
                           {'instrument':buy, 'side':'buy', 'quantity':size, 'average_price':quote['buy_price']},
                           {'instrument':sell, 'side':'sell', 'quantity':size, 'average_price':quote['sell_price']}],
                       'fees':quote['fees'], 'wallet':wallet}
            encoded = json.dumps(payload)
            con.execute('UPDATE funds SET payload=? WHERE id=1', (json.dumps(wallet),))
            con.execute('INSERT INTO paper_spreads(request_id,request,status,payload) VALUES(?,?,?,?)',
                        (request_id, identity, 'aberta', encoded))
            return payload
    except (KeyError, TypeError, InvalidOperation, sqlite3.OperationalError) as exc:
        raise ValueError('Dados de abertura de papel inválidos.') from exc


def list_spreads(db_path):
    with closing(sqlite3.connect(db_path)) as con:
        try:
            rows = con.execute('SELECT payload FROM paper_spreads ORDER BY id DESC').fetchall()
        except sqlite3.OperationalError:
            return []
    return [reconciled(db_path, item) for item in (json.loads(row[0]) for row in rows)]


def record_fill(db_path, data):
    """Record authoritative cumulative fill snapshots; unique events are replay-safe."""
    try:
        strategy = str(data['strategy_id']).strip()
        event_id = str(data['event_id']).strip()
        instrument = str(data['instrument']).strip()
        observed_at = str(data['observed_at']).strip()
        quantity, price, fee = map(_d, (data['quantity'], data['average_price'], data['fee']))
        if not strategy or not event_id or not observed_at or quantity < 0 or price < 0 or fee < 0:
            raise ValueError('Informe identificador, horário e quantidades não negativas.')
        with closing(sqlite3.connect(db_path, timeout=10)) as con, con:
            con.execute('BEGIN IMMEDIATE')
            con.execute('CREATE TABLE IF NOT EXISTS paper_fill_events (event_id TEXT PRIMARY KEY, strategy_id TEXT NOT NULL, instrument TEXT NOT NULL, observed_at TEXT NOT NULL, quantity TEXT NOT NULL, average_price TEXT NOT NULL, fee TEXT NOT NULL, payload TEXT NOT NULL)')
            row = con.execute('SELECT payload FROM paper_spreads WHERE request_id=?', (strategy,)).fetchone()
            if not row:
                raise ValueError('Posição simulada não encontrada.')
            spread = json.loads(row[0])
            if instrument not in (spread['quote']['buy'], spread['quote']['sell']):
                raise ValueError('Instrumento não pertence a esta posição.')
            if quantity > _d(spread['quote']['size']):
                raise ValueError('Preenchimento acumulado excede a quantidade solicitada.')
            event = {'strategy_id':strategy,'instrument':instrument,'observed_at':observed_at,
                     'quantity':str(quantity),'average_price':str(price),'fee':str(fee)}
            encoded = json.dumps(event, sort_keys=True)
            old = con.execute('SELECT payload FROM paper_fill_events WHERE event_id=?', (event_id,)).fetchone()
            if old:
                if old[0] != encoded:
                    raise ValueError('Identificador de preenchimento reutilizado com dados diferentes.')
                return reconciled(db_path, spread)
            con.execute('INSERT INTO paper_fill_events VALUES(?,?,?,?,?,?,?,?)',
                        (event_id,strategy,instrument,observed_at,str(quantity),str(price),str(fee),encoded))
            con.commit()
            return reconciled(db_path, spread)
    except (KeyError, TypeError, InvalidOperation, sqlite3.OperationalError) as exc:
        raise ValueError('Dados do preenchimento inválidos.') from exc


def reconciled(db_path, spread):
    """Rebuild each leg from its newest cumulative venue snapshot after process restart."""
    if spread.get('status') != 'aberta':
        return spread
    with closing(sqlite3.connect(db_path)) as con:
        try:
            rows = con.execute('SELECT instrument,observed_at,quantity,average_price,fee FROM paper_fill_events WHERE strategy_id=? ORDER BY observed_at DESC,event_id DESC',
                               (spread['request_id'],)).fetchall()
        except sqlite3.OperationalError:
            rows = []
    latest = {}
    for instrument, observed_at, quantity, price, fee in rows:
        latest.setdefault(instrument, {'instrument':instrument,'observed_at':observed_at,
                                      'quantity':quantity,'average_price':price,'fee':fee})
    requested = _d(spread['quote']['size'])
    legs = []
    for instrument, side, default_price in ((spread['quote']['buy'],'buy',spread['quote']['buy_price']),
                                             (spread['quote']['sell'],'sell',spread['quote']['sell_price'])):
        leg = latest.get(instrument, {'instrument':instrument,'quantity':str(requested),
                    'average_price':default_price,'fee':spread['fees'],'observed_at':None})
        legs.append({**leg,'side':side,'residual_quantity':str(requested-_d(leg['quantity']))})
    spread['opened_legs'] = legs
    spread['reconciled'] = _d(legs[0]['quantity']) == _d(legs[1]['quantity'])
    spread['roll_blocked'] = not spread['reconciled']
    spread['unhedged_quantity'] = str(abs(_d(legs[0]['quantity'])-_d(legs[1]['quantity'])))
    spread['effective_fees'] = str(sum((_d(leg['fee']) for leg in legs), Decimal(0)))
    return spread
