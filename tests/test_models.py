"""Synthetic fixtures are confined to tests; no invented app observations."""
import itertools
import json
import math
from pathlib import Path
import tempfile
import unittest
import zipfile

from pipeline.scoring import score_site, rank_sites, percentile_scores, normalize_weights
from pipeline.optimisation import solve, objective, naive_selection, resource_cost
from pipeline.connectivity import connection_total
from pipeline.sensitivity import monte_carlo
from pipeline.io import extract

ROOT = Path(__file__).resolve().parent.parent


def site(name, value, area=1):
    return {'id': name, 'V': value, 'D': value, 'P': value, 'O': value,
            'area_ha': area, 'proxy_cost': area}


class ScoringTests(unittest.TestCase):
    def test_missing_is_not_zero(self):
        row = site('a', 50)
        row['P'] = None
        self.assertIsNone(score_site(row)['score'])
        self.assertEqual(score_site(row, allow_partial=True)['score'], 50)
        self.assertEqual(score_site(row, allow_partial=True)['coverage'], 75)

    def test_zero_weight_missing_is_safe(self):
        row = site('a', 50)
        row['O'] = None
        self.assertAlmostEqual(score_site(row, [1, 1, 1, 0])['score'], 50)

    def test_ecological_threshold(self):
        self.assertIsNone(score_site(site('low', 9))['score'])

    def test_invalid_weights(self):
        for weights in ([0, 0, 0, 0], [1, -1, 2, 3], [math.nan, 1, 2, 3]):
            with self.assertRaises(ValueError):
                normalize_weights(weights)

    def test_midrank_and_null(self):
        self.assertEqual(percentile_scores([0, 5, 5, None]), [0, 100 * 2 / 3, 100 * 2 / 3, None])


class OptimisationTests(unittest.TestCase):
    def setUp(self):
        self.sites = [site('a', 90, 5), site('b', 70, 3), site('c', 60, 3), site('d', 25, 1)]
        self.paths = [{'id': 'p1', 'sites': ['b', 'c'], 'gain': 100}]

    def test_ilp_matches_exhaustive_search(self):
        for mode, budget in [('sites', 2), ('hectares', 6), ('proxy', 7)]:
            result = solve(self.sites, self.paths, mode=mode, budget=budget, connectivity_weight=.8)
            ranked = rank_sites(self.sites)
            expected = 0
            for bits in itertools.product([0, 1], repeat=len(ranked)):
                chosen = [s for s, bit in zip(ranked, bits) if bit]
                if sum(resource_cost(s, mode) for s in chosen) <= budget:
                    expected = max(expected, objective([s['id'] for s in chosen], ranked, self.paths, .8))
            self.assertEqual(result['status'], 'OPTIMAL')
            self.assertAlmostEqual(result['objective'], expected)
            self.assertLessEqual(result['used'], budget + 1e-8)

    def test_top_n_already_optimal_without_connections(self):
        result = solve(self.sites, [], budget=2, connectivity_weight=0)
        self.assertAlmostEqual(result['gain_percent'], 0)

    def test_route_requires_all_sites(self):
        self.assertEqual(connection_total(['b'], self.paths), 0)
        self.assertEqual(connection_total(['b', 'c'], self.paths), 100)

    def test_zero_budget(self):
        result = solve(self.sites, self.paths, budget=0)
        self.assertEqual(result['selected'], [])
        self.assertIsNone(result['gain_percent'])

    def test_missing_data_returns_no_eligible(self):
        rows = [dict(row, P=None) for row in self.sites]
        self.assertEqual(solve(rows, self.paths)['status'], 'NO_ELIGIBLE_DATA')

    def test_budget_validation(self):
        with self.assertRaises(ValueError):
            solve(self.sites, [], budget=-1)


class SensitivityTests(unittest.TestCase):
    def test_reproducibility_and_range(self):
        rows = [site(str(i), i + 20) for i in range(30)]
        first = monte_carlo(rows, runs=30)
        self.assertEqual(first, monte_carlo(rows, runs=30))
        self.assertEqual(first['mean_top20_jaccard'], 1)
        self.assertTrue(all(0 <= row['top20_frequency'] <= 1 for row in first['sites']))


class IntegrityTests(unittest.TestCase):
    def test_zip_traversal_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'bad.zip'
            with zipfile.ZipFile(path, 'w') as z:
                z.writestr('../escape', 'bad')
            with self.assertRaises(ValueError):
                extract(path, Path(directory) / 'out')

    def test_real_export_validity(self):
        cells = json.loads((ROOT / 'dist/data/cells.geojson').read_text())['features']
        self.assertGreater(len(cells), 0)
        self.assertEqual(len(cells), len({f['properties']['id'] for f in cells}))
        self.assertTrue(all(f['properties']['P'] is None for f in cells))
        self.assertTrue(all(f['properties']['O'] is None for f in cells))
        sites = [f['properties'] for f in cells]
        scenarios = json.loads((ROOT / 'dist/data/scenarios.json').read_text())
        paths = json.loads((ROOT / 'dist/data/connectivity.json').read_text())['paths']
        for scenario in scenarios:
            lookup = {s['id']: s for s in rank_sites(sites, scenario['weights'], True)}
            self.assertTrue(set(scenario['selected']).issubset(lookup))
            used = sum(resource_cost(lookup[id], scenario['mode']) for id in scenario['selected'])
            self.assertLessEqual(used, scenario['budget'] + 1e-6)
            self.assertAlmostEqual(scenario['objective'], objective(scenario['selected'], list(lookup.values()), paths, .35), places=5)
            self.assertGreaterEqual(scenario['objective'] + 1e-6, scenario['baseline_objective'])


if __name__ == '__main__':
    unittest.main()
