"""Painel local de posição simulada na Aave."""
import json
import os
import sqlite3
from decimal import Decimal, InvalidOperation
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

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


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/api/position':
            self.respond(200, json.dumps(load()).encode(), 'application/json')
        elif self.path == '/':
            self.respond(200, Path(__file__).with_name('index.html').read_bytes(), 'text/html; charset=utf-8')
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path != '/api/position':
            self.send_error(404)
            return
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if size > 65536:
                raise ValueError('Pedido muito grande.')
            save(json.loads(self.rfile.read(size)))
            self.respond(200, json.dumps(load()).encode(), 'application/json')
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
