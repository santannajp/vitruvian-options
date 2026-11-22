import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import app


class PositionTest(unittest.TestCase):
    def test_position_persists_and_calculates_health_factor(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(app, 'DB', Path(directory) / 'test.db'):
            data = dict(account='conta', network='ethereum', market='aave', token='WBTC', contract='0x123', quantity='1', price='100', threshold='80', debt_token='USDC', debt_contract='0x456', debt_quantity='40', debt_price='1', source='manual', observed_at='2026-01-01T12:00')
            app.save(data)
            self.assertEqual(app.load()['health_factor'], '2')
            data['debt_quantity'] = '0'
            app.save(data)
            self.assertIsNone(app.load()['health_factor'])
            self.assertEqual(app.load()['contract'], '0x123')

    def test_invalid_threshold_does_not_replace_saved_position(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(app, 'DB', Path(directory) / 'test.db'):
            data = dict(account='conta', network='ethereum', market='aave', token='WBTC', contract='0x123', quantity='1', price='100', threshold='80', debt_token='USDC', debt_contract='0x456', debt_quantity='40', debt_price='1', source='manual', observed_at='2026-01-01T12:00')
            app.save(data)
            data['threshold'] = '101'
            with self.assertRaises(ValueError):
                app.save(data)
            self.assertEqual(app.load()['threshold'], '80')


if __name__ == '__main__':
    unittest.main()

class HttpTest(unittest.TestCase):
    def test_save_and_reload_over_http(self):
        import json
        import threading
        from urllib.request import Request, urlopen

        with tempfile.TemporaryDirectory() as directory, patch.object(app, 'DB', Path(directory) / 'test.db'):
            server = app.ThreadingHTTPServer(('127.0.0.1', 0), app.Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                url = f'http://127.0.0.1:{server.server_port}'
                with urlopen(url) as response:
                    self.assertIn('Minha posição na Aave', response.read().decode())
                data = dict(account='conta', network='ethereum', market='aave', token='WBTC', contract='0x123', quantity='1', price='100', threshold='80', debt_token='USDC', debt_contract='0x456', debt_quantity='40', debt_price='1', source='manual', observed_at='2026-01-01T12:00')
                request = Request(url + '/api/position', data=json.dumps(data).encode(), headers={'Content-Type': 'application/json'}, method='POST')
                with urlopen(request) as response:
                    self.assertEqual(json.load(response)['health_factor'], '2')
                with urlopen(url + '/api/position') as response:
                    self.assertEqual(json.load(response)['token'], 'WBTC')
                scenario = {'account': 'conta', 'network': 'ethereum', 'market': 'aave', 'btc_price': '100', 'observed_at': '2026-01-01T12:00Z', 'snapshot': True, 'collateral': [{'token': 'WBTC', 'contract': '0x123', 'quantity': '1', 'btc_ratio': '1', 'threshold': '80'}], 'debts': [{'token': 'USDC', 'contract': '0x456', 'quantity': '40', 'price': '1'}]}
                request = Request(url + '/api/scenario', data=json.dumps(scenario).encode(), headers={'Content-Type': 'application/json'}, method='POST')
                with urlopen(request) as response:
                    self.assertEqual(json.load(response)['current']['result']['health_factor'], '2')
                with urlopen(url + '/api/scenario?account=conta&network=ethereum&market=aave') as response:
                    self.assertEqual(json.load(response)['original']['input']['account'], 'conta')
            finally:
                server.shutdown()
                server.server_close()
                thread.join()

class ScenarioTest(unittest.TestCase):
    def test_multiple_assets_and_immutable_original(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(app, 'DB', Path(directory) / 'test.db'):
            data = {'account': 'carteira', 'network': 'ethereum', 'market': 'aave', 'btc_price': '100', 'observed_at': '2026-01-01T00:00:00Z', 'collateral': [{'token': 'WBTC', 'contract': '0x1', 'quantity': '1', 'btc_ratio': '1', 'threshold': '80'}, {'token': 'cbBTC', 'contract': '0x2', 'quantity': '1', 'btc_ratio': '1', 'threshold': '80'}], 'debts': [{'token': 'USDC', 'contract': '0x3', 'quantity': '40', 'price': '1'}, {'token': 'USDT', 'contract': '0x4', 'quantity': '40', 'price': '1'}]}
            first = app.scenario(data, True)
            self.assertEqual(first['current']['result']['health_factor'], '2')
            self.assertEqual(float(first['current']['result']['liquidation_btc_price']), 50)
            data['debts'][1]['price'] = '2'
            second = app.scenario(data)
            self.assertEqual(second['current']['result']['health_factor'], '1.333333333333333333333333333')
            self.assertEqual(second['original']['result']['health_factor'], '2')
            self.assertEqual(app.scenario()['original']['input']['debts'][1]['price'], '1')
            data['account'] = 'outra'
            app.scenario(data)
            self.assertEqual(app.scenario(identity=('carteira', 'ethereum', 'aave'))['current']['input']['account'], 'carteira')
            self.assertEqual(app.scenario(identity=('outra', 'ethereum', 'aave'))['current']['input']['account'], 'outra')
