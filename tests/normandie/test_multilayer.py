import json
import pathlib
import sys
import unittest

import numpy as np
import shapely

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools/normandie'))
from multilayer_score import clean, pilot_percentile, presence_percentile, spearman  # noqa: E402


class PercentileRules(unittest.TestCase):
    def test_zero_stays_zero_and_uncovered_is_null(self):
        values = np.array([0.0, 0.2, 0.4, 0.4, 0.0])
        covered = np.array([True, True, True, True, False])
        out = pilot_percentile(values, covered)
        self.assertEqual(out[0], 0.0)
        self.assertTrue(np.isnan(out[4]))
        self.assertEqual(out[2], out[3])          # ties share a midrank
        self.assertGreater(out[2], out[1])

    def test_presence_layer_never_lowers_a_cell(self):
        out = presence_percentile(np.array([0.0, 0.1, 0.5]))
        self.assertTrue(np.isnan(out[0]))         # absence is unknown, not zero
        self.assertTrue((out[1:] >= 50).all())

    def test_spearman_ignores_missing(self):
        a = np.array([1, 2, 3, np.nan, 5.0])
        b = np.array([2, 4, 6, 8, 10.0])
        self.assertAlmostEqual(spearman(a, b), 1.0)


class GeometryCleaning(unittest.TestCase):
    def test_mixed_collection_keeps_highest_dimension(self):
        gc = shapely.GeometryCollection([shapely.box(0, 0, 1, 1), shapely.LineString([(0, 0), (2, 2)])])
        out = clean(np.array([gc], dtype=object))
        self.assertEqual(int(shapely.get_dimensions(out[0])), 2)
        self.assertAlmostEqual(out[0].area, 1.0)


class ConfigContract(unittest.TestCase):
    def test_every_layer_declares_role_weight_and_coverage(self):
        cfg = json.loads((ROOT / 'tools/normandie/layer_scoring.json').read_text(encoding='utf-8'))
        for spec in cfg['layers']:
            self.assertIn(spec['c'], 'VDPO')
            self.assertGreater(spec['w'], 0)
            self.assertIn(spec['coverage'], ('regional', 'territorial', 'presence'))
            if spec['coverage'] == 'territorial':
                self.assertIn('territory', spec)
        for c in 'VDPO':
            self.assertTrue(any(s['c'] == c and s['coverage'] == 'regional' for s in cfg['layers']),
                            f'{c} needs at least one regional backbone layer')


class RegionalOutput(unittest.TestCase):
    """Regression guard on the published regional cells (skipped if not built)."""

    def test_no_criterion_is_null_or_flat(self):
        path = ROOT / 'dist/data/normandie/cells.geojson'
        if not path.exists():
            self.skipTest('regional cells not built')
        rows = [f['properties'] for f in json.loads(path.read_text())['features']]
        if rows[0].get('scoring') != 'multilayer_v1':
            self.skipTest('multilayer scoring not applied')
        for c in 'VDPO':
            vals = [r[c] for r in rows if r.get(c) is not None]
            self.assertGreaterEqual(len(vals) / len(rows), 0.95, c)
            top = max(np.unique(np.round(vals, 2), return_counts=True)[1])
            self.assertLessEqual(top / len(vals), 0.6, c)


if __name__ == '__main__':
    unittest.main()
