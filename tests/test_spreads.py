import unittest
import time
from decimal import Decimal
import spreads


class SpreadTest(unittest.TestCase):
    def test_four_variants_on_both_venues(self):
        strikes = {'CLOW': ('call', '100'), 'CHIGH': ('call', '120'), 'PLOW': ('put', '100'), 'PHIGH': ('put', '120')}
        def snapshot(venue, name):
            kind, strike = strikes[name]
            # Calls and puts each have their usual monotonic price relationship.
            premium = {'CLOW':'15', 'CHIGH':'5', 'PLOW':'5', 'PHIGH':'15'}[name]
            scale = Decimal('100') if venue == 'deribit' else Decimal('1')
            return {'name':name, 'type':kind, 'strike':strike, 'expiry':1000, 'minimum':'1', 'step':'1', 'maximum':'10', 'asks':[[str((Decimal(premium)+1)/scale),'5']], 'bids':[[str(Decimal(premium)/scale),'5']], 'index':'100', 'timestamp':time.time()*1000, 'rate':'0', 'base_fee':'0', 'fee_cap':'0.125'}
        variants = [('alta','debito','CLOW','CHIGH'), ('alta','credito','PLOW','PHIGH'), ('baixa','debito','PHIGH','PLOW'), ('baixa','credito','CHIGH','CLOW')]
        for venue in ('deribit','derive'):
            for direction,entry,buy,sell in variants:
                with self.subTest(venue=venue, direction=direction, entry=entry):
                    result = spreads.preview(venue,direction,entry,buy,sell,'1',snapshot)
                    self.assertEqual(result['buy'],buy)
                    self.assertEqual(result['sell'],sell)
                    self.assertEqual(Decimal(result['maximum_gain_usd']) > 0, True)
                    self.assertEqual(len(result['scenario_usd']),3)

    def test_liquidity_and_incompatible_strikes_rejected(self):
        def snapshot(venue,name):
            return {'name':name,'type':'call','strike':'100' if name=='A' else '120','expiry':1000,'minimum':'1','step':'1','maximum':'10','asks':[['5','1']],'bids':[['2','1']],'index':'100','timestamp':time.time()*1000,'rate':'0','base_fee':'0','fee_cap':'0.125'}
        with self.assertRaisesRegex(ValueError, 'Profundidade insuficiente'):
            spreads.preview('derive','alta','debito','A','B','2',snapshot)
        with self.assertRaisesRegex(ValueError, 'strikes'):
            spreads.preview('derive','alta','debito','B','A','1',snapshot)

    def test_discovery_and_manual_preview_are_identical(self):
        instruments = [
            {'name': 'C100', 'strike': '100', 'expiry': 1000, 'type': 'call'},
            {'name': 'C110', 'strike': '110', 'expiry': 1000, 'type': 'call'},
            {'name': 'C120', 'strike': '120', 'expiry': 1000, 'type': 'call'},
        ]
        pairs = spreads.discover(instruments, 'alta', 'debito')
        self.assertEqual(pairs[0], {'buy': 'C100', 'sell': 'C110', 'expiry': 1000})
        def snapshot(venue, name):
            strike = name[1:]
            return {'name': name, 'type': 'call', 'strike': strike, 'expiry': 1000,
                    'minimum': '1', 'step': '1', 'maximum': '10', 'asks': [['5', '5']],
                    'bids': [['4', '5']], 'index': '105', 'timestamp': 1800000000000,
                    'rate': '0', 'base_fee': '0', 'fee_cap': '0.125'}
        suggested = spreads.preview('derive', 'alta', 'debito', pairs[0]['buy'], pairs[0]['sell'], '1', snapshot)
        manual = spreads.preview('derive', 'alta', 'debito', 'C100', 'C110', '1', snapshot)
        self.assertEqual(suggested, manual)
        self.assertEqual(suggested['maximum_gain_usd'], '9')
        self.assertEqual(suggested['maximum_loss_usd'], '-1')

    def test_close_quote_sells_long_and_covers_short_on_both_venues(self):
        def snapshot(venue,name):
            return {'name':name,'type':'call','strike':'100' if name=='LONG' else '110','expiry':1000,
                    'minimum':'1','step':'1','maximum':'10','bids':[['4','5']], 'asks':[['5','5']],
                    'index':'100','timestamp':1800000000000,'rate':'0','base_fee':'0','fee_cap':'0.125'}
        for venue in ('deribit','derive'):
            result=spreads.close_quote(venue,'LONG','SHORT','1',snapshot)
            self.assertEqual(result['sell_long_bid'],'4')
            self.assertEqual(result['buy_short_ask'],'5')
            self.assertEqual(result['close_debit'],'1')

    def test_roll_credit_145_less_120_and_eight_fees_is_17(self):
        def snapshot(venue,name):
            return {'name':name,'type':'put','strike':'100','expiry':1000,'minimum':'1','step':'1','maximum':'10',
                    'bids':[['145','10']] if name=='NEW' else [['130','10']],
                    'asks':[['120','10']] if name=='OLD' else [['155','10']],
                    'index':'100000','timestamp':1800000000000,'rate':'0','base_fee':'4','fee_cap':'0.125'}
        result=spreads.roll_quote('derive','OLD','NEW','sell','1',snapshot)
        self.assertEqual(result['old_close_price'],'120')
        self.assertEqual(result['replacement_price'],'145')
        self.assertEqual(result['fees'],'8')
        self.assertEqual(result['net_credit'],'17')
