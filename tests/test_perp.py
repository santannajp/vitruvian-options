import tempfile
import unittest
from pathlib import Path

import perp


class PerpHedgeTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.db=Path(self.tmp.name)/'perp.db';self.db.touch()
        self.position={'position_id':'p1','venue':'derive','subaccount':'account-1','side':'long',
                       'quantity':'10','multiplier_btc':'0.01','entry_price':'100000',
                       'liquidation_price':'90000','horizon_days':'10','funding_rate_percent_per_8h':'0.01'}
        perp.save_position(self.db,self.position)

    def universe(self,venue,expiry):
        return [{'name':'P99000','type':'put','strike':'99000','expiry':1810000000000},
                {'name':'P100000','type':'put','strike':'100000','expiry':1810000000000},
                {'name':'C101000','type':'call','strike':'101000','expiry':1810000000000},
                {'name':'C100000','type':'call','strike':'100000','expiry':1810000000000}]

    def snapshot(self,venue,name):
        return {'name':name,'type':'put' if name.startswith('P') else 'call',
                'strike':name[1:],'expiry':1810000000000,'minimum':'0.01','step':'0.01','maximum':'100',
                'bids':[['400','10']],'asks':[['500','10']],'index':'100000',
                'timestamp':1800000000000,'rate':'0','base_fee':'0','fee_cap':'0.125'}

    def run_hedge(self,position_id='p1',percent='75',budget='1000',event='event-1'):
        return perp.hedge(self.db,{'position_id':position_id,'hedge_percent':percent,'budget_usd':budget,'event_id':event},
                          now_ms=1800000000000,universe_fetch=self.universe,snapshot_fetch=self.snapshot,index_fetch=lambda venue:100000)

    def test_long_put_nearest_eligible_strike_and_coverage(self):
        result=self.run_hedge()
        self.assertEqual(result['option'],'P100000')
        self.assertEqual(result['option_type'],'put')
        self.assertEqual(result['requested_coverage_btc'],'0.075')
        self.assertEqual(result['covered_btc'],'0.07')
        self.assertEqual(result['residual_exposure_btc'],'0.03')
        self.assertEqual(len(result['scenarios']),4)
        liq=next(x for x in result['scenarios'] if x['at_liquidation_price'])
        self.assertGreater(Decimal(liq['pnl_with_option_usd']),Decimal(liq['pnl_without_option_usd']))

    def test_short_position_uses_call_and_size_change_recalculates(self):
        changed={**self.position,'side':'short','quantity':'20','liquidation_price':'110000','position_id':'p2'}
        perp.save_position(self.db,changed)
        result=self.run_hedge('p2','50','1000','event-2')
        self.assertEqual(result['option'],'C100000')
        self.assertEqual(result['option_type'],'call')
        self.assertEqual(Decimal(result['requested_coverage_btc']),Decimal('0.1'))
        self.assertEqual(Decimal(result['covered_btc']),Decimal('0.1'))

    def test_budget_limits_coverage_and_repeated_event_is_idempotent(self):
        first=self.run_hedge('p1','100','5','event-budget')
        self.assertEqual(first['covered_btc'],'0.01')
        second=self.run_hedge('p1','100','5','event-budget')
        self.assertEqual(first,second)
        self.assertEqual(len(perp.hedge_history(self.db)),1)

    def test_delta_and_percentage_distance_modes_explain_selection(self):
        delta=perp.hedge(self.db,{'position_id':'p1','hedge_percent':'100','budget_usd':'1000',
            'event_id':'delta','selection_mode':'delta','target_delta_abs':'0.25','volatility_percent':'60',
            'size_tolerance_percent':'5','renewal_before_days':'7'},now_ms=1800000000000,
            universe_fetch=self.universe,snapshot_fetch=self.snapshot,index_fetch=lambda venue:100000)
        distance=perp.hedge(self.db,{'position_id':'p1','hedge_percent':'100','budget_usd':'1000',
            'event_id':'distance','selection_mode':'distance','target_distance_percent':'1',
            'volatility_percent':'60','size_tolerance_percent':'5','renewal_before_days':'7'},
            now_ms=1800000000000,universe_fetch=self.universe,snapshot_fetch=self.snapshot,index_fetch=lambda venue:100000)
        self.assertIn('delta absoluto mais próximo',delta['selection_explanation'])
        self.assertIn('distância percentual',distance['selection_explanation'])
        self.assertTrue(0<=float(delta['absolute_delta'])<=1)
        self.assertEqual(distance['option'],'P99000')

    def test_size_change_creates_one_idempotent_renewal(self):
        first=self.run_hedge('p1','50','1000','first-renewal')
        updated={**self.position,'quantity':'20'}
        perp.save_position(self.db,updated)
        second=self.run_hedge('p1','50','1000','second-renewal')
        self.assertEqual(second['renewal_action'],'renovar')
        self.assertTrue(any('Exposição mudou' in reason for reason in second['renewal_reasons']))
        self.assertEqual(second['previous_hedge_event_id'],'first-renewal')
        self.assertEqual(len(perp.hedge_history(self.db)),2)

    def test_invalid_liquidation_direction_rejected(self):
        with self.assertRaisesRegex(ValueError,'abaixo da entrada'):
            perp.save_position(self.db,{**self.position,'liquidation_price':'101000'})


from decimal import Decimal
if __name__=='__main__':unittest.main()
