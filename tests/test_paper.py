import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app
import paper


def preview(venue, direction, entry, buy, sell, size):
    return {'venue':venue,'direction':direction,'entry':entry,'buy':buy,'sell':sell,
            'size':size,'entry_currency':'USDC','debit':'1.05','fees':'0.05',
            'risk_estimate_usd':'10','reference_btc_usd':'100000',
            'buy_price':'2','sell_price':'1','expiry':1800000000000}


class PaperTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / 'paper.db'
        self.db.touch()
        self.addCleanup(self.tmp.cleanup)
        with patch.object(app, 'DB', self.db):
            app.funds({'balances':[{'token':'USDC','location':'derive','total':'100'}], 'grid_btc':'0'})
        self.request = {'request_id':'one','venue':'derive','direction':'alta','entry':'debito',
                        'buy':'BTC-C100','sell':'BTC-C110','size':'1','token':'USDC',
                        'proposed_debit':'1','tolerance_percent':'10'}

    def test_requotes_reserves_once_and_is_idempotent(self):
        first = paper.open_spread(self.db, self.request, preview)
        second = paper.open_spread(self.db, self.request, lambda *args: self.fail('must not requote replay'))
        self.assertEqual(first, second)
        self.assertEqual(first['status'], 'aberta')
        self.assertEqual(first['opened_legs'][0]['average_price'], '2')
        self.assertEqual(first['fees'], '0.05')
        with patch.object(app, 'DB', self.db):
            balance = app.funds()['balances'][0]
        self.assertEqual(balance['available'], '98.95')
        self.assertEqual(balance['margem'], '1.05')

    def test_excess_slippage_expires_without_changing_wallet(self):
        request = {**self.request, 'proposed_debit':'0.5','tolerance_percent':'1'}
        result = paper.open_spread(self.db, request, preview)
        self.assertEqual(result['status'], 'expirada')
        self.assertEqual(result['wallet_before'], result['wallet_after'])
        with patch.object(app, 'DB', self.db):
            self.assertEqual(app.funds()['balances'][0]['available'], '100')
        self.assertEqual(paper.list_spreads(self.db)[0]['status'], 'expirada')

    def test_budget_and_request_id_conflicts(self):
        request = {**self.request, 'entry':'credito','proposed_debit':'-1'}
        def expensive_credit(*args):
            result = preview(*args)
            result.update(debit='-0.8', risk_estimate_usd='200')
            return result
        with self.assertRaisesRegex(ValueError, 'Orçamento insuficiente'):
            paper.open_spread(self.db, request, expensive_credit)
        paper.open_spread(self.db, self.request, preview)
        with self.assertRaisesRegex(ValueError, 'Identificador já usado'):
            paper.open_spread(self.db, {**self.request, 'size':'2'}, preview)


if __name__ == '__main__':
    unittest.main()
