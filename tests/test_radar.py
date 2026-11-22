import json
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

import radar


class RadarTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.db=Path(self.tmp.name)/'radar.db';self.db.touch()
        payload={'balances':[{'token':'BTC','location':'deribit','total':'0.01','available':'0.01'},
                             {'token':'USDC','location':'derive','total':'100','available':'100'}]}
        with closing(__import__('sqlite3').connect(self.db)) as con, con:
            con.execute('CREATE TABLE funds (id INTEGER PRIMARY KEY,payload TEXT NOT NULL)')
            con.execute('INSERT INTO funds VALUES(1,?)',(json.dumps(payload),))

    def test_weighted_score_reproduces_80_5_and_persists_calibration(self):
        candidate={'venue':'derive','buy':'C100','sell':'C110','timestamp':'1795320000000',
                   'risk_estimate_usd':'20','reference_btc_usd':'100000','size':'1','executable_size':'1',
                   'entry_currency':'USDC','maximum_gain_usd':'30',
                   'factors':{'liquidity':90,'economics':70,'objective_fit':80}}
        result=radar.evaluate(self.db,{'evaluation_id':'e1','objective':'protecao','weights':{'liquidity':40,'economics':35,'objective_fit':25},
                                       'candidates':[candidate]},now_ms=1795320000100)
        self.assertEqual(result['ranked'][0]['score'],'80.5')
        self.assertEqual(result['version'],'experimental-v1')
        self.assertEqual(result['calibration'],'experimental')
        self.assertEqual(radar.history(self.db)[0]['evaluation_id'],'e1')
        replay=radar.evaluate(self.db,{'evaluation_id':'e1','objective':'protecao','weights':{'liquidity':40,'economics':35,'objective_fit':25},'candidates':[candidate]},now_ms=1795320000200)
        self.assertEqual(replay['objective'],'protecao')
        with self.assertRaisesRegex(ValueError,'reutilizado'):
            radar.evaluate(self.db,{'evaluation_id':'e1','objective':'aposta','candidates':[]},now_ms=1795320000200)

    def test_explains_stale_quotes_and_budget_limit(self):
        candidate={'venue':'derive','buy':'P90','sell':'P80','timestamp':'1000','risk_estimate_usd':'101',
                   'size':'1','entry_currency':'USDC','maximum_gain_usd':'5'}
        result=radar.evaluate(self.db,{'evaluation_id':'e2','objective':'aposta','max_risk_usd':'100',
                                       'candidates':[candidate]},now_ms=100000)
        self.assertEqual(result['ranked'],[])
        self.assertIn('Cotação fora da janela',result['excluded'][0]['reasons'][0])
        self.assertIn('excede o limite',result['excluded'][0]['reasons'][1])
        self.assertIn('insuficiente',result['excluded'][0]['reasons'][2])
        self.assertIn('Nenhuma candidata',result['empty_reason'])

    def test_weights_must_sum_to_one_hundred(self):
        with self.assertRaisesRegex(ValueError,'somar exatamente'):
            radar.evaluate(self.db,{'objective':'rendimento','weights':{'liquidity':40,'economics':30,'objective_fit':20},'candidates':[]})


if __name__=='__main__':unittest.main()
