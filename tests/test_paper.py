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
            'buy_price':'2','sell_price':'1','expiry':1800000000000,'type':'call',
            'buy_strike':'100','sell_strike':'110'}


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

    def test_close_releases_reserve_and_records_realized_pnl_once(self):
        paper.open_spread(self.db, self.request, preview)
        calls=[]
        def close(venue, buy, sell, size):
            calls.append((venue,buy,sell,size))
            return {'close_debit':'-0.5','reference_btc_usd':'100000','currency':'USDC','fees':'0.1','timestamp':1800000000000}
        first=paper.close_spread(self.db,'one','close-1',close)
        second=paper.close_spread(self.db,'one','close-2',lambda *args: self.fail('must not close twice'))
        self.assertEqual(first,second)
        self.assertEqual(first['realized_pnl'],'-0.55')
        self.assertEqual(first['status'],'encerrada')
        self.assertEqual(len(calls),1)
        with patch.object(app, 'DB', self.db):
            balance=app.funds()['balances'][0]
        self.assertEqual(balance['margem'],'0.00')
        self.assertEqual(balance['total'],'99.45')
        self.assertEqual(balance['available'],'99.45')

    def test_monitor_suspends_only_position_with_stale_market(self):
        paper.open_spread(self.db, self.request, preview)
        positions=paper.monitor(self.db, lambda *args: (_ for _ in ()).throw(TimeoutError('feed antigo')))
        self.assertEqual(positions[0]['market_status'],'indisponivel')
        self.assertIn('feed antigo',positions[0]['market_error'])

    def test_settlement_after_expiry_uses_intrinsic_model_and_releases_reserve(self):
        paper.open_spread(self.db, self.request, preview)
        with self.assertRaisesRegex(ValueError, 'ainda não ocorreu'):
            paper.close_spread(self.db,'one','expiry-early',settlement={'btc_price':'105'},now_ms=1700000000000)
        settled=paper.close_spread(self.db,'one','expiry-1',settlement={'btc_price':'105','fee':'0.1'},now_ms=1900000000000)
        self.assertEqual(settled['close_mode'],'vencimento')
        self.assertEqual(settled['exit_quote']['intrinsic_usd'],'5')
        self.assertEqual(settled['realized_pnl'],'3.85')

    def test_roll_rules_block_credit_20_allow_17_and_replay_once(self):
        paper.open_spread(self.db,self.request,preview)
        rule={'request_id':'one','side':'sell','trigger':'days_lte','threshold':'5',
              'minimum_credit':'20','max_rolls':1,'max_capital_usd':'1000','max_cumulative_loss_usd':'50'}
        paper.save_roll_rule(self.db,rule)
        data={'request_id':'one','new_instrument':'BTC-C120','reference_price':'105','days_remaining':'4'}
        def roll_quote(venue,old,new,side,size):
            return {'old_instrument':old,'new_instrument':new,'side':side,'size':size,
                    'old_close_price':'120','replacement_price':'145','fees':'8','net_debit':'-17',
                    'net_credit':'17','currency':'USDC','reference_btc_usd':'100000','timestamp':1800000000000,
                    'new_strike':'120','new_expiry':1800000000000,'type':'call'}
        blocked=paper.preview_roll(self.db,data,roll_quote)
        self.assertFalse(blocked['eligible'])
        self.assertIn('abaixo do mínimo',blocked['reasons'][0])
        rule['minimum_credit']='17';paper.save_roll_rule(self.db,rule)
        allowed=paper.preview_roll(self.db,data,roll_quote)
        self.assertTrue(allowed['eligible'])
        first=paper.execute_roll(self.db,{**data,'event_id':'roll-1'},roll_quote)
        second=paper.execute_roll(self.db,{**data,'event_id':'roll-1'},lambda *args:self.fail('replay must not reroll'))
        self.assertEqual(first,second)
        self.assertEqual(first['status'],'executada')
        self.assertEqual(first['net_credit'],'17')
        self.assertEqual(first['position']['quote']['sell'],'BTC-C120')
        self.assertEqual(first['position']['roll_count'],1)
        self.assertEqual(paper.list_spreads(self.db)[0]['last_roll']['quote']['net_credit'],'17')

    def test_roll_blocks_partially_filled_exposure(self):
        paper.open_spread(self.db,self.request,preview)
        paper.save_roll_rule(self.db,{'request_id':'one','side':'sell','trigger':'days_lte','threshold':'5',
            'minimum_credit':'0','max_rolls':1,'max_capital_usd':'1000','max_cumulative_loss_usd':'50'})
        paper.record_fill(self.db,{'strategy_id':'one','event_id':'partial','instrument':'BTC-C100',
            'observed_at':'2026-01-01T00:00:00Z','quantity':'0.5','average_price':'2','fee':'0'})
        with self.assertRaisesRegex(ValueError,'preenchimento parcial'):
            paper.preview_roll(self.db,{'request_id':'one','new_instrument':'BTC-C120','reference_price':'100',
                'days_remaining':'1'},lambda *args:self.fail('must block before fetching roll book'))


if __name__ == '__main__':
    unittest.main()
