import tempfile
import unittest
from contextlib import closing
from pathlib import Path

import paper


class ReconciliationTest(unittest.TestCase):
    def test_partial_fills_replay_out_of_order_and_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            db=Path(directory)/'paper.db'
            db.touch()
            # This record matches the durable position payload written by paper.open_spread.
            import sqlite3, json
            payload={'status':'aberta','request_id':'trade-1','quote':{'buy':'BTC-C100','sell':'BTC-C110','size':'2','buy_price':'10','sell_price':'4'},'fees':'0.2'}
            with closing(sqlite3.connect(db)) as con, con:
                con.execute('CREATE TABLE paper_spreads (id INTEGER PRIMARY KEY AUTOINCREMENT, request_id TEXT UNIQUE NOT NULL, request TEXT NOT NULL, status TEXT NOT NULL, payload TEXT NOT NULL)')
                con.execute('INSERT INTO paper_spreads(request_id,request,status,payload) VALUES(?,?,?,?)',('trade-1','{}','aberta',json.dumps(payload)))
            common={'strategy_id':'trade-1','instrument':'BTC-C100','quantity':'1','average_price':'11','fee':'0.1'}
            first=paper.record_fill(db,{**common,'event_id':'event-2','observed_at':'2026-01-02T00:00:00Z'})
            self.assertFalse(first['reconciled'])
            second=paper.record_fill(db,{**common,'instrument':'BTC-C110','quantity':'1','average_price':'4.5','event_id':'event-1','observed_at':'2026-01-01T00:00:00Z'})
            self.assertTrue(second['reconciled'])
            third=paper.record_fill(db,{**common,'quantity':'0.5','average_price':'12','fee':'0.2','event_id':'event-3','observed_at':'2026-01-03T00:00:00Z'})
            self.assertFalse(third['reconciled'])
            replay=paper.record_fill(db,{**common,'quantity':'0.5','average_price':'12','fee':'0.2','event_id':'event-3','observed_at':'2026-01-03T00:00:00Z'})
            self.assertEqual(replay['opened_legs'][0]['quantity'],'0.5')
            recovered=paper.list_spreads(db)[0]
            self.assertFalse(recovered['reconciled'])
            self.assertTrue(recovered['roll_blocked'])
            self.assertEqual(recovered['unhedged_quantity'],'0.5')


if __name__ == '__main__':
    unittest.main()
