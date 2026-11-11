"""End-to-end workflow test for every kind of upload: image, JSON, climate JSON, GeoJSON, land plans,
CSV (records / points), ZIP (GeoJSON, CSV, shapefile) and API fetch with a key.

Each case goes through the real pipeline: upload -> reference -> type_check -> validation -> routing
(-> populate -> datastore -> atlas publication), and the hostile cases must be blocked with a clear reason.
Run: .venv-normandie/bin/python -m unittest tests.workbench.test_upload_types -v
"""
import io
import json
import os
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from unittest import mock

os.environ.setdefault('RENATURA_WORKBENCH_DATA', tempfile.mkdtemp(prefix='wb-types-'))
os.environ.setdefault('RENATURA_PUBLISH_DIR', tempfile.mkdtemp(prefix='wb-types-pub-'))
os.environ.setdefault('RENATURA_WORKBENCH_OPEN', '1')
from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402

from pipeline.workbench import db, publish  # noqa: E402
from pipeline.workbench.app import app  # noqa: E402

EX = Path(__file__).resolve().parents[2] / 'pipeline' / 'workbench' / 'examples'


def zip_bytes(files: dict) -> bytes:
    b = io.BytesIO()
    with zipfile.ZipFile(b, 'w', zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            z.writestr(name, data)
    return b.getvalue()


class UploadTypes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = TestClient(app)
        cls.c = cls.ctx.__enter__()
        cats = cls.c.get('/api/intake/state').json()['categories']
        cls.cat = {c['name']: c['id'] for c in cats}

    @classmethod
    def tearDownClass(cls):
        cls.ctx.__exit__(None, None, None)

    # ---------- helpers
    def wait(self, job):
        deadline = time.time() + 60
        while time.time() < deadline:
            j = self.c.get('/api/jobs/' + job).json()
            if j['state'] not in ('queued', 'running'):
                return j
            time.sleep(.05)
        self.fail('workflow job did not finish')

    def upload(self, name, data, element_type, category='Biodiversité et continuités écologiques', **form):
        r = self.c.post('/api/intake/uploads', files={'file': (name, data, 'application/octet-stream')},
                        data={'reference': f'Test {name}', 'element_type': element_type, 'category_id': self.cat[category], **form})
        self.assertEqual(r.status_code, 202, r.text)
        self.assertEqual(self.wait(r.json()['job_id'])['state'], 'completed')
        return self.c.get('/api/intake/uploads/' + r.json()['batch_id']).json()

    def populate(self, batch):
        r = self.c.post(f'/api/intake/uploads/{batch["id"]}/populate')
        self.assertEqual(r.status_code, 202, r.text)
        self.assertEqual(self.wait(r.json()['job_id'])['state'], 'completed')
        d = db.get('datasets', batch['id'])
        self.assertIsNotNone(d, 'populated dataset must be in the datastore')
        return d

    def assertBlocked(self, batch, words):
        self.assertEqual(batch['state'], 'blocked', batch)
        self.assertTrue(any(w.lower() in (batch.get('error') or '').lower() for w in words), batch.get('error'))
        self.assertEqual(self.c.post(f'/api/intake/uploads/{batch["id"]}/populate').status_code, 409)

    # ---------- image
    def test_image_upload_strips_metadata_and_populates(self):
        img = Image.new('RGB', (320, 240), (60, 120, 70))
        exif = img.getexif()
        exif[0x010F] = 'CameraMaker'           # Make
        exif[0x8825] = {2: (49.0, 11.0, 0.0)}  # GPS (latitude) — must not survive
        buf = io.BytesIO()
        img.save(buf, 'JPEG', exif=exif)
        b = self.upload('photo.jpg', buf.getvalue(), 'image', 'Images et espèces')
        self.assertEqual(b['state'], 'ready')
        stored = Image.open(db.DATA / 'images' / f'{b["id"]}.jpg')
        self.assertEqual(len(stored.getexif()), 0, 'EXIF (GPS, device) must be removed')
        d = self.populate(b)
        self.assertEqual(d['kind'], 'image')
        self.assertFalse(publish.path_for(b['id']).exists(), 'images are not atlas layers')

    def test_image_is_enriched_by_the_species_model(self):
        from pipeline.workbench import species
        ok, why = species.available()
        if not ok:
            self.skipTest(why)
        photos = sorted((db.PROJECT / 'datasets/normandie_species/training_set/test').glob('*/*.jpg'))
        if not photos:
            self.skipTest('no test photo available')
        photo = photos[0]
        b = self.upload(photo.name, photo.read_bytes(), 'image', 'Images et espèces')
        self.assertEqual(b['state'], 'ready', b.get('error'))
        det = b['detection']
        self.assertEqual(len(det['top5']), 5)
        self.assertIn(det['status'], ('proposed_high_confidence', 'to_confirm'))
        self.assertTrue(0 < det['species']['probability'] <= 1)
        record = self.populate(b)['data'][0]
        for field in ('species_scientific_name', 'species_french_name', 'detection_confidence', 'detection_status', 'detection_candidates'):
            self.assertIn(field, record)
        print(f"\n  model on {photo.parent.name}: proposed {record['species_scientific_name']} "
              f"({record['detection_confidence']:.0%}, {record['detection_status']})")

    def test_detection_step_is_not_applicable_to_tables(self):
        b = self.upload('mini.csv', b'a,b\n1,2\n', 'json')
        self.assertEqual(b['detection']['status'], 'not_applicable')
        self.assertEqual(b['state'], 'ready')

    def test_corrupt_image_is_blocked(self):
        self.assertBlocked(self.upload('fake.jpg', b'this is not an image', 'image', 'Images et espèces'), ['cannot identify', 'image'])

    # ---------- JSON records / climate
    def test_json_records_with_schema_partial_then_populate(self):
        rows = [{'id': 1, 'value': 3.5}, {'id': 2, 'value': 'oops'}, {'id': 3, 'value': 7}]
        schema = json.dumps({'type': 'object', 'properties': {'value': {'type': 'number'}}, 'required': ['value']})
        b = self.upload('rows.json', json.dumps(rows).encode(), 'json', schema_text=schema)
        self.assertEqual((b['state'], b['accepted_count'], b['rejected_count']), ('partial_ready', 2, 1))
        self.assertEqual(self.populate(b)['valid_count'], 2)

    def test_climate_records(self):
        b = self.upload('climate.json', (EX / 'climate.json').read_bytes(), 'climate', 'Climat')
        self.assertIn(b['state'], ('ready', 'partial_ready'))
        self.assertGreater(b['accepted_count'], 0)

    def test_invalid_json_is_blocked(self):
        self.assertBlocked(self.upload('broken.json', b'{"a": [1, 2', 'json'), ['expecting', 'json', 'delimiter'])

    # ---------- GeoJSON layer / land plans
    def test_geojson_layer_populates_and_is_published(self):
        b = self.upload('canopy.geojson', (EX / 'canopy.geojson').read_bytes(), 'geojson')
        self.assertIn(b['state'], ('ready', 'partial_ready'))
        self.populate(b)
        out = json.loads(publish.path_for(b['id']).read_text())
        self.assertEqual(out['metadata']['theme'], 'biodiversity')

    def test_land_plans_foncier(self):
        b = self.upload('land.geojson', (EX / 'land.geojson').read_bytes(), 'foncier', 'Foncier')
        self.assertIn(b['state'], ('ready', 'partial_ready'))
        self.populate(b)
        self.assertEqual(json.loads(publish.path_for(b['id']).read_text())['metadata']['theme'], 'landuse')

    def test_geojson_in_records_box_is_blocked(self):
        self.assertBlocked(self.upload('canopy.geojson', (EX / 'canopy.geojson').read_bytes(), 'json'), ['geojson', 'records'])

    # ---------- CSV
    def test_csv_records_with_semicolon_and_decimal_comma(self):
        csv_text = 'commune;surface_ha;remarque\nCaen;12,5;ok\nBayeux;3;\nLisieux;7,25;haie\n'
        b = self.upload('parcelles.csv', csv_text.encode(), 'json')
        self.assertEqual((b['state'], b['accepted_count']), ('ready', 3))
        self.assertIn('decimal comma', b['source_format'])
        rows = self.populate(b)['data']
        self.assertEqual(rows[0]['surface_ha'], 12.5)
        self.assertIsNone(rows[1]['remarque'])

    def test_csv_points_for_a_geographic_box(self):
        csv_text = 'name,latitude,longitude,count\nA,49.18,-0.37,3\nB,49.44,1.09,5\nC,not-a-number,0.1,1\n'
        b = self.upload('observations.csv', csv_text.encode(), 'geojson')
        self.assertEqual((b['state'], b['accepted_count'], b['rejected_count']), ('partial_ready', 2, 1))
        d = self.populate(b)
        self.assertEqual(d['data']['features'][0]['geometry']['type'], 'Point')

    def test_csv_without_coordinates_in_geographic_box_is_blocked(self):
        self.assertBlocked(self.upload('nocoords.csv', b'name,count\nA,1\n', 'geojson'), ['latitude'])

    # ---------- ZIP
    def test_zip_with_geojson(self):
        b = self.upload('layer.zip', zip_bytes({'data/canopy.geojson': (EX / 'canopy.geojson').read_bytes()}), 'geojson')
        self.assertIn(b['state'], ('ready', 'partial_ready'))
        self.assertIn('zip', b['source_format'])

    def test_zip_with_csv(self):
        b = self.upload('table.zip', zip_bytes({'table.csv': 'a,b\n1,2\n3,4\n'}), 'json')
        self.assertEqual((b['state'], b['accepted_count']), ('ready', 2))

    def test_zip_with_shapefile_is_reprojected_to_wgs84(self):
        import geopandas as gpd
        from shapely.geometry import Point
        with tempfile.TemporaryDirectory() as tmp:
            gpd.GeoDataFrame({'nom': ['Caen', 'Rouen']}, geometry=[Point(454000, 6904000), Point(562000, 6928000)],
                             crs='EPSG:2154').to_file(Path(tmp) / 'sites.shp')
            files = {f'sites{e}': (Path(tmp) / f'sites{e}').read_bytes() for e in ('.shp', '.shx', '.dbf', '.prj', '.cpg') if (Path(tmp) / f'sites{e}').exists()}
        b = self.upload('sites.zip', zip_bytes(files), 'foncier', 'Foncier')
        self.assertEqual(b['state'], 'ready', b.get('error'))
        self.assertIn('WGS84', b['source_format'])
        x, y = self.populate(b)['data']['features'][0]['geometry']['coordinates']
        self.assertTrue(-2 < x < 2 and 48 < y < 51, (x, y))

    def test_zip_shapefile_without_projection_is_blocked(self):
        self.assertBlocked(self.upload('noprj.zip', zip_bytes({'a.shp': b'x', 'a.shx': b'x', 'a.dbf': b'x'}), 'geojson'), ['.prj'])

    def test_zip_path_traversal_is_blocked(self):
        self.assertBlocked(self.upload('evil.zip', zip_bytes({'../../evil.json': '[]'}), 'json'), ['unsafe path'])

    def test_zip_bomb_is_blocked(self):
        self.assertBlocked(self.upload('bomb.zip', zip_bytes({'zeros.json': b'0' * (8 * 1024 * 1024)}), 'json'), ['zip bomb', 'ratio'])

    def test_zip_with_two_datasets_is_blocked(self):
        self.assertBlocked(self.upload('two.zip', zip_bytes({'a.csv': 'a\n1\n', 'b.csv': 'b\n2\n'}), 'json'), ['one dataset'])

    # ---------- API with a key
    def fetch(self, body, handler):
        import httpx
        real = httpx.Client
        with mock.patch('pipeline.ingest.api.public_url', side_effect=lambda u: u if u.startswith('https://') else (_ for _ in ()).throw(ValueError('HTTPS only'))), \
             mock.patch('httpx.Client', lambda **kw: real(transport=httpx.MockTransport(handler), **kw)):
            return self.c.post('/api/intake/fetch', json={'category_id': self.cat['Climat'], 'reference': 'API test', **body})

    def test_api_with_key_header_is_fetched_and_the_key_is_never_stored(self):
        secret = 'sk-test-0123456789abcdef'
        seen = {}

        def api(request):
            seen['key'] = request.headers.get('X-API-Key')
            return __import__('httpx').Response(200, json=[{'station': 'Caen', 'temp': 12.4}, {'station': 'Rouen', 'temp': 11.9}])
        r = self.fetch({'url': 'https://api.example.org/v1/climate', 'element_type': 'climate', 'api_key': secret, 'api_key_header': 'X-API-Key'}, api)
        self.assertEqual(r.status_code, 202, r.text)
        self.assertEqual(seen['key'], secret, 'the key must be sent in the chosen header')
        self.assertEqual(self.wait(r.json()['job_id'])['state'], 'completed')
        b = self.c.get('/api/intake/uploads/' + r.json()['batch_id']).json()
        self.assertEqual((b['state'], b['accepted_count']), ('ready', 2))
        self.assertIn('non stockée', b['auth'])
        stored = json.dumps(db.get('batches', b['id'])) + ''.join(p.read_text() for p in db.LOGS.glob('*.log'))
        self.assertNotIn(secret, stored, 'the API key must never be stored or logged')

    def test_api_refusing_the_key_gives_a_clear_error_without_the_key(self):
        secret = 'sk-wrong-key-987654321'
        r = self.fetch({'url': 'https://api.example.org/v1/climate', 'element_type': 'climate', 'api_key': secret},
                       lambda req: __import__('httpx').Response(401, json={'error': f'bad key {secret}'}))
        self.assertEqual(r.status_code, 422)
        self.assertIn('HTTP 401', r.json()['detail'])
        self.assertNotIn(secret, r.json()['detail'])

    def test_api_key_is_not_forwarded_to_another_host_on_redirect(self):
        secret = 'sk-redirect-555'
        hits = []

        def api(request):
            hits.append((request.url.host, request.headers.get('Authorization')))
            if request.url.host == 'api.example.org':
                return __import__('httpx').Response(302, headers={'location': 'https://cdn.other.net/data.json'})
            return __import__('httpx').Response(200, json=[{'v': 1}])
        r = self.fetch({'url': 'https://api.example.org/data', 'element_type': 'json', 'api_key': secret}, api)
        self.assertEqual(r.status_code, 202, r.text)
        self.assertEqual(hits[0], ('api.example.org', secret))
        self.assertEqual(hits[1], ('cdn.other.net', None), 'the key must not follow a redirect to another host')

    def test_api_key_in_a_forbidden_header_is_refused(self):
        r = self.fetch({'url': 'https://api.example.org/data', 'element_type': 'json', 'api_key': 'x', 'api_key_header': 'Host'},
                       lambda req: __import__('httpx').Response(200, json=[]))
        self.assertEqual(r.status_code, 422)


if __name__ == '__main__':
    unittest.main()
