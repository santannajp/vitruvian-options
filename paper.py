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
    return [json.loads(row[0]) for row in rows]
