import unittest
from decimal import Decimal
import derive


class DeriveTest(unittest.TestCase):
    def test_quote_and_wbtc_conversion(self):
        option = {'is_active': True, 'risk_universe_id': 1, 'base_currency':'BTC', 'quote_currency':'USDC', 'minimum_amount':'0.01', 'maximum_amount':'100', 'amount_step':'0.01', 'base_fee':'0.5', 'taker_fee_rate':'0.0003', 'mark_price_fee_rate_cap':'0.125', 'option_details':{'option_type':'P','strike':'80000','expiry':1000}}
        spot = {'amount_step':'0.0001','minimum_amount':'0.001','base_fee':'0.01','taker_fee_rate':'0.0015'}
        def fetch(method, params):
            if method == 'get_risk_universes':
                return [{'risk_universe_id': 1, 'managers': [{'collaterals': [{'name': 'USDC'}]}]}]
            if method == 'get_ticker':
                return {'I':'60000','M':'10000','t':1000}
            return spot if params['instrument_name'] == 'WBTC-USDC' else option
        def book(name):
            if name == 'WBTC-USDC':
                return {'timestamp':1000,'asks':[['60000','1']]}
            return {'timestamp':1000,'bids':[['10000','0.1']]}
        result = derive.quote('BTC-P', '0.2', fetch, book, lambda: 1)
        self.assertEqual(Decimal(result['filled']), Decimal('0.1'))
        self.assertEqual(Decimal(result['unfilled']), Decimal('0.1'))
        self.assertEqual(Decimal(result['gross_usdc']), Decimal('1000'))
        self.assertEqual(Decimal(result['fee_usdc']), Decimal('2.3'))
        self.assertEqual(Decimal(result['conversion']['wbtc']), Decimal('0.0166'))

    def test_old_book_is_rejected(self):
        option = {'is_active':True,'risk_universe_id':1,'base_currency':'BTC','minimum_amount':'0.01','maximum_amount':'10','amount_step':'0.01','option_details':{'option_type':'P'}}
        def fetch(method, params):
            if method == 'get_risk_universes':
                return []
            return {'I':'100','M':'1','t':1000} if method == 'get_ticker' else option
        with self.assertRaisesRegex(ValueError, 'desatualizada'):
            derive.quote('P', '1', fetch, lambda name: {'timestamp':1000}, lambda: 60)
