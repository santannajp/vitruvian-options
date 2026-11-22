"""Scenario estimates for a purchased put or a debit put spread.

Quotes and fees are per BTC of option exposure. Scenario values are calculated
in BTC, with USD option value converted at the scenario BTC price.
"""
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_DOWN
from math import erf, log, sqrt


def decimal(value):
    number = Decimal(str(value))
    if not number.is_finite():
        raise ValueError('Valores devem ser finitos.')
    return number


def put_value(spot, strike, years, volatility):
    if years == 0:
        return max(strike - spot, 0.0)
    if volatility <= 0:
        return max(strike - spot, 0.0)
    d1 = (log(spot / strike) + volatility * volatility * years / 2) / (volatility * sqrt(years))
    d2 = d1 - volatility * sqrt(years)
    cdf = lambda x: (1 + erf(x / sqrt(2))) / 2
    return strike * cdf(-d2) - spot * cdf(-d1)


def compare(data):
    try:
        before = decimal(data['protected_btc'])
        remaining = decimal(data['remaining_btc'])
        cash = decimal(data['cash_btc'])
        budget = decimal(data['budget_btc'])
        maximum = decimal(data['max_amount'])
        step = decimal(data['step'])
        spot = decimal(data['scenario_price'])
        years = decimal(data['days_remaining']) / Decimal(365)
        vol = decimal(data['volatility_percent']) / Decimal(100)
        fee = decimal(data['fee_btc_per_contract'])
        extra_cost = decimal(data.get('extra_cost_btc', '0'))
        long = data['long_put']
        short = data['short_put']
        strike_long = decimal(long['strike'])
        strike_short = decimal(short['strike'])
        values = [before, remaining, cash, budget, maximum, step, spot, years, vol, fee, extra_cost, strike_long, strike_short]
        if any(x < 0 for x in values) or not step or not spot or not strike_long or not strike_short or strike_short >= strike_long:
            raise ValueError('Informe valores válidos e strike comprado maior que o vendido.')
        if remaining > before:
            raise ValueError('O BTC conservado não pode exceder a referência.')
        target = max(Decimal(0), before - remaining - cash + extra_cost)
        strategies = []
        for name, legs in (('put', [long]), ('trava', [long, short])):
            open_cost = decimal(long['ask_btc']) - (decimal(short['bid_btc']) if len(legs) > 1 else 0) + fee * len(legs)
            capacity = min(decimal(long['ask_depth']), decimal(short['bid_depth']) if len(legs) > 1 else maximum, maximum)
            if open_cost < 0 or capacity < 0:
                raise ValueError('Preços e profundidades devem ser não negativos e o débito não pode ser negativo.')
            affordable = budget / open_cost if open_cost else maximum
            long_value = Decimal(str(put_value(float(spot), float(strike_long), float(years), float(vol)))) / spot
            short_value = Decimal(str(put_value(float(spot), float(strike_short), float(years), float(vol)))) / spot if len(legs) > 1 else Decimal(0)
            projected_per_contract = long_value - short_value - open_cost - fee * len(legs)
            needed = (target / projected_per_contract / step).to_integral_value(rounding=ROUND_CEILING) * step if projected_per_contract > 0 else Decimal(0)
            limit = (min(capacity, affordable, maximum) / step).to_integral_value(rounding=ROUND_DOWN) * step
            amount = min(needed, limit)
            projected_gross = amount * (long_value - short_value)
            premium = amount * open_cost
            projected_net = projected_gross - premium - amount * fee * len(legs)
            deficit = max(Decimal(0), target - projected_net)
            reasons = []
            if projected_per_contract <= 0:
                reasons.append('cenário não gera proteção líquida')
            if amount < needed:
                if affordable <= capacity and affordable <= maximum:
                    reasons.append('orçamento')
                if capacity <= affordable and capacity <= maximum:
                    reasons.append('profundidade')
                if maximum <= affordable and maximum <= capacity:
                    reasons.append('limite de contratos')
            if amount == 0 and target > 0:
                reasons.append('lote mínimo ou ausência de orçamento')
            strategies.append({'name': name, 'amount': str(amount), 'premium_btc': str(premium), 'projected_gross_btc': str(projected_gross), 'projected_net_btc': str(projected_net), 'recovered_btc': str(remaining + cash + projected_net - extra_cost), 'deficit_btc': str(deficit), 'constraints': reasons})
        return {'target_btc': str(target), 'without_hedge_btc': str(remaining + cash), 'strategies': strategies}
    except (InvalidOperation, KeyError, TypeError, OverflowError, ZeroDivisionError) as exc:
        raise ValueError('Dados da comparação inválidos.') from exc


def deribit_inputs(long_name, short_name, fetch, now):
    """Read executable top-of-book entry prices for a compatible BTC put spread."""
    instruments = []
    books = []
    for name in (long_name, short_name):
        instrument = fetch('get_instrument', {'instrument_name': name})
        if not instrument.get('is_active') or instrument.get('option_type') != 'put' or instrument.get('settlement_currency') != 'BTC':
            raise ValueError('Selecione puts inversas de BTC ativas.')
        book = fetch('get_order_book', {'instrument_name': name, 'depth': 100})
        if now() * 1000 - book['timestamp'] > 30000:
            raise ValueError('Livro da Deribit desatualizado.')
        instruments.append(instrument)
        books.append(book)
    if instruments[0]['expiration_timestamp'] != instruments[1]['expiration_timestamp']:
        raise ValueError('As puts devem ter o mesmo vencimento.')
    if Decimal(str(instruments[0]['strike'])) <= Decimal(str(instruments[1]['strike'])):
        raise ValueError('O strike comprado deve ser maior que o vendido.')
    if not books[0]['asks'] or not books[1]['bids']:
        raise ValueError('Faltam ofertas para montar as pernas.')
    buy = books[0]['asks'][0]
    sell = books[1]['bids'][0]
    return {'long_put': {'strike': str(instruments[0]['strike']), 'ask_btc': str(buy[0]), 'ask_depth': str(buy[1])},
            'short_put': {'strike': str(instruments[1]['strike']), 'bid_btc': str(sell[0]), 'bid_depth': str(sell[1])},
            'long_name': long_name, 'short_name': short_name,
            'expiration': instruments[0]['expiration_timestamp'],
            'fee_btc_per_contract': str(max(decimal(item['taker_commission']) for item in instruments)),
            'long_close': books[0]['bids'][0] if books[0]['bids'] else None,
            'short_close': books[1]['asks'][0] if books[1]['asks'] else None,
            'step': str(max(decimal(instruments[0]['min_trade_amount']), decimal(instruments[1]['min_trade_amount']))),
            'timestamp': min(books[0]['timestamp'], books[1]['timestamp'])}
