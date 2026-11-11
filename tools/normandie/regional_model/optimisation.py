"""Binary site-selection ILP, equal-constraint baseline, and audit output."""
from __future__ import annotations

import math
import pulp
from .connectivity import connection_total
from .scoring import rank_sites, DEFAULT_WEIGHTS

# proxy = land acquisition cost in k€ (DVF median €/ha × area, attached by complete_region.py), same as the browser.
COST_FIELDS = {'sites': None, 'hectares': 'area_ha', 'proxy': 'land_cost_keur'}


def resource_cost(site, mode):
    if mode not in COST_FIELDS:
        raise ValueError(f'Unknown constraint: {mode}')
    field = COST_FIELDS[mode]
    if field is None:
        return 1.0
    value = site.get(field)
    return float(value) if isinstance(value, (int, float)) else math.nan


def validate_budget(budget):
    if not isinstance(budget, (int, float)) or not math.isfinite(budget) or budget < 0:
        raise ValueError('Budget must be finite and nonnegative')


def objective(selected, sites, paths, connectivity_weight):
    lookup = {site['id']: site for site in sites}
    return sum(lookup[id]['score'] for id in selected) + connectivity_weight * connection_total(selected, paths)


def naive_selection(sites, mode, budget):
    """Descending score; skip unaffordable sites, under identical constraints."""
    validate_budget(budget)
    selected = []
    used = 0.0
    for site in sorted(sites, key=lambda x: (-x['score'], x['id'])):
        cost = resource_cost(site, mode)
        if used + cost <= budget + 1e-8:
            selected.append(site['id'])
            used += cost
    return selected


def solve(sites, paths, mode='sites', budget=10, connectivity_weight=0.35,
          weights=DEFAULT_WEIGHTS, allow_partial=False, seconds=30, min_area=0):
    validate_budget(budget)
    if not math.isfinite(connectivity_weight) or connectivity_weight < 0:
        raise ValueError('Connectivity weight must be nonnegative')
    # Same rules as the browser solver (dist/worker.js): only sites of at least min_area hectares with a known
    # cost, and a site is worth its priority × its share of a complete cell (no filling the budget with slivers).
    def usable(site):
        cost = resource_cost(site, mode)
        return (site.get('area_ha') or 0) >= min_area and math.isfinite(cost) and cost > 0
    sites = [site for site in sites if usable(site)]
    full_area = max((site.get('area_ha') or 0 for site in sites), default=0) or 1
    ranked = rank_sites(sites, weights, allow_partial)
    for row in ranked:
        row['rp'] = row['score']
        row['score'] = row['score'] * (row.get('area_ha') or 0) / full_area
    ranked.sort(key=lambda x: (-x['score'], x['id']))
    if not ranked:
        return {'status': 'NO_ELIGIBLE_DATA', 'selected': [], 'mode': mode, 'budget': budget}
    for row in ranked:
        cost = resource_cost(row, mode)
        if not math.isfinite(cost) or cost <= 0:
            raise ValueError('Site costs must be finite and positive')
    candidates = ranked
    if mode == 'sites':
        # Exact reduction: with unit costs, any optimal cell outside corridors is among the top-B by score.
        eligible_ids = {row['id'] for row in ranked}
        route_cells = {n for p in paths if set(p['sites']).issubset(eligible_ids) for n in p['sites']}
        top = [row for row in ranked if row['id'] not in route_cells][:int(math.floor(budget))]
        keep = {row['id'] for row in top} | route_cells
        candidates = [row for row in ranked if row['id'] in keep]
    model = pulp.LpProblem('Renatura', pulp.LpMaximize)
    variables = {row['id']: pulp.LpVariable(row['id'], cat='Binary') for row in candidates}
    route_variables = {}
    valid_paths = [p for p in paths if set(p['sites']).issubset(variables)]
    for path in valid_paths:
        y = pulp.LpVariable(path['id'], cat='Binary')
        route_variables[path['id']] = y
        for node in path['sites']:
            model += y <= variables[node]
        model += y >= pulp.lpSum(variables[node] for node in path['sites']) - len(path['sites']) + 1
    model += pulp.lpSum(variables[row['id']] * resource_cost(row, mode) for row in candidates) <= budget
    model += (pulp.lpSum(variables[row['id']] * row['score'] for row in candidates)
              + connectivity_weight * pulp.lpSum(route_variables[p['id']] * p['gain'] for p in valid_paths))
    # Warm start from the greedy baseline so a time-limited solve never returns less than the baseline.
    used_start, start = 0.0, set()
    for row in candidates:
        cost = resource_cost(row, mode)
        if used_start + cost <= budget + 1e-8:
            start.add(row['id'])
            used_start += cost
    for node, variable in variables.items():
        variable.setInitialValue(1 if node in start else 0)
    for path in valid_paths:
        route_variables[path['id']].setInitialValue(1 if set(path['sites']) <= start else 0)
    solver = pulp.PULP_CBC_CMD(msg=False, timeLimit=seconds, threads=1, warmStart=True,
                               options=['randomSeed 42'])
    model.solve(solver)
    # CBC can label a stopped incumbent as LpStatusOptimal: inspect sol_status.
    proven = model.sol_status == pulp.LpSolutionOptimal
    incumbent = model.sol_status in (pulp.LpSolutionOptimal, pulp.LpSolutionIntegerFeasible)
    selected = sorted(node for node, variable in variables.items()
                      if incumbent and variable.value() is not None and variable.value() > 0.5)
    lookup = {s['id']: s for s in ranked}
    used = sum(resource_cost(lookup[node], mode) for node in selected)
    if used > budget + 1e-6:
        raise AssertionError('Solver selection violates budget')
    baseline = naive_selection(ranked, mode, budget)
    value = objective(selected, ranked, valid_paths, connectivity_weight)
    baseline_value = objective(baseline, ranked, valid_paths, connectivity_weight)
    # Loose but valid universal upper bound for nonnegative coefficients.
    upper = value if proven else sum(s['score'] for s in ranked) + connectivity_weight * sum(p['gain'] for p in valid_paths)
    status = 'OPTIMAL' if proven else ('FEASIBLE' if incumbent else pulp.LpStatus[model.status])
    return {
        'status': status,
        'selected': selected,
        'baseline': baseline,
        'mode': mode,
        'budget': budget,
        'min_area': min_area,
        'eligible': len(ranked),
        'used': used,
        'weights': list(weights),
        'connectivity_weight': connectivity_weight,
        'allow_partial': allow_partial,
        'objective': value,
        'baseline_objective': baseline_value,
        'gain_percent': (100 * (value / baseline_value - 1)) if baseline_value else None,
        'upper_bound': upper,
        'bound_kind': 'exact' if proven else 'conservative universal bound',
        'gap_percent': 100 * (upper - value) / max(abs(value), 1),
        'priority_total': sum(lookup[node]['score'] for node in selected),
        'connectivity_total': connection_total(selected, valid_paths),
        'baseline_connectivity': connection_total(baseline, valid_paths),
        'area_ha': sum(lookup[node]['area_ha'] for node in selected),
        'proxy_cost': sum(lookup[node].get('proxy_cost') or 0 for node in selected),
        'land_cost_keur': sum(lookup[node].get('land_cost_keur') or 0 for node in selected),
        'solver': 'PuLP / CBC, single thread, seed 42',
    }
