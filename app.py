"""Painel local de posição simulada na Aave."""
import json
import os
import sqlite3
from contextlib import closing
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
    with closing(sqlite3.connect(DB)) as con, con:
        con.execute('CREATE TABLE IF NOT EXISTS position (id INTEGER PRIMARY KEY, payload TEXT NOT NULL)')
        con.execute('INSERT OR REPLACE INTO position VALUES (1, ?)', (json.dumps(values),))
    return values


def load():
    with closing(sqlite3.connect(DB)) as con, con:
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
    with closing(sqlite3.connect(DB)) as con, con:
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


ALLOCATIONS = ('reserva', 'grid', 'premios', 'margem', 'apostas')


def funds(data=None):
    with closing(sqlite3.connect(DB)) as con, con:
        con.execute('CREATE TABLE IF NOT EXISTS funds (id INTEGER PRIMARY KEY, payload TEXT NOT NULL)')
        row = con.execute('SELECT payload FROM funds WHERE id = 1').fetchone()
        if data is None:
            return json.loads(row[0]) if row else None
        try:
            balances = data['balances']
            if not isinstance(balances, list) or not balances:
                raise ValueError('Informe ao menos um saldo.')
            seen = set()
            cleaned = []
            for balance in balances:
                token = str(balance['token']).strip()
                location = str(balance['location']).strip()
                key = (token.lower(), location.lower())
                if not token or not location or key in seen:
                    raise ValueError('Informe saldos únicos por moeda e local.')
                seen.add(key)
                total = Decimal(str(balance['total']))
                allocated = {key: Decimal(str(balance.get(key, '0'))) for key in ALLOCATIONS}
                if any(not value.is_finite() or value < 0 for value in [total, *allocated.values()]):
                    raise ValueError('Informe valores não negativos e finitos.')
                if sum(allocated.values()) > total:
                    raise ValueError('As reservas não podem exceder o saldo.')
                cleaned.append({'token': token, 'location': location, 'total': str(total),
                                **{key: str(value) for key, value in allocated.items()},
                                'available': str(total - sum(allocated.values()))})
            grid_btc = Decimal(str(data.get('grid_btc', '0')))
            if not grid_btc.is_finite() or grid_btc < 0:
                raise ValueError('Informe o BTC do grid como valor não negativo.')
            result = {'balances': cleaned, 'grid_btc': str(grid_btc)}
            con.execute('INSERT OR REPLACE INTO funds VALUES (1, ?)', (json.dumps(result),))
            return result
        except (KeyError, TypeError, InvalidOperation) as exc:
            raise ValueError('Dados dos saldos inválidos.') from exc


def repay(data):
    try:
        identity = tuple(str(data[key]).strip() for key in ('account', 'network', 'market'))
        token = str(data['token']).strip()
        request_id = str(data['request_id']).strip()
        if not request_id:
            raise ValueError('Identificador da operação obrigatório.')
        amount = Decimal(str(data['amount']))
        if not amount.is_finite() or amount <= 0:
            raise ValueError('Informe uma quantia positiva.')
        with closing(sqlite3.connect(DB)) as con, con:
            con.execute('BEGIN IMMEDIATE')
            con.execute('CREATE TABLE IF NOT EXISTS repayments (request_id TEXT PRIMARY KEY, request TEXT NOT NULL, result TEXT NOT NULL)')
            previous = con.execute('SELECT request, result FROM repayments WHERE request_id = ?', (request_id,)).fetchone()
            signature = json.dumps({'identity': identity, 'token': token, 'amount': str(amount)}, sort_keys=True)
            if previous:
                if previous[0] != signature:
                    raise ValueError('Identificador já utilizado para outra amortização.')
                return json.loads(previous[1])
            row = con.execute('SELECT payload FROM funds WHERE id = 1').fetchone()
            scenario_row = con.execute('SELECT current FROM scenario_positions WHERE account = ? AND network = ? AND market = ?', identity).fetchone()
            if not row or not scenario_row:
                raise ValueError('Cadastre os saldos e o cenário Aave primeiro.')
            wallet = json.loads(row[0])
            current = json.loads(scenario_row[0])
            balance = next((item for item in wallet['balances'] if item['token'].lower() == token.lower() and item['location'].lower() == 'rede'), None)
            matching_debts = [item for item in current['input']['debts'] if item['token'].lower() == token.lower()]
            debt = matching_debts[0] if len(matching_debts) == 1 else None
            if not balance or not debt:
                raise ValueError('A dívida e o saldo na rede devem usar a mesma stablecoin.')
            available = Decimal(balance['available']) + Decimal(balance['reserva'])
            if amount > available or amount > Decimal(debt['quantity']):
                raise ValueError('Quantia excede a dívida ou o caixa disponível na rede.')
            used_reserve = min(amount, Decimal(balance['reserva']))
            balance['reserva'] = str(Decimal(balance['reserva']) - used_reserve)
            balance['total'] = str(Decimal(balance['total']) - amount)
            balance['available'] = str(Decimal(balance['available']) - (amount - used_reserve))
            debt['quantity'] = str(Decimal(debt['quantity']) - amount)
            current['result'] = calculate_scenario(current['input'])
            con.execute('UPDATE funds SET payload = ? WHERE id = 1', (json.dumps(wallet),))
            con.execute('UPDATE scenario_positions SET current = ? WHERE account = ? AND network = ? AND market = ?', (json.dumps(current), *identity))
            result = {'funds': wallet, 'scenario': current}
            con.execute('INSERT INTO repayments VALUES (?, ?, ?)', (request_id, signature, json.dumps(result)))
            return result
    except (KeyError, TypeError, InvalidOperation, sqlite3.OperationalError) as exc:
        raise ValueError('Dados de amortização inválidos ou cenário não cadastrado.') from exc


def simulate_liquidation(data):
    """Estimate a single Aave V3.3 liquidation using supplied reserve parameters."""
    try:
        identity = tuple(str(data[key]).strip() for key in ('account', 'network', 'market'))
        stored = scenario(identity=identity)
        if not stored:
            raise ValueError('Cadastre o cenário Aave desta conta primeiro.')
        position = stored['current']['input']
        original = calculate_scenario(position)
        hf = original['health_factor']
        collateral = next((x for x in position['collateral'] if x['contract'].lower() == str(data['collateral_contract']).lower()), None)
        debt = next((x for x in position['debts'] if x['contract'].lower() == str(data['debt_contract']).lower()), None)
        if not collateral or not debt:
            raise ValueError('Selecione contratos de garantia e dívida existentes.')
        requested = Decimal(str(data['debt_to_cover']))
        bonus = Decimal(str(data['bonus_percent']))
        cash = Decimal(str(data['cash_usd']))
        buy_price = Decimal(str(data['buy_price']))
        buy_capacity = Decimal(str(data['buy_capacity']))
        costs = Decimal(str(data['costs_btc']))
        all_values = (requested, bonus, cash, buy_price, buy_capacity, costs)
        if any(not x.is_finite() or x < 0 for x in all_values) or buy_price <= 0 or requested <= 0:
            raise ValueError('Informe valores não negativos e preço de compra positivo.')
        btc_price = Decimal(str(position['btc_price']))
        collateral_price = btc_price * Decimal(str(collateral['btc_ratio']))
        debt_price = Decimal(str(debt['price']))
        if not collateral_price or not debt_price:
            raise ValueError('Preços dos ativos devem ser positivos.')
        debt_qty = Decimal(str(debt['quantity']))
        collateral_qty = Decimal(str(collateral['quantity']))
        total_debt = sum(Decimal(str(x['quantity'])) * Decimal(str(x['price'])) for x in position['debts'])
        protected_btc = sum(Decimal(str(x['quantity'])) * Decimal(str(x['btc_ratio'])) for x in position['collateral'])
        if hf is None or Decimal(hf) >= 1:
            return {'event': 'sem_liquidacao', 'health_factor': hf, 'protected_btc': str(protected_btc), 'remaining_btc': str(protected_btc), 'debt_usd': str(total_debt)}
        maximum = debt_qty
        if Decimal(hf) > Decimal('0.95') and collateral_qty * collateral_price >= 2000 and debt_qty * debt_price >= 2000:
            maximum = min(maximum, total_debt / 2 / debt_price)
        actual = min(requested, maximum, collateral_qty * collateral_price / ((1 + bonus / 100) * debt_price))
        taken = actual * debt_price * (1 + bonus / 100) / collateral_price
        remaining_debt = debt_qty - actual
        remaining_collateral = collateral_qty - taken
        if actual < debt_qty and taken < collateral_qty and (remaining_debt * debt_price < 1000 or remaining_collateral * collateral_price < 1000):
            raise ValueError('O cenário deixaria saldo residual abaixo do limite informado para Aave V3.3.')
        remainder_btc = protected_btc - taken * Decimal(str(collateral['btc_ratio']))
        cash_btc = min(cash / buy_price, buy_capacity)
        net_needed = max(Decimal(0), protected_btc - remainder_btc - cash_btc)
        position_after = json.loads(json.dumps(position))
        next(x for x in position_after['collateral'] if x['contract'].lower() == collateral['contract'].lower())['quantity'] = str(remaining_collateral)
        next(x for x in position_after['debts'] if x['contract'].lower() == debt['contract'].lower())['quantity'] = str(remaining_debt)
        result = calculate_scenario(position_after)
        return {'event': 'total' if total_debt - actual * debt_price == 0 else 'parcial', 'health_factor_before': hf,
                'health_factor_after': result['health_factor'], 'protected_btc': str(protected_btc),
                'remaining_btc': str(remainder_btc), 'collateral_taken': str(taken),
                'bonus_percent': str(bonus), 'debt_repaid': str(actual),
                'remaining_debt_units': str(remaining_debt), 'debt_usd': str(total_debt - actual * debt_price),
                'cash_btc': str(cash_btc), 'net_options_btc': str(net_needed),
                'gross_options_btc': str(net_needed + costs), 'assumed_buy_price': str(buy_price),
                'unspent_cash_usd': str(cash - cash_btc * buy_price)}
    except (KeyError, TypeError, InvalidOperation) as exc:
        raise ValueError('Dados de liquidação inválidos.') from exc


def recovery_events(identity, original, event=None):
    """Maintain an auditable sequence of observed balances and recovery actions."""
    with closing(sqlite3.connect(DB)) as con, con:
        con.execute('CREATE TABLE IF NOT EXISTS recovery_baselines (account TEXT, network TEXT, market TEXT, original TEXT NOT NULL, PRIMARY KEY(account,network,market))')
        con.execute('CREATE TABLE IF NOT EXISTS recovery_events (id INTEGER PRIMARY KEY AUTOINCREMENT, account TEXT NOT NULL, network TEXT NOT NULL, market TEXT NOT NULL, event_id TEXT NOT NULL, payload TEXT NOT NULL, UNIQUE(account, network, market, event_id))')
        if event is not None:
            try:
                event_id = str(event['event_id']).strip()
                kind = str(event['kind'])
                observed_at = str(event['observed_at']).strip()
                if not event_id or not observed_at or kind not in ('liquidacao', 'recompra', 'ajuste'):
                    raise ValueError('Informe identificador, data e tipo válido.')
                value = Decimal(str(event['value_btc']))
                debt = Decimal(str(event.get('debt_usd', '0')))
                if not value.is_finite() or not debt.is_finite() or debt < 0 or (value < 0 and kind != 'ajuste'):
                    raise ValueError('Valores do evento inválidos.')
                if kind == 'liquidacao':
                    if 'debt_usd' not in event:
                        raise ValueError('Informe a dívida remanescente.')
                    projected = Decimal(str(event['projected_btc']))
                    if not projected.is_finite() or projected < 0:
                        raise ValueError('Informe a garantia projetada.')
                payload = json.dumps(event, sort_keys=True)
                previous = con.execute('SELECT payload FROM recovery_events WHERE account=? AND network=? AND market=? AND event_id=?', (*identity, event_id)).fetchone()
                if previous and previous[0] != payload:
                    raise ValueError('Identificador já registrado com outro conteúdo.')
                if not previous:
                    con.execute('INSERT OR IGNORE INTO recovery_baselines VALUES (?,?,?,?)', (*identity, json.dumps(original)))
                    con.execute('INSERT INTO recovery_events (account,network,market,event_id,payload) VALUES (?,?,?,?,?)', (*identity, event_id, payload))
            except (KeyError, TypeError, InvalidOperation) as exc:
                raise ValueError('Dados de conciliação inválidos.') from exc
        rows = con.execute('SELECT payload FROM recovery_events WHERE account=? AND network=? AND market=? ORDER BY id', identity).fetchall()
        baseline = con.execute('SELECT original FROM recovery_baselines WHERE account=? AND network=? AND market=?', identity).fetchone()
        return [json.loads(row[0]) for row in rows], json.loads(baseline[0]) if baseline else original


def recovery(data=None, identity=None):
    if data is not None:
        identity = tuple(str(data[key]).strip() for key in ('account', 'network', 'market'))
    position = scenario(identity=identity)
    if not position or not position['original']:
        raise ValueError('Salve primeiro um cenário original para esta conta.')
    events, baseline = recovery_events(identity, position['original'], data)
    original = baseline['input']
    initial = sum(Decimal(str(item['quantity'])) * Decimal(str(item['btc_ratio'])) for item in original['collateral'])
    target = initial
    purchased = Decimal(0)
    observed = initial
    debt = None
    history = []
    for event in events:
        value = Decimal(str(event['value_btc']))
        if event['kind'] == 'ajuste':
            target += value
            observed += value
        elif event['kind'] == 'recompra':
            purchased += value
        else:
            observed = value
            debt = event['debt_usd']
        history.append({**event, 'target_btc': str(target), 'observed_btc': str(observed),
                        'purchased_btc': str(purchased), 'deficit_btc': str(max(Decimal(0), target - observed - purchased)),
                        'remaining_debt_usd': debt})
    return {'original': baseline, 'events': history, 'target_btc': str(target),
            'observed_btc': str(observed), 'purchased_btc': str(purchased),
            'deficit_btc': str(max(Decimal(0), target - observed - purchased)), 'remaining_debt_usd': debt}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/api/position':
            self.respond(200, json.dumps(load()).encode(), 'application/json')
        elif urlsplit(self.path).path == '/api/scenario':
            params = parse_qs(urlsplit(self.path).query)
            identity = tuple(params.get(key, [''])[0] for key in ('account', 'network', 'market')) if params else None
            self.respond(200, json.dumps(scenario(identity=identity)).encode(), 'application/json')
        elif urlsplit(self.path).path == '/api/recovery':
            params = parse_qs(urlsplit(self.path).query)
            try:
                identity = tuple(params[key][0] for key in ('account', 'network', 'market'))
                self.respond(200, json.dumps(recovery(identity=identity)).encode(), 'application/json')
            except (KeyError, ValueError) as exc:
                self.respond(400, json.dumps({'error': str(exc)}).encode(), 'application/json')
        elif self.path == '/api/funds':
            self.respond(200, json.dumps(funds()).encode(), 'application/json')
        elif self.path == '/':
            self.respond(200, Path(__file__).with_name('index.html').read_bytes(), 'text/html; charset=utf-8')
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path not in ('/api/position', '/api/scenario', '/api/funds', '/api/repay', '/api/liquidation', '/api/recovery'):
            self.send_error(404)
            return
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if size > 65536:
                raise ValueError('Pedido muito grande.')
            data = json.loads(self.rfile.read(size))
            if self.path == '/api/scenario':
                result = scenario(data, bool(data.get('snapshot')))
            elif self.path == '/api/funds':
                result = funds(data)
            elif self.path == '/api/repay':
                result = repay(data)
            elif self.path == '/api/liquidation':
                result = simulate_liquidation(data)
            elif self.path == '/api/recovery':
                result = recovery(data)
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
