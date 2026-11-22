"""Discover and quote BTC vertical option spreads on supported venues."""
import time
from decimal import Decimal, InvalidOperation
from itertools import combinations

import deribit
import derive


def decimal(value):
    number = Decimal(str(value))
    if not number.is_finite():
        raise ValueError('Número inválido.')
    return number


def universe(venue, expiry, fetch_deribit=deribit.request, fetch_derive=derive.request):
    if venue == 'deribit':
        instruments = fetch_deribit('get_instruments', {'currency': 'BTC', 'kind': 'option', 'expired': 'false'})
        return [{'name': item['instrument_name'], 'strike': str(item['strike']), 'expiry': item['expiration_timestamp'],
                 'type': item['option_type'], 'minimum': str(item['min_trade_amount'])}
                for item in instruments if item.get('is_active') and item.get('settlement_currency') == 'BTC'
                and time.strftime('%Y-%m-%d', time.gmtime(item['expiration_timestamp'] / 1000)) == expiry]
    if venue == 'derive':
        result = []
        page = 1
        while True:
            data = fetch_derive('get_all_instruments', {'instrument_type': 'option', 'currency': 'BTC', 'expired': False, 'page': page, 'page_size': 1000})
            for item in data['instruments']:
                details = item.get('option_details') or {}
                if item.get('is_active') and time.strftime('%Y-%m-%d', time.gmtime(details['expiry'])) == expiry:
                    result.append({'name': item['instrument_name'], 'strike': details['strike'], 'expiry': details['expiry'] * 1000,
                                   'type': 'put' if details['option_type'] == 'P' else 'call', 'minimum': item['minimum_amount']})
            if page >= data['pagination']['num_pages']:
                return result
            page += 1
    raise ValueError('Exchange inválida.')


def structure(direction, entry):
    variants = {('alta', 'debito'): ('call', 'low'), ('alta', 'credito'): ('put', 'low'),
                ('baixa', 'debito'): ('put', 'high'), ('baixa', 'credito'): ('call', 'high')}
    try:
        return variants[(direction, entry)]
    except KeyError as exc:
        raise ValueError('Escolha direção e tipo de entrada válidos.') from exc


def discover(items, direction, entry, max_strikes=12):
    kind, buy = structure(direction, entry)
    selected = sorted((x for x in items if x['type'] == kind), key=lambda x: decimal(x['strike']))
    # Adjacent strikes keep discovery bounded; each proposed pair is recotado before use.
    return [{'buy': low['name'] if buy == 'low' else high['name'],
             'sell': high['name'] if buy == 'low' else low['name'],
             'expiry': low['expiry']} for low, high in zip(selected[:max_strikes], selected[1:max_strikes])]


def calculate(buy, sell, size, venue, buy_price, sell_price, index_price, fee):
    amount = decimal(size)
    buy_strike, sell_strike = decimal(buy['strike']), decimal(sell['strike'])
    buy_price, sell_price, index_price, fee = map(decimal, (buy_price, sell_price, index_price, fee))
    if amount <= 0 or buy_price <= 0 or sell_price <= 0 or index_price <= 0 or fee < 0:
        raise ValueError('Tamanho, preços e taxas devem ser válidos.')
    if buy['type'] != sell['type'] or buy['expiry'] != sell['expiry'] or buy_strike == sell_strike:
        raise ValueError('As pernas devem ter mesmo tipo e vencimento e strikes distintos.')
    debit = (buy_price - sell_price) * amount + fee
    debit_usd = debit * index_price if venue == 'deribit' else debit
    low, high = sorted((buy_strike, sell_strike))
    def payoff(strike_price):
        if buy['type'] == 'call':
            return (max(Decimal(0), strike_price-buy_strike)-max(Decimal(0), strike_price-sell_strike))*amount-debit_usd
        return (max(Decimal(0), buy_strike-strike_price)-max(Decimal(0), sell_strike-strike_price))*amount-debit_usd
    values = [payoff(Decimal(0)), payoff(low), payoff(high), payoff(high * 2)]
    before, after = payoff(low), payoff(high)
    breakeven = low + (high-low)*(-before)/(after-before) if before != after and min(before, after) <= 0 <= max(before, after) else None
    return {'buy': buy['name'], 'sell': sell['name'], 'size': str(amount), 'expiry': buy['expiry'],
            'type': buy['type'], 'buy_strike': str(buy_strike), 'sell_strike': str(sell_strike),
            'entry_currency': 'BTC' if venue == 'deribit' else 'USDC', 'debit': str(debit), 'fees': str(fee),
            'reference_btc_usd': str(index_price), 'breakeven_usd': str(breakeven) if breakeven is not None else None,
            'maximum_gain_usd': str(max(Decimal(0), *values)), 'maximum_loss_usd': str(min(Decimal(0), *values)),
            'scenario_usd': [{'btc_price': str(point), 'pnl': str(payoff(point))} for point in (low*Decimal('0.8'), (low+high)/2, high*Decimal('1.2'))],
            'margin': None, 'risk_estimate_usd': str(max(Decimal(0), -min(Decimal(0), *values))),
            'margin_note': 'Margem real da conta indisponível; risco máximo estimado da trava vertical, não é cálculo da exchange. Resultado em USD usa o prêmio BTC convertido pelo índice de entrada.' if venue == 'deribit' else 'Margem real da conta indisponível; risco máximo estimado da trava vertical, não é cálculo da exchange.'}


def snapshot(venue, name):
    if venue == 'deribit':
        item = deribit.request('get_instrument', {'instrument_name': name})
        book = deribit.request('get_order_book', {'instrument_name': name, 'depth': 20})
        if not item.get('is_active') or item.get('settlement_currency') != 'BTC':
            raise ValueError('Instrumento Deribit indisponível.')
        if time.time() * 1000 - book['timestamp'] > 30000:
            raise ValueError('Livro Deribit desatualizado.')
        return {'name': name, 'type': item['option_type'], 'strike': item['strike'], 'expiry': item['expiration_timestamp'],
                'minimum': item['min_trade_amount'], 'step': item['min_trade_amount'], 'maximum': None,
                'bids': book['bids'], 'asks': book['asks'], 'index': book['index_price'], 'timestamp': book['timestamp'],
                'rate': item['taker_commission'], 'base_fee': '0', 'fee_cap': '0.125'}
    if venue == 'derive':
        item = derive.request('get_instrument', {'instrument_name': name})
        ticker = derive.request('get_ticker', {'instrument_name': name})
        book = derive.orderbook(name)
        details = item.get('option_details') or {}
        if not item.get('is_active') or item.get('base_currency') != 'BTC':
            raise ValueError('Instrumento Derive indisponível.')
        if time.time() * 1000 - min(book['timestamp'], ticker['t']) > 30000:
            raise ValueError('Livro Derive desatualizado.')
        return {'name': name, 'type': 'call' if details['option_type'] == 'C' else 'put', 'strike': details['strike'],
                'expiry': details['expiry'] * 1000, 'minimum': item['minimum_amount'], 'step': item['amount_step'],
                'maximum': item['maximum_amount'], 'bids': book['bids'], 'asks': book['asks'], 'index': ticker['I'],
                'timestamp': book['timestamp'], 'rate': item['taker_fee_rate'], 'base_fee': item['base_fee'], 'fee_cap': item['mark_price_fee_rate_cap']}
    raise ValueError('Exchange inválida.')


def preview(venue, direction, entry, buy_name, sell_name, size, fetch_snapshot=snapshot):
    try:
        kind, buy_strike = structure(direction, entry)
        amount = decimal(size)
        buy = fetch_snapshot(venue, buy_name)
        sell = fetch_snapshot(venue, sell_name)
        if time.time() * 1000 - min(buy['timestamp'], sell['timestamp']) > 30000:
            raise ValueError('Um dos livros ficou desatualizado durante a consulta.')
        if buy['type'] != kind or sell['type'] != kind or buy['expiry'] != sell['expiry']:
            raise ValueError('As pernas devem ter mesmo tipo e vencimento.')
        if (decimal(buy['strike']) < decimal(sell['strike'])) != (buy_strike == 'low') or decimal(buy['strike']) == decimal(sell['strike']):
            raise ValueError('Os strikes não correspondem à direção escolhida.')
        for item in (buy, sell):
            if amount < decimal(item['minimum']) or amount % decimal(item['step']) or (item['maximum'] and amount > decimal(item['maximum'])):
                raise ValueError('Quantidade fora dos limites de lote de uma perna.')
        if not buy['asks'] or not sell['bids']:
            raise ValueError('Falta oferta em uma das pernas.')
        ask, ask_qty = map(decimal, buy['asks'][0])
        bid, bid_qty = map(decimal, sell['bids'][0])
        if min(ask_qty, bid_qty) < amount:
            raise ValueError('Profundidade insuficiente no melhor preço de uma perna.')
        index = decimal(buy['index'])
        if venue == 'deribit':
            fee = amount * (min(decimal(buy['rate']), ask * decimal(buy['fee_cap'])) + min(decimal(sell['rate']), bid * decimal(sell['fee_cap'])))
        else:
            fee = decimal(buy['base_fee']) + min(decimal(buy['rate']) * amount * index, ask * amount * decimal(buy['fee_cap']))
            fee += decimal(sell['base_fee']) + min(decimal(sell['rate']) * amount * index, bid * amount * decimal(sell['fee_cap']))
        result = calculate(buy, sell, amount, venue, ask, bid, index, fee)
        if (entry == 'credito' and decimal(result['debit']) >= 0) or (entry == 'debito' and decimal(result['debit']) <= 0):
            raise ValueError('O preço líquido não corresponde ao tipo de entrada.')
        result.update({'venue': venue, 'direction': direction, 'entry': entry,
                       'buy_price': str(ask), 'sell_price': str(bid), 'timestamp': min(buy['timestamp'], sell['timestamp'])})
        return result
    except (InvalidOperation, KeyError, TypeError, ZeroDivisionError) as exc:
        raise ValueError('Dados de mercado inválidos.') from exc


def scan(venue, expiry, direction, entry, size):
    items = universe(venue, expiry)
    index = deribit.request('get_index_price', {'index_name': 'btc_usd'})['index_price'] if venue == 'deribit' else derive.request('get_currency', {'currency': 'BTC'})['spot_price']
    nearest = sorted(items, key=lambda item: abs(decimal(item['strike']) - decimal(index)))[:20]
    candidates = discover(nearest, direction, entry, max_strikes=6)
    results = []
    excluded = []
    for candidate in candidates:
        try:
            results.append(preview(venue, direction, entry, candidate['buy'], candidate['sell'], size))
        except (ValueError, OSError, TimeoutError, derive.WebSocketException) as exc:
            excluded.append({'buy': candidate['buy'], 'sell': candidate['sell'], 'reason': str(exc)})
    return {'candidates': results, 'excluded': excluded, 'index': str(index)}


def close_quote(venue, buy_name, sell_name, size, fetch_snapshot=snapshot):
    """Quote an exit: sell the original long at bid and cover the short at ask."""
    amount = decimal(size)
    buy, sell = fetch_snapshot(venue, buy_name), fetch_snapshot(venue, sell_name)
    if time.time()*1000-min(buy['timestamp'],sell['timestamp']) > 30000:
        raise ValueError('Um dos livros ficou desatualizado durante a saída.')
    if buy['type'] != sell['type'] or buy['expiry'] != sell['expiry'] or not buy['bids'] or not sell['asks']:
        raise ValueError('Livros incompatíveis ou sem liquidez para encerrar.')
    if any(amount < decimal(x['minimum']) or amount % decimal(x['step']) or (x['maximum'] and amount > decimal(x['maximum'])) for x in (buy,sell)):
        raise ValueError('Quantidade fora dos limites de lote para encerrar.')
    bid,bid_qty=map(decimal,buy['bids'][0]); ask,ask_qty=map(decimal,sell['asks'][0])
    if min(bid_qty,ask_qty)<amount:
        raise ValueError('Profundidade insuficiente para encerrar as duas pernas.')
    index=decimal(buy['index'])
    if venue=='deribit':
        fee=amount*(min(decimal(buy['rate']),bid*decimal(buy['fee_cap']))+min(decimal(sell['rate']),ask*decimal(sell['fee_cap'])))
    elif venue=='derive':
        fee=decimal(buy['base_fee'])+min(decimal(buy['rate'])*amount*index,bid*amount*decimal(buy['fee_cap']))
        fee+=decimal(sell['base_fee'])+min(decimal(sell['rate'])*amount*index,ask*amount*decimal(sell['fee_cap']))
    else:
        raise ValueError('Exchange inválida.')
    cashflow=(ask-bid)*amount+fee
    return {'buy_to_close':sell_name,'sell_to_close':buy_name,'size':str(amount),'close_debit':str(cashflow),
            'sell_long_bid':str(bid),'buy_short_ask':str(ask),'fees':str(fee),'currency':'BTC' if venue=='deribit' else 'USDC',
            'reference_btc_usd':str(index),'timestamp':min(buy['timestamp'],sell['timestamp']),
            'timestamp_buy':sell['timestamp'],'timestamp_sell':buy['timestamp']}


def roll_quote(venue, old_name, new_name, side, size, fetch_snapshot=snapshot):
    """Buy back/sell the old leg and open its replacement at executable book sides."""
    if side not in ('buy','sell'):raise ValueError('Lado da perna inválido.')
    amount=decimal(size);old,new=fetch_snapshot(venue,old_name),fetch_snapshot(venue,new_name)
    if time.time()*1000-min(old['timestamp'],new['timestamp'])>30000:raise ValueError('Livro desatualizado; rolagem suspensa.')
    if old['type']!=new['type'] or old['expiry']!=new['expiry']:
        raise ValueError('Rolagem inicial exige tipo e vencimento iguais; calendários ficam para a etapa própria.')
    if old_name==new_name:raise ValueError('Instrumento substituto deve ser diferente da perna atual.')
    if any(amount<decimal(x['minimum']) or amount%decimal(x['step']) or (x['maximum'] and amount>decimal(x['maximum'])) for x in (old,new)):
        raise ValueError('Quantidade fora dos limites de lote da rolagem.')
    close_levels=old['asks'] if side=='sell' else old['bids']
    open_levels=new['bids'] if side=='sell' else new['asks']
    if not close_levels or not open_levels:raise ValueError('Falta oferta para uma das pernas da rolagem.')
    close_price,close_qty=map(decimal,close_levels[0]);open_price,open_qty=map(decimal,open_levels[0])
    if min(close_qty,open_qty)<amount:raise ValueError('Profundidade insuficiente para rolar a quantidade completa.')
    index=decimal(old['index'])
    if venue=='deribit':
        fees=amount*(min(decimal(old['rate']),close_price*decimal(old['fee_cap']))+min(decimal(new['rate']),open_price*decimal(new['fee_cap'])))
    elif venue=='derive':
        fees=decimal(old['base_fee'])+min(decimal(old['rate'])*amount*index,close_price*amount*decimal(old['fee_cap']))
        fees+=decimal(new['base_fee'])+min(decimal(new['rate'])*amount*index,open_price*amount*decimal(new['fee_cap']))
    else:raise ValueError('Exchange inválida.')
    if side=='sell':debit=(close_price-open_price)*amount+fees
    else:debit=(open_price-close_price)*amount+fees
    return {'old_instrument':old_name,'new_instrument':new_name,'side':side,'size':str(amount),
            'old_close_price':str(close_price),'replacement_price':str(open_price),'fees':str(fees),
            'net_debit':str(debit),'net_credit':str(-debit),'currency':'BTC' if venue=='deribit' else 'USDC',
            'new_strike':str(new['strike']),'new_expiry':new['expiry'],'type':new['type'],
            'reference_btc_usd':str(index),'timestamp':min(old['timestamp'],new['timestamp']),
            'old_timestamp':old['timestamp'],'replacement_timestamp':new['timestamp']}


def reference_index(venue):
    """Read BTC/USD trigger reference from the selected public venue."""
    if venue=='deribit':
        return decimal(deribit.request('get_index_price',{'index_name':'btc_usd'})['index_price'])
    if venue=='derive':
        return decimal(derive.request('get_currency',{'currency':'BTC'})['spot_price'])
    raise ValueError('Exchange inválida.')
