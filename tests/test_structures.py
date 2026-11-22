import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
import json,sqlite3,time

import app
import structures


class StructureTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.db=Path(self.tmp.name)/'structures.db';self.db.touch()
        with patch.object(app,'DB',self.db):
            app.funds({'balances':[{'token':'USDC','location':'derive','total':'100'}],'grid_btc':'0'})

    def snapshot(self,venue,name):
        opts={'C100':('call','100','5','4'),'P100':('put','100','6','5'),
              'P90':('put','90','2','1'),'P95':('put','95','3','2'),'P105':('put','105','3','2'),
              'C95':('call','95','3','2'),'C105':('call','105','2','1'),'C110':('call','110','3','2')}
        kind,strike,ask,bid=opts[name]
        return {'name':name,'type':kind,'strike':strike,'expiry':1800000000000,'minimum':'0.1','step':'0.1','maximum':'100',
                'asks':[[ask,'10']],'bids':[[bid,'10']],'index':'100','timestamp':time.time()*1000,
                'rate':'0','base_fee':'0','fee_cap':'0.125'}

    def quote(self,family,legs,size='1'):
        return structures.preview({'venue':'derive','family':family,'size':size,'legs':legs},self.snapshot)

    def test_call_put_straddle_strangle_all_quote_and_mark(self):
        call=self.quote('long_call',[{'instrument':'C100','side':'buy'}])
        put=self.quote('long_put',[{'instrument':'P100','side':'buy'}])
        straddle=self.quote('straddle',[{'instrument':'C100','side':'buy'},{'instrument':'P100','side':'buy'}])
        strangle=self.quote('strangle',[{'instrument':'P90','side':'buy'},{'instrument':'C110','side':'buy'}])
        self.assertEqual(call['debit'],'5')
        self.assertIsNone(call['maximum_gain_usd'])
        self.assertEqual(put['debit'],'6')
        self.assertEqual(straddle['debit'],'11')
        self.assertEqual(straddle['unrealized_pnl_usd'],'-2')
        self.assertEqual(len(strangle['legs']),2)
        self.assertTrue(straddle['exit_available'])
        self.assertEqual({x['market_state'] for x in straddle['scenarios']},{'baixa','estabilidade','alta'})

    def test_rejects_wrong_straddle_and_unequal_expiry(self):
        with self.assertRaisesRegex(ValueError,'strikes iguais'):
            self.quote('straddle',[{'instrument':'P90','side':'buy'},{'instrument':'C110','side':'buy'}])
        with self.assertRaisesRegex(ValueError,'call e put'):
            self.quote('strangle',[{'instrument':'P90','side':'buy'},{'instrument':'P100','side':'buy'}])

    def test_open_close_and_expiry_settlement_are_idempotent(self):
        data={'request_id':'call-1','venue':'derive','family':'long_call','size':'1',
              'legs':[{'instrument':'C100','side':'buy'}],'proposed_debit':'5','tolerance_percent':'2'}
        opened=structures.open_paper(self.db,data,self.snapshot)
        self.assertEqual(opened['status'],'aberta')
        closed=structures.close_paper(self.db,'call-1','close-1',self.snapshot)
        replay=structures.close_paper(self.db,'call-1','different-event',lambda *args:self.fail('closed trade must replay'))
        self.assertEqual(closed,replay)
        self.assertEqual(closed['realized_pnl'],'-1')
        data={**data,'request_id':'call-2'}
        structures.open_paper(self.db,data,self.snapshot)
        settled=structures.settle_paper(self.db,'call-2','settle-1','120',now_ms=1900000000000)
        self.assertEqual(settled['realized_pnl'],'15')
        with patch.object(app,'DB',self.db):
            self.assertEqual(app.funds()['balances'][0]['total'],'114')

    def test_partial_two_leg_fill_is_reconciled_and_closed_per_leg(self):
        data={'request_id':'straddle-1','venue':'derive','family':'straddle','size':'1',
              'legs':[{'instrument':'C100','side':'buy'},{'instrument':'P100','side':'buy'}],
              'proposed_debit':'11','tolerance_percent':'2'}
        structures.open_paper(self.db,data,self.snapshot)
        structures.record_fill(self.db,{'request_id':'straddle-1','event_id':'f1','instrument':'C100',
             'observed_at':'2026-01-01T00:00Z','quantity':'0.5','average_price':'5','fee':'0'})
        detail=structures.record_fill(self.db,{'request_id':'straddle-1','event_id':'f2','instrument':'P100',
             'observed_at':'2026-01-01T00:00Z','quantity':'1','average_price':'6','fee':'0'})
        self.assertFalse(detail['reconciled'])
        closed=structures.close_paper(self.db,'straddle-1','partial-close',self.snapshot)
        self.assertEqual(closed['realized_pnl'],'-1.5')
        self.assertTrue(closed['settlement']['partial_exposure_closed'])

    def test_iron_condor_defined_credit_risk_and_partial_four_leg_close(self):
        def condor_snapshot(venue,name):
            result=self.snapshot(venue,name)
            prices={'P90':('1','0.5'),'P95':('3','2'),'C105':('3','2'),'C110':('1','0.5')}
            ask,bid=prices[name];result['asks']=[[ask,'10']];result['bids']=[[bid,'10']]
            return result
        legs=[{'instrument':'P90','side':'buy'},{'instrument':'P95','side':'sell'},
              {'instrument':'C105','side':'sell'},{'instrument':'C110','side':'buy'}]
        quote=structures.preview({'venue':'derive','family':'iron_condor','size':'1','legs':legs},condor_snapshot)
        self.assertEqual(quote['debit'],'-2')
        self.assertEqual(quote['maximum_gain_usd'],'2')
        self.assertEqual(quote['maximum_loss_usd'],'-3')
        self.assertEqual(quote['risk_estimate_usd'],'3')
        stable=next(x for x in quote['scenarios'] if x['btc_price_usd']=='100')
        outside=next(x for x in quote['scenarios'] if float(x['btc_price_usd'])<90)
        self.assertEqual(stable['pnl_at_expiry_usd'],'2')
        self.assertEqual(outside['pnl_at_expiry_usd'],'-3')
        data={'request_id':'condor-1','venue':'derive','family':'iron_condor','size':'1','legs':legs,
              'proposed_debit':'-2','tolerance_percent':'2'}
        opened=structures.open_paper(self.db,data,condor_snapshot)
        self.assertEqual(opened['reserved'],'3')
        for event,instrument,quantity,price in [('a','P90','0.5','1'),('b','P95','1','2'),
                                                ('c','C105','1','2'),('d','C110','0.5','1')]:
            structures.record_fill(self.db,{'request_id':'condor-1','event_id':event,'instrument':instrument,
                'observed_at':'2026-01-01T00:00:00Z','quantity':quantity,'average_price':price,'fee':'0'})
        status=next(x for x in structures.list_paper(self.db) if x['request_id']=='condor-1')
        self.assertFalse(status['reconciled']);self.assertEqual(status['unhedged_quantity'],'0.5')
        closed=structures.close_paper(self.db,'condor-1','condor-close',condor_snapshot)
        from decimal import Decimal
        self.assertEqual(Decimal(closed['realized_pnl']),Decimal('-2.5'))
        self.assertEqual(len(closed['settlement']['closed_legs']),4)

    def test_iron_condor_rejects_wrong_wing_order_and_expiry(self):
        legs=[{'instrument':'P90','side':'buy'},{'instrument':'P105','side':'sell'},
              {'instrument':'C95','side':'sell'},{'instrument':'C110','side':'buy'}]
        with self.assertRaisesRegex(ValueError,'ordenar asas'):
            self.quote('iron_condor',legs)


if __name__=='__main__':unittest.main()
