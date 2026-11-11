"""Workbench inside Renatura: atlas publishing, log files, secure URL intake, mounting under /workbench."""
import json
import os
import tempfile
import time
import unittest
from pathlib import Path

os.environ.setdefault('RENATURA_WORKBENCH_DATA', tempfile.mkdtemp(prefix='wb-int-'))
os.environ.setdefault('RENATURA_PUBLISH_DIR', tempfile.mkdtemp(prefix='wb-pub-'))
os.environ.setdefault('RENATURA_WORKBENCH_OPEN','1')  # functional tests; access rules are tested separately
from fastapi.testclient import TestClient  # noqa: E402

from pipeline.workbench import db, publish  # noqa: E402
from pipeline.workbench.app import app  # noqa: E402

EXAMPLES = Path(__file__).resolve().parents[2] / 'pipeline' / 'workbench' / 'examples'


class Integration(unittest.TestCase):
    def wait(self, c, key):
        deadline = time.time() + 30
        while time.time() < deadline:
            j = c.get('/api/jobs/' + key).json()
            if j['state'] not in ('queued', 'running'):
                return j
            time.sleep(.05)
        self.fail('worker did not finish')

    def test_populated_geojson_is_published_to_the_atlas_and_follows_trash(self):
        with TestClient(app) as c:
            cat = next(x for x in c.get('/api/intake/state').json()['categories'] if x['name'] == 'Eau')
            r = c.post('/api/intake/uploads', files={'file': ('canopy.geojson', (EXAMPLES / 'canopy.geojson').read_bytes(), 'application/json')},
                       data={'reference': 'Publish fixture', 'element_type': 'geojson', 'category_id': cat['id']})
            key = r.json()['batch_id']
            self.wait(c, r.json()['job_id'])
            self.wait(c, c.post(f'/api/intake/uploads/{key}/populate').json()['job_id'])
            f = publish.path_for(key)
            self.assertTrue(f.exists(), 'populated GeoJSON must appear in the atlas registry')
            out = json.loads(f.read_text())
            self.assertEqual(out['metadata']['theme'], 'water')
            self.assertEqual(len(out['data']['features']), db.get('datasets', key)['valid_count'])
            trash = c.delete(f'/api/intake/datasets/{key}').json()['trash_id']
            self.assertFalse(f.exists(), 'removing the dataset removes it from the atlas')
            c.post(f'/api/intake/trash/{trash}/restore')
            self.assertTrue(f.exists(), 'restoring puts it back')

    def test_events_are_written_to_daily_log_files(self):
        db.event('test-job', 'test-node', 'log file check', 'info')
        lines = [json.loads(line) for p in db.LOGS.glob('workbench-*.log') for line in p.read_text().splitlines()]
        self.assertTrue(any(x['message'] == 'log file check' and x['job'] == 'test-job' for x in lines))

    def test_url_intake_refuses_unsafe_links(self):
        with TestClient(app) as c:
            cat = c.get('/api/intake/state').json()['categories'][0]
            for url in ('http://example.org/data.geojson',           # not HTTPS
                        'https://127.0.0.1/data.geojson',            # local address
                        'https://localhost/data.geojson',
                        'https://user:pass@example.org/data.json',   # credentials in URL
                        'https://example.org/data.json?api_key=abc'):  # secret in URL
                r = c.post('/api/intake/fetch', json={'url': url, 'reference': 'unsafe', 'element_type': 'json', 'category_id': cat['id']})
                self.assertEqual(r.status_code, 422, url)
                self.assertIn('Fetch refused', r.json()['detail'])

    def test_optional_key_requirement_for_online_deployments(self):
        import hashlib
        store = tempfile.mkdtemp(prefix='wb-partners-')
        Path(store, 'partners.json').write_text(json.dumps({hashlib.sha256(b'good-key').hexdigest(): {'name': 'CEN test', 'expert': True}}))
        old = {k: os.environ.get(k) for k in ('RENATURA_WORKBENCH_REQUIRE_KEY', 'RENATURA_NATURE_STORE')}
        os.environ['RENATURA_WORKBENCH_REQUIRE_KEY'] = '1'
        os.environ['RENATURA_NATURE_STORE'] = store
        try:
            with TestClient(app) as c:
                self.assertEqual(c.get('/api/intake/state').status_code, 200)                       # reading: open
                body = {'name': 'Access test category', 'description': ''}
                self.assertEqual(c.post('/api/intake/categories', json=body).status_code, 401)     # no key
                self.assertEqual(c.post('/api/intake/categories', json=body, headers={'X-Partner-Key': 'bad'}).status_code, 401)
                r = c.post('/api/intake/categories', json=body, headers={'X-Partner-Key': 'good-key'})
                self.assertEqual(r.status_code, 200, r.text)
                self.assertEqual(c.get('/api/whoami', headers={'X-Partner-Key': 'good-key'}).json()['partner'], 'CEN test')
                audit = [e['message'] for e in db.recent_events() if e['node'] == 'access']
                self.assertTrue(any('CEN test' in m and 'categories' in m for m in audit))
        finally:
            for k, v in old.items():
                os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)

    def test_mounted_in_the_renatura_server(self):
        from pipeline.nature.server import app as site
        with TestClient(site) as c:
            self.assertEqual(c.get('/workbench/').status_code, 200)
            self.assertEqual(c.get('/workbench/api/intake/state').status_code, 200)
            self.assertIn('renatura', c.get('/workbench/').text.lower())


if __name__ == '__main__':
    unittest.main()
