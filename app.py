"""Painel local de posição simulada na Aave."""
import json
import os
import sqlite3
from decimal import Decimal, InvalidOperation
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

DB = Path(os.environ.get('VITRUVIAN_DB', 'vitruvian.db'))
FIELDS = ('account', 'network', 'market', 'token', 'contract', 'quantity', 'price', 'threshold', 'debt_token', 'debt_contract', 'debt_quantity', 'debt_price', 'source', 'observed_at')


def save(data):
    values = {key: str(data.get(key, '')).strip() for key in FIELDS}
    if any(not value for value in values.values()):
        raise ValueError('Preencha todos os campos.')
    try:
        numbers = {key: Decimal(values[key]) for key in ('quantity', 'price', 'threshold', 'debt_quantity', 'debt_price')}
        if any(not n.is_finite() or n < 0 for n in numbers.values()) or numbers['threshold'] > 100:
            raise ValueError('Informe valores não negativos e limiar entre 0 e 100.')
    except InvalidOperation as exc:
        raise ValueError('Informe valores numéricos válidos.') from exc
    with sqlite3.connect(DB) as con:
        con.execute('CREATE TABLE IF NOT EXISTS position (id INTEGER PRIMARY KEY, payload TEXT NOT NULL)')
        con.execute('INSERT OR REPLACE INTO position VALUES (1, ?)', (json.dumps(values),))
    return values


def load():
    with sqlite3.connect(DB) as con:
        con.execute('CREATE TABLE IF NOT EXISTS position (id INTEGER PRIMARY KEY, payload TEXT NOT NULL)')
        row = con.execute('SELECT payload FROM position WHERE id = 1').fetchone()
    if not row:
        return None
    data = json.loads(row[0])
    debt = Decimal(data['debt_quantity']) * Decimal(data['debt_price'])
    collateral = Decimal(data['quantity']) * Decimal(data['price'])
    data['collateral_value'] = str(collateral)
    data['health_factor'] = str(collateral * Decimal(data['threshold']) / 100 / debt) if debt else None
    return data


def calculate_scenario(data):
    """Calculate with fixed token/BTC ratios and fixed stablecoin USD prices."""
    try:
        if any(not str(data.get(key, '')).strip() for key in ('account', 'network', 'market', 'observed_at')):
            raise ValueError('Informe conta, rede, mercado e data do cenário.')
        btc = Decimal(str(data['btc_price']))
        collateral = data['collateral']
        debts = data['debts']
        if not btc.is_finite() or btc <= 0 or not collateral or not debts:
            raise ValueError('Informe preço BTC positivo e pelo menos um ativo em cada lista.')
        if len({str(item.get('contract', '')).lower() for item in collateral}) != len(collateral) or len({str(item.get('contract', '')).lower() for item in debts}) != len(debts):
            raise ValueError('Cada contrato deve aparecer uma vez em cada lista.')
        weighted = Decimal(0)
        debt_total = Decimal(0)
        assumptions = []
        for item in collateral:
            if not str(item.get('token', '')).strip() or not str(item.get('contract', '')).strip():
                raise ValueError('Informe o token e contrato de cada garantia.')
            quantity = Decimal(str(item['quantity']))
            ratio = Decimal(str(item['btc_ratio']))
            threshold = Decimal(str(item['threshold']))
            if not all(x.is_finite() and x >= 0 for x in (quantity, ratio, threshold)) or threshold > 100:
                raise ValueError('Valores de garantia inválidos.')
            weighted += quantity * ratio * btc * threshold / 100
            assumptions.append({'token': str(item['token']), 'btc_ratio': str(ratio)})
        for item in debts:
            if not str(item.get('token', '')).strip() or not str(item.get('contract', '')).strip():
                raise ValueError('Informe o token e contrato de cada dívida.')
            quantity = Decimal(str(item['quantity']))
            price = Decimal(str(item['price']))
            if not all(x.is_finite() and x >= 0 for x in (quantity, price)):
                raise ValueError('Valores de dívida inválidos.')
            debt_total += quantity * price
        weighted_per_btc = weighted / btc
        return {
            'health_factor': str(weighted / debt_total) if debt_total else None,
            'liquidation_btc_price': str(debt_total / weighted_per_btc) if weighted_per_btc and debt_total else None,
            'assumptions': assumptions,
            'stablecoins': [{'token': str(item['token']), 'price': str(item['price'])} for item in debts],
        }
    except (KeyError, TypeError, InvalidOperation) as exc:
        raise ValueError('Dados do cenário inválidos.') from exc


def scenario(data=None, snapshot=False, identity=None):
    with sqlite3.connect(DB) as con:
        con.execute('CREATE TABLE IF NOT EXISTS scenario_positions (account TEXT, network TEXT, market TEXT, current TEXT, original TEXT, PRIMARY KEY (account, network, market))')
        if data is not None:
            result = calculate_scenario(data)
            identity = tuple(data[key].strip() for key in ('account', 'network', 'market'))
        if identity is None:
            row = con.execute('SELECT current, original FROM scenario_positions ORDER BY rowid DESC LIMIT 1').fetchone()
        else:
            row = con.execute('SELECT current, original FROM scenario_positions WHERE account = ? AND network = ? AND market = ?', identity).fetchone()
        if data is not None:
            current = json.dumps({'input': data, 'result': result})
            original = current if snapshot else (row[1] if row else None)
            con.execute('INSERT OR REPLACE INTO scenario_positions VALUES (?, ?, ?, ?, ?)', (*identity, current, original))
            return {'current': json.loads(current), 'original': json.loads(original) if original else None}
        return {'current': json.loads(row[0]), 'original': json.loads(row[1]) if row[1] else None} if row else None


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/api/position':
            self.respond(200, json.dumps(load()).encode(), 'application/json')
        elif urlsplit(self.path).path == '/api/scenario':
            params = parse_qs(urlsplit(self.path).query)
            identity = tuple(params.get(key, [''])[0] for key in ('account', 'network', 'market')) if params else None
            self.respond(200, json.dumps(scenario(identity=identity)).encode(), 'application/json')
        elif self.path == '/':
            self.respond(200, Path(__file__).with_name('index.html').read_bytes(), 'text/html; charset=utf-8')
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path not in ('/api/position', '/api/scenario'):
            self.send_error(404)
            return
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if size > 65536:
                raise ValueError('Pedido muito grande.')
            data = json.loads(self.rfile.read(size))
            if self.path == '/api/scenario':
                result = scenario(data, bool(data.get('snapshot')))
            else:
                save(data)
                result = load()
            self.respond(200, json.dumps(result).encode(), 'application/json')
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            self.respond(400, json.dumps({'error': str(exc)}).encode(), 'application/json')

    def respond(self, status, body, content_type):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == '__main__':
    ThreadingHTTPServer(('127.0.0.1', 8000), Handler).serve_forever()
