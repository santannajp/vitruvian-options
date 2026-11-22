import unittest
from decimal import Decimal
import deribit


class DeribitTest(unittest.TestCase):
    def test_quote_consumes_bids_and_limits_fill(self):
        instrument = {'instrument_name': 'BTC-P', 'option_type': 'put', 'settlement_currency': 'BTC', 'is_active': True, 'min_trade_amount': 0.1, 'taker_commission': 0.0003, 'strike': 80000, 'expiration_timestamp': 1000, 'contract_size': 1}
        book = {'bids': [[0.02, 0.1], [0.01, 0.1]], 'index_price': 70000, 'mark_price': 0.02, 'timestamp': 900}
        def fetch(method, params):
            return instrument if method == 'get_instrument' else book
        result = deribit.quote('BTC-P', '0.3', '60000', fetch, now=lambda: 0.9)
        self.assertEqual(Decimal(result['gross_btc']), Decimal('0.003'))
        self.assertEqual(Decimal(result['filled']), Decimal('0.2'))
        self.assertEqual(Decimal(result['unfilled']), Decimal('0.1'))
        self.assertEqual(Decimal(result['estimated_fee_btc']), Decimal('0.00006'))
        self.assertEqual(Decimal(result['expiry_gross_btc']), Decimal('0.1'))

    def test_instrument_filter(self):
        items = [{'instrument_name':'P','option_type':'put','settlement_currency':'BTC','is_active':True,'strike':50000,'expiration_timestamp':1000}, {'instrument_name':'C','option_type':'call','settlement_currency':'BTC','is_active':True,'strike':50000,'expiration_timestamp':1000}]
        self.assertEqual([item['name'] for item in deribit.instruments(lambda *args: items)], ['P'])
