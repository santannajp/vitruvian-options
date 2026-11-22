"""Read-only Derive V3 market data and approximate taker execution."""
import json
import time
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from urllib.request import Request, urlopen
from websockets.sync.client import connect
from websockets.exceptions import WebSocketException

BASE_URL = 'https://api.derive.xyz/v3/public/'


def request(method, params):
    body = json.dumps(params).encode()
    req = Request(BASE_URL + method, data=body, headers={'Content-Type': 'application/json', 'User-Agent': 'Mozilla/5.0'})
    with urlopen(req, timeout=8) as response:
        payload = json.load(response)
    if 'error' in payload:
        raise ValueError('Derive: ' + payload['error'].get('message', 'erro desconhecido'))
    return payload['result']


def orderbook(name):
    channel = f'orderbook.{name}.1.100'
    with connect('wss://api.derive.xyz/v3/ws', open_timeout=8, close_timeout=1, additional_headers={'User-Agent': 'Mozilla/5.0'}) as websocket:
        websocket.send(json.dumps({'id': 1, 'method': 'subscribe', 'params': {'channels': [channel]}}))
        for _ in range(10):
            message = json.loads(websocket.recv(timeout=8))
            if 'error' in message:
                raise ValueError('Falha ao assinar livro da Derive.')
            if message.get('id') == 1 and message.get('result', {}).get('status', {}).get(channel) != 'ok':
                raise ValueError('Derive recusou a assinatura do livro.')
            if message.get('method') == 'subscription' and message.get('params', {}).get('channel') == channel:
                return message['params']['data']
    raise ValueError('Derive não retornou livro de ofertas.')


def instruments(fetch=request):
    options = []
    page = 1
    while True:
        result = fetch('get_all_instruments', {'instrument_type': 'option', 'currency': 'BTC', 'expired': False, 'page': page, 'page_size': 1000})
        for item in result['instruments']:
            details = item.get('option_details') or {}
            if item.get('is_active') and details.get('option_type') == 'P':
                options.append({'name': item['instrument_name'], 'strike': details['strike'], 'expiry': details['expiry'] * 1000})
        if page >= result['pagination']['num_pages']:
            break
        page += 1
    return sorted(options, key=lambda item: (item['expiry'], Decimal(item['strike'])))


def quote(name, size, fetch=request, book_fetch=orderbook, now=time.time):
    try:
        amount = Decimal(str(size))
        if not amount.is_finite() or amount <= 0:
            raise ValueError('Informe uma quantidade positiva.')
        instrument = fetch('get_instrument', {'instrument_name': name})
        details = instrument.get('option_details') or {}
        if not instrument.get('is_active') or instrument.get('base_currency') != 'BTC' or details.get('option_type') != 'P':
            raise ValueError('Selecione uma put de BTC ativa.')
        minimum, maximum, step = (Decimal(instrument[key]) for key in ('minimum_amount', 'maximum_amount', 'amount_step'))
        if amount < minimum or amount > maximum or amount % step:
            raise ValueError('A quantidade deve respeitar mínimo, máximo e passo da Derive.')
        universes = fetch('get_risk_universes', {})
        universe = next((item for item in universes if item['risk_universe_id'] == instrument['risk_universe_id']), None)
        collateral = sorted({asset['name'] for manager in universe['managers'] for asset in manager['collaterals']}) if universe else []
        ticker = fetch('get_ticker', {'instrument_name': name})
        book = book_fetch(name)
        if now() * 1000 - book['timestamp'] > 30000 or now() * 1000 - ticker['t'] > 30000:
            raise ValueError('Cotação da Derive desatualizada.')
        remaining = amount
        gross = Decimal(0)
        for price, available in book['bids']:
            fill = min(remaining, Decimal(available))
            gross += fill * Decimal(price)
            remaining -= fill
            if not remaining:
                break
        filled = amount - remaining
        fee = Decimal(0)
        if filled:
            fee = Decimal(instrument['base_fee']) + min(Decimal(instrument['taker_fee_rate']) * filled * Decimal(ticker['I']), Decimal(instrument['mark_price_fee_rate_cap']) * gross)
        conversion = convert_to_wbtc(gross - fee, fetch, book_fetch, now) if gross > fee else None
        return {'instrument': name, 'strike': details['strike'], 'expiry': details['expiry'] * 1000,
                'minimum': str(minimum), 'step': str(step), 'quote_currency': instrument['quote_currency'],
                'index_price': ticker['I'], 'mark_price': ticker['M'], 'timestamp': book['timestamp'],
                'taker_rate': instrument['taker_fee_rate'], 'collateral': collateral, 'risk_universe_id': instrument['risk_universe_id'], 'filled': str(filled), 'unfilled': str(remaining),
                'gross_usdc': str(gross), 'fee_usdc': str(fee), 'net_usdc': str(gross - fee), 'conversion': conversion}
    except (InvalidOperation, KeyError, TypeError, WebSocketException) as exc:
        raise ValueError('Cotação ou resposta da Derive inválida.') from exc


def convert_to_wbtc(budget, fetch=request, book_fetch=orderbook, now=time.time):
    instrument = fetch('get_instrument', {'instrument_name': 'WBTC-USDC'})
    book = book_fetch('WBTC-USDC')
    if now() * 1000 - book['timestamp'] > 30000:
        raise ValueError('Livro WBTC/USDC desatualizado.')
    fee_rate = Decimal(instrument['taker_fee_rate'])
    base_fee = Decimal(instrument['base_fee'])
    available = max(Decimal(0), budget - base_fee)
    remaining_notional = available / (1 + fee_rate)
    quantity = Decimal(0)
    notional = Decimal(0)
    for price, depth in book['asks']:
        price, depth = Decimal(price), Decimal(depth)
        take = min(depth, remaining_notional / price)
        quantity += take
        notional += take * price
        remaining_notional -= take * price
        if remaining_notional <= 0:
            break
    step = Decimal(instrument['amount_step'])
    quantity = (quantity / step).to_integral_value(rounding=ROUND_DOWN) * step
    if quantity < Decimal(instrument['minimum_amount']):
        return {'wbtc': '0', 'unspent_usdc': str(budget), 'timestamp': book['timestamp']}
    left = quantity
    notional = Decimal(0)
    for price, depth in book['asks']:
        take = min(left, Decimal(depth))
        notional += take * Decimal(price)
        left -= take
        if not left:
            break
    spot_fee = base_fee + notional * fee_rate
    return {'wbtc': str(quantity), 'fee_usdc': str(spot_fee), 'unspent_usdc': str(budget - notional - spot_fee), 'timestamp': book['timestamp']}
