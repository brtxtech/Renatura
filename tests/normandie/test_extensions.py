"""Tests for the three extensions: prices (DVF + barème), climate trends, nature-photo API rules."""
import importlib
import io
import json
import os
import pathlib
import sys
import tempfile
import unittest

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools/normandie'))
sys.path.insert(0, str(ROOT))


class PriceRules(unittest.TestCase):
    def test_bareme_has_the_five_normandy_departments(self):
        import price_cells
        if not (price_cells.SRC / 'bareme_2024_jorf.txt').exists():
            self.skipTest('barème not downloaded')
        rows = price_cells.parse_bareme()
        self.assertEqual({r['department'] for r in rows}, {'14', '27', '50', '61', '76'})
        for r in rows:
            self.assertLessEqual(r['min'], r['dominant'])
            self.assertLessEqual(r['dominant'], r['max'])

    def test_published_prices_rest_on_at_least_five_sales(self):
        path = ROOT / 'dist/data/normandie/prices.json'
        if not path.exists():
            self.skipTest('prices not built')
        cells = json.loads(path.read_text())['cells']
        for rec in list(cells.values())[:5000]:
            for c in ('agri', 'forest', 'rural'):
                if c in rec:
                    self.assertGreaterEqual(rec[c]['n'], 5)


class ClimateTrends(unittest.TestCase):
    def test_sen_slope_and_mann_kendall(self):
        from climate_history import sen_mk
        years = list(range(1991, 2026))
        rng = np.random.default_rng(0)
        warming = [10 + 0.03 * (y - 1991) + rng.normal(0, 0.1) for y in years]
        flat = [10 + rng.normal(0, 0.3) for y in years]
        t = sen_mk(years, warming)
        self.assertAlmostEqual(t['slope_per_decade'], 0.3, delta=0.08)
        self.assertTrue(t['significant'])
        self.assertFalse(sen_mk(years, flat)['significant'])
        self.assertIsNone(sen_mk(years[:5], warming[:5]))  # too short


class NaturePhotoRules(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from fastapi.testclient import TestClient  # noqa: F401
        except Exception:
            raise unittest.SkipTest('fastapi test client unavailable')
        cls.tmp = tempfile.TemporaryDirectory()
        os.environ['RENATURA_NATURE_STORE'] = cls.tmp.name
        import pipeline.nature.server as server
        cls.server = importlib.reload(server)
        s = cls.server
        # stub model + cell index: rules are tested, not the network
        s.MODEL.predict = lambda img: [{'scientific_name': 'Lutra lutra', 'french_name': 'Loutre', 'group_en': 'mammals',
                                        'probability': 0.6}] + [{'scientific_name': f'sp{i}', 'french_name': '', 'group_en': 'x',
                                                                 'probability': 0.1} for i in range(4)]
        s.MODEL.threshold = 0.9
        s.CELL_INDEX.find = lambda lon, lat: 'H1_TEST' if 48 < lat < 51 else None
        s.SPECIES = {'Lutra lutra': {'protected_france': 'True', 'red_list_normandie': 'EN', 'group_en': 'mammals'}}
        import hashlib
        keys = {'a': {'name': 'A', 'expert': False}, 'b': {'name': 'B', 'expert': False}}
        (pathlib.Path(cls.tmp.name) / 'partners.json').write_text(json.dumps({hashlib.sha256(k.encode()).hexdigest(): v for k, v in keys.items()}))
        from fastapi.testclient import TestClient
        cls.client = TestClient(s.app)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()
        os.environ.pop('RENATURA_NATURE_STORE', None)

    def jpeg(self):
        from PIL import Image
        b = io.BytesIO()
        Image.new('RGB', (64, 64), (40, 120, 60)).save(b, 'JPEG')
        return b.getvalue()

    def test_upload_needs_partner_key_and_position(self):
        c = self.client
        r = c.post('/api/nature/photos', files={'file': ('x.jpg', self.jpeg(), 'image/jpeg')})
        self.assertEqual(r.status_code, 401)
        r = c.post('/api/nature/photos', files={'file': ('x.jpg', self.jpeg(), 'image/jpeg')}, headers={'X-Partner-Key': 'a'})
        self.assertEqual(r.status_code, 422)  # no GPS, no manual position
        r = c.post('/api/nature/photos', files={'file': ('x.jpg', self.jpeg(), 'image/jpeg')}, data={'lat': 40, 'lon': 0},
                   headers={'X-Partner-Key': 'a'})
        self.assertEqual(r.status_code, 422)  # outside Normandy

    def test_two_partners_confirm_and_sensitive_species_are_generalised(self):
        c = self.client
        r = c.post('/api/nature/photos', files={'file': ('x.jpg', self.jpeg(), 'image/jpeg')}, data={'lat': 49.12345, 'lon': 0.12345},
                   headers={'X-Partner-Key': 'a'}).json()
        self.assertEqual(r['status'], 'pending')  # 0.6 < auto threshold 0.9
        pid = r['id']
        v = c.post(f'/api/nature/photos/{pid}/validate', json={'decision': 'confirm'}, headers={'X-Partner-Key': 'a'}).json()
        self.assertEqual(v['status'], 'pending')  # one non-expert is not enough
        v = c.post(f'/api/nature/photos/{pid}/validate', json={'decision': 'confirm'}, headers={'X-Partner-Key': 'b'}).json()
        self.assertEqual(v['status'], 'confirmed')
        public = c.get('/api/nature/photos').json()
        row = next(x for x in public if x['id'] == pid)
        self.assertTrue(row['location_generalised'])  # protected otter: 10 km precision for the public
        self.assertIsNone(row['cell_id'])
        self.assertNotEqual(row['lat'], 49.12345)
        ev = c.get('/api/nature/evidence').json()
        self.assertEqual(ev['cells']['H1_TEST']['protected_species'], ['Lutra lutra'])

    def test_stored_photo_has_no_exif(self):
        from PIL import Image
        img = Image.new('RGB', (64, 64))
        exif = img.getexif()
        exif[0x010F] = 'CameraMaker'
        b = io.BytesIO()
        img.save(b, 'JPEG', exif=exif)
        r = self.client.post('/api/nature/photos', files={'file': ('x.jpg', b.getvalue(), 'image/jpeg')}, data={'lat': 49.2, 'lon': -0.3},
                             headers={'X-Partner-Key': 'a'}).json()
        stored = Image.open(pathlib.Path(self.tmp.name) / 'photos' / f"{r['id']}.jpg")
        self.assertEqual(len(stored.getexif()), 0)


if __name__ == '__main__':
    unittest.main()
