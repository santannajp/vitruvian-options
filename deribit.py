"""Public, read-only Deribit inverse BTC option quotes."""
import json
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode
from urllib.request import urlopen

BASE_URL = 'https://www.deribit.com/api/v2/public/'


def request(method, params):
    with urlopen(BASE_URL + method + '?' + urlencode(params), timeout=8) as response:
        payload = json.load(response, parse_float=Decimal)
    if 'error' in payload:
        raise ValueError('Deribit: ' + payload['error'].get('message', 'erro desconhecido'))
    return payload['result']


def instruments(fetch=request):
    items = fetch('get_instruments', {'currency': 'BTC', 'kind': 'option', 'expired': 'false'})
    return sorted(({'name': x['instrument_name'], 'strike': str(x['strike']),
                    'expiry': x['expiration_timestamp']} for x in items
                   if x.get('option_type') == 'put' and x.get('settlement_currency') == 'BTC'
                   and x.get('is_active')), key=lambda x: (x['expiry'], Decimal(x['strike'])))


def quote(name, size, settlement_price, fetch=request):
    try:
        amount = Decimal(str(size))
        expiry_price = Decimal(str(settlement_price))
        if not amount.is_finite() or amount <= 0 or not expiry_price.is_finite() or expiry_price <= 0:
            raise ValueError('Informe quantidade e preço de vencimento positivos.')
        instrument = fetch('get_instrument', {'instrument_name': name})
        if instrument.get('option_type') != 'put' or instrument.get('settlement_currency') != 'BTC' or not instrument.get('is_active'):
            raise ValueError('Selecione uma put inversa de BTC ativa.')
        minimum = Decimal(str(instrument['min_trade_amount']))
        if amount < minimum or amount % minimum:
            raise ValueError('A quantidade deve respeitar o lote mínimo da Deribit.')
        book = fetch('get_order_book', {'instrument_name': name, 'depth': 100})
        remaining = amount
        gross = Decimal(0)
        fee = Decimal(0)
        rate = Decimal(str(instrument['taker_commission']))
        for price, available in book['bids']:
            price, available = Decimal(str(price)), Decimal(str(available))
            fill = min(remaining, available)
            gross += fill * price
            fee += fill * min(rate, price * Decimal('0.125'))
            remaining -= fill
            if remaining == 0:
                break
        strike = Decimal(str(instrument['strike']))
        payoff = amount * max(strike - expiry_price, Decimal(0)) / expiry_price
        return {'instrument': name, 'strike': str(strike), 'expiry': instrument['expiration_timestamp'],
                'min_amount': str(minimum), 'contract_size': str(instrument['contract_size']),
                'settlement_currency': instrument['settlement_currency'], 'index_price': str(book['index_price']),
                'mark_price': str(book['mark_price']), 'timestamp': book['timestamp'], 'taker_rate': str(rate),
                'filled': str(amount - remaining), 'unfilled': str(remaining), 'gross_btc': str(gross),
                'estimated_fee_btc': str(fee), 'net_btc': str(gross - fee), 'expiry_gross_btc': str(payoff),
                'expiry_price': str(expiry_price)}
    except (InvalidOperation, KeyError, TypeError) as exc:
        raise ValueError('Cotação ou resposta da Deribit inválida.') from exc
