import unittest
from decimal import Decimal
import protection


class ProtectionTest(unittest.TestCase):
    def test_maximum_budget_and_partial_protection(self):
        data = {'protected_btc': '1', 'remaining_btc': '0.45', 'cash_btc': '0.05', 'budget_btc': '0.005', 'max_amount': '10', 'step': '0.1', 'scenario_price': '60000', 'days_remaining': '0', 'volatility_percent': '80', 'fee_btc_per_contract': '0', 'long_put': {'strike':'90000','ask_btc':'0.01','ask_depth':'10'}, 'short_put': {'strike':'70000','bid_btc':'0.005','bid_depth':'10'}}
        result = protection.compare(data)
        self.assertEqual(Decimal(result['target_btc']), Decimal('0.5'))
        put, spread = result['strategies']
        self.assertEqual(Decimal(put['amount']), Decimal('0.5'))
        self.assertEqual(Decimal(spread['amount']), Decimal('1'))
        self.assertIn('orçamento', put['constraints'])
        self.assertEqual(Decimal(put['projected_gross_btc']), Decimal('0.25'))
        self.assertEqual(Decimal(spread['projected_gross_btc']), Decimal('0.3333333333333333333333333333'))

    def test_recovered_btc_and_costs_are_counted_once(self):
        data = {'protected_btc': '1', 'remaining_btc': '0.45', 'cash_btc': '0.05', 'budget_btc': '1', 'max_amount': '1', 'step': '0.1', 'scenario_price': '60000', 'days_remaining': '0', 'volatility_percent': '80', 'fee_btc_per_contract': '0', 'long_put': {'strike':'88200', 'ask_btc':'0', 'ask_depth':'1'}, 'short_put': {'strike':'70000', 'bid_btc':'0', 'bid_depth':'1'}}
        result = protection.compare(data)['strategies'][0]
        self.assertEqual(Decimal(result['projected_net_btc']), Decimal('0.47'))
        self.assertEqual(Decimal(result['recovered_btc']), Decimal('0.97'))
        self.assertEqual(Decimal(result['deficit_btc']), Decimal('0.03'))

    def test_quotes_reject_stale_and_incompatible_options(self):
        def fetch(method, params):
            if method == 'get_instrument':
                return {'is_active': True, 'option_type':'put', 'settlement_currency':'BTC', 'expiration_timestamp': 10000, 'strike': 90000 if params['instrument_name']=='A' else 80000, 'min_trade_amount': '0.1', 'taker_commission': '0.0003'}
            return {'timestamp':1000, 'asks': [[0.1,1]], 'bids': [[0.05,1]]}
        result = protection.deribit_inputs('A', 'B', fetch, lambda:1)
        self.assertEqual(result['long_put']['ask_btc'], '0.1')
        with self.assertRaisesRegex(ValueError, 'desatualizado'):
            protection.deribit_inputs('A', 'B', fetch, lambda:60)

    def test_compare_protection_uses_one_aave_scenario(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        import app
        with tempfile.TemporaryDirectory() as directory, patch.object(app, 'DB', Path(directory) / 'test.db'):
            position = {'account': 'a', 'network': 'ethereum', 'market': 'aave', 'btc_price': '10000', 'observed_at': '2026-01-01T00:00Z', 'collateral': [{'token': 'WBTC', 'contract': '0x1', 'quantity': '1', 'btc_ratio': '1', 'threshold': '80'}], 'debts': [{'token': 'USDC', 'contract': '0x2', 'quantity': '9000', 'price': '1'}]}
            app.scenario(position, True)
            liquidation = {'account': 'a', 'network': 'ethereum', 'market': 'aave', 'collateral_contract': '0x1', 'debt_contract': '0x2', 'debt_to_cover': '5000', 'bonus_percent': '10', 'cash_usd': '500', 'buy_price': '10000', 'buy_capacity': '1', 'costs_btc': '0'}
            def fetch(method, params):
                if method == 'get_instrument':
                    return {'is_active': True, 'option_type': 'put', 'settlement_currency': 'BTC', 'expiration_timestamp': 9999999999999, 'strike': 15000 if params['instrument_name'] == 'A' else 12000, 'min_trade_amount': '0.1', 'taker_commission': '0.0003'}
                return {'timestamp': 2000000, 'asks': [['0.01', '10']], 'bids': [['0.005', '10']]}
            data = {'liquidation': liquidation, 'long_name': 'A', 'short_name': 'B', 'budget_btc': '1', 'max_amount': '1', 'scenario_price': '10000', 'days_remaining': '0', 'volatility_percent': '80'}
            with patch.object(app.deribit, 'request', fetch), patch.object(app.time, 'time', lambda: 2000):
                result = app.compare_protection(data)
            self.assertEqual(Decimal(result['without_hedge_btc']), Decimal('0.5'))
            self.assertEqual(Decimal(result['target_btc']), Decimal('0.5'))
            self.assertEqual(result['health_factor'], str(Decimal(8000) / Decimal(9000)))
            self.assertEqual(len(result['strategies']), 2)
            self.assertIsNotNone(result['strategies'][0]['current_close'])
