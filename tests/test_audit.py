import json
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

import audit
import radar


class AuditTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.db=Path(self.tmp.name)/'audit.db';self.db.touch()
        candidate={'venue':'derive','buy':'C100','sell':'C110','direction':'alta','entry':'debito',
                   'timestamp':'1795320000000','expiry':1800000000000,'risk_estimate_usd':'20',
                   'reference_btc_usd':'100000','size':'1','entry_currency':'USDC','debit':'1',
                   'maximum_gain_usd':'30','factors':{'liquidity':90,'economics':70,'objective_fit':80}}
        wallet={'balances':[{'token':'USDC','location':'derive','total':'100','available':'100'}]}
        with closing(__import__('sqlite3').connect(self.db)) as con,con:
            con.execute('CREATE TABLE funds (id INTEGER PRIMARY KEY,payload TEXT NOT NULL)')
            con.execute('INSERT INTO funds VALUES(1,?)',(json.dumps(wallet),))
        self.evaluation=radar.evaluate(self.db,{'evaluation_id':'eval-1','objective':'protecao',
            'weights':{'liquidity':40,'economics':35,'objective_fit':25},'candidates':[candidate]},now_ms=1795320000100)
        self.candidate=self.evaluation['ranked'][0]['candidate']

    def test_ignored_expired_and_empty_period_are_auditable(self):
        event={'event_id':'ignore-1','evaluation_id':'eval-1','candidate':self.candidate,
               'status':'ignorada','note':'aguardar melhor preço'}
        audit.disposition(self.db,event,now_ms=1795320000200)
        audit.disposition(self.db,event,now_ms=1795320000300)
        radar.evaluate(self.db,{'evaluation_id':'empty-1','objective':'rendimento','candidates':[]},now_ms=1795320000400)
        history=audit.history(self.db,now_ms=1800000000001)
        self.assertEqual(history['opportunities'][0]['status'],'ignorada')
        self.assertEqual(len(history['empty_periods']),1)
        self.assertEqual(history['summary']['ignored'],1)
        with self.assertRaisesRegex(ValueError,'reutilizado'):
            audit.disposition(self.db,{**event,'status':'bloqueada'},now_ms=1795320000500)

    def test_external_flows_are_idempotent_and_separate(self):
        flow={'event_id':'interest-1','category':'juros_divida','currency':'USDC',
              'amount':'-12.5','observed_at':'2026-01-01T00:00:00Z','note':'juros Aave'}
        audit.cashflow(self.db,flow)
        audit.cashflow(self.db,flow)
        history=audit.history(self.db)
        self.assertEqual(len(history['cashflows']),1)
        self.assertEqual(history['summary']['realized_option_pnl_usd'],'0')


if __name__=='__main__':unittest.main()
