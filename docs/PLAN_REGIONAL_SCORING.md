# Plan: make the regional Normandy atlas meaningful (multi-layer weighting)

Status: implemented in `tools/normandie/multilayer_score.py` + `tools/normandie/layer_scoring.json`.
Reference result: the pilot **"Bocages du sud Pays d'Auge"** (FR2502014, `dist/pays-auge.html`).

## 1. Diagnosis: why the regional map shows nulls and identical values

Audit of `dist/data/normandie/cells.geojson` (30,850 cells of 1 km²) before the fix:

| criterion | cells with a value | why |
|---|---|---|
| V (ecological value) | 145 / 30,850 (0.5 %) | defined only by hedges + woodland from the **pilot FR2502014**; the regional hedge/woodland layers are empty files (42 bytes) |
| D (degradation) | 145 / 30,850 | hedge loss 2010→2016, again pilot only |
| P (pressure) | 30,850 | built + ICPE + rail only; ~70 % of cells share P = 0 (no building, no ICPE, no rail) → same colour |
| O (opportunity) | 0 / 30,850 | "documented land availability" required; no source accepted |

Then `score_site()` / `scoreSite()` make a cell **eligible only if V ≥ 10**. V is null in 99.5 % of
cells, so the final score is null almost everywhere. The few values left come from P, which is
mostly 0. Hence "null and the same value in all parts".

The 198 declared layers (354 catalogue references, 275 with mapped geometry, 2.93 M features) were
only used as *context* (`add_context_score.py`, a document-density index on 5 × 5 km zones). None of them
entered V/D/P/O.

## 2. Principles of the fix

1. **Use the real layers, every one with a declared role.** Each retained layer gets a criterion (V, D, P,
   O), a sign, a weight, an aggregation (area fraction, line density, point density, or an attribute class)
   and a **coverage class**:
   - `regional`: COMPLETE / FILE_VERIFIED over the whole region → absence of feature = true 0.
   - `territorial`: complete on a known territory (department group 14-50-61 or 27-76, an EPCI with a
     local TVB, the pilot site) → 0 inside the territory, **null outside** (renormalised away, never a fake 0).
   - `presence`: PARTIAL extraction (WFS page limit) → a feature adds evidence where it exists; absence is
     **unknown** (null), so truncation can't paint false zeros.
2. **Normalise per layer, combine per criterion.** Raw metric per cell → within-layer midrank percentile
   (0 stays 0, as in the pilot) → criterion = weighted mean of the layers that cover the cell, renormalised
   on the weight actually covered. A criterion is published only if ≥ 35 % of its weight covers the cell.
3. **Give every criterion a continuous regional backbone**, so cells differ even without a designation:
   naturalness (1 − built fraction), river density and water-body state, built-up growth 2006 → 2025, etc.
4. **"Hits": count and keep the evidence.** Each cell stores `layer_hits` (layers intersected, with counts)
   and per-criterion evidence rows `{sourceId, year, metric, value, unit}`, which the map's existing panel shows.
5. **Keep the pilot as the gold standard.** Inside FR2502014 the original hedge/woodland V and D are kept as
   a high-weight territorial layer. The regional V must rank the pilot cells consistently with the pilot V
   (Spearman correlation reported in the audit).
6. **Honesty labels unchanged.** O becomes "documented action opportunity" (SPRB, ORE, SRCE priority
   actions, priority continuities, PNR, landscape plans), explicitly **not** land availability or consent.

## 3. Layer → criterion mapping (initial weights, editable in `layer_scoring.json`)

**V: ecological value / recognised natural heritage**
ZNIEFF 1 (3) · ZNIEFF 2 (1.5) · Natura 2000 ZSC (2) · ZPS (1.5) · APB (2.5) · RNN (3) · RNR (2.5) · Ramsar (1.5) ·
protection forest (1.5) · PNR (0.5) · water surfaces BD Topage (1) · wetland surveys (0.5) · major beds with fish
stakes (1, by class) · naturalness = 1 − built 2025 (2, continuous backbone) · SRCE reservoirs (1.5, presence) ·
SRCE corridors BN/HN (1, presence) · plain biodiversity sectors 14-50-61 (1) · grassland islets 2013 27-76 (1) ·
Natura 2000 habitats eastern Normandy (1, presence) · local TVB reservoirs (Lieuvin, Lisieux, Mont-Saint-Michel,
Vire au Noireau, Côte Ouest Centre Manche, PETR: 1–1.5, territorial) · pilot hedges+woodland V (4, territorial FR2502014).

**D: degradation / restoration need**
built-up growth 2006→2025 (3) · river water bodies in poor ecological state (2.5, attribute class) · groundwater
bodies in poor chemical state (1) · nitrate vulnerable zone (1) · 6PAR reinforced action zones (0.5) · water
shortage alert zones (0.5) · land-cover change 2012-2018 (1, presence) · flow obstacles from local TVBs (1, territorial)
· pilot hedge loss D (4, territorial FR2502014).

**P: anthropogenic pressure**
built 2025 (3.5) · OSM roads (3) · ICPE (2) · OSM stops (1) · rail (0.5) · wind visual saturation (0.5) ·
mining hazards (0.5) · PPRT (0.5) · quarry deposits of national/regional interest (0.5).

**O: documented action opportunity**
Potential sectors to restore biodiversity SPRB (3) · ORE (2) · SRCE priority actions, point (1) and surface (1.5) ·
priority continuities 27-76 / HN (2) · SRCE sectors of interest BN (1) · local TVB corridors and corridor breaks
(1–1.5, territorial) · PNR (0.5) · landscape plans (0.5) · Grand Site operations (0.5).

Excluded, with the reason recorded: duplicates (same data as GeoJSON/GPKG/SHP/ZIP, API + file), administrative
perimeters (SCoT, PCAET, ANAH, OPAH, DTA communes…), energy/mobility services (bike rental, car pooling,
boilers), urban-only Nature en Ville Calvados (urban areas of one department, 1.6 M polygons), slopes/geothermal/
wetland predisposition layers with ≤ 8 % extent (truncated to one corner of the region).

## 4. Implementation steps

1. `layer_scoring.json`: role, criterion, weight, aggregation, coverage, attribute rules per layer.
2. `multilayer_score.py`:
   - load the existing 1 km² cells (geometry, pilot V/D) and the boundary;
   - build territory masks (departments from the commune layer, EPCI hulls for local TVBs, FR2502014);
   - per layer: read the gz chunks, reproject to EPSG:2154, vectorised STRtree intersection with the cells,
     area / length / count / attribute-weighted area per cell;
   - percentile per layer, weighted combination per criterion, coverage threshold;
   - write V, D, P, O, `layer_hits`, evidence, methods, data_catalog (used layers), audit block.
3. Re-run `complete_region.py` (graph, corridors, ILP scenarios, Monte-Carlo sensitivity) on the new criteria.
4. Audit (`readiness.json` + `summary.json.scoring_audit`): per criterion, the covered cells, distinct values,
   share of the modal value, quantiles, Spearman vs pilot V/D, and eligible cells. **Acceptance:** V, D, P, O
   each cover ≥ 95 % of cells; no criterion has > 60 % of cells on one value; eligible cells ≥ 50 %;
   pilot V correlation > 0.3.
5. Tests: `tests/normandie/test_multilayer.py` for the percentile rules, coverage classes and renormalisation.

## 5. Results (build of 2026-11-11)

| | before | after |
|---|---|---|
| cells with V / D / P / O | 145 / 145 / 30,850 / 0 | 30,850 for each |
| cells with all four criteria | 0 | 30,850 |
| eligible for ranking (V ≥ 10) | 145 | 27,765 (90 %) |
| layers feeding the scores | 3 (+ pilot hedges) | 74 sources in 78 roles (44 V, 9 D, 9 P, 15 O, +2 pilot) |
| distinct values per criterion | P mostly 0 | ≈ 9,600–9,900; largest single value ≤ 4 % of cells |
| corridors | 9 (pilot only) | 15 between 1,123 regional cores (V ≥ 85) |
| ILP scenarios | 5 on 145 cells | 5 on the whole region, all OPTIMAL |
| Monte-Carlo (300 runs, ±20 %) | on 145 cells | top-20 Jaccard 0.86, rank correlation 0.996 |

Acceptance checks: all four pass. Agreement with the pilot inside FR2502014: Spearman V 0.53, D 0.28.
**Independent check** (regional layers only, without the pilot layer): V −0.04, D −0.03. The regional layers
do not reproduce the fine hedge/woodland structure of the pilot: no regional hedge or woodland inventory exists in
the catalogue. Adding one (e.g. BD Haie / BD Forêt v2) is the most valuable next data step.

Other fixes made along the way:
- `regional_model/connectivity.py` uses `habitat_ha` (area × V/100) for patch size when present, so corridors exist
  outside the pilot; `complete_region.py` reads `core_threshold` from `regional_config.json` (85 regionally).
- `regional_model/optimisation.py`: exact candidate reduction for site-count budgets (top-B cells + corridor cells)
  and a warm start from the greedy baseline; the three site scenarios were "Not Solved" in 20 s with 27,765 binaries.
- The "continuités prioritaires 27-76" layer has a mask polygon covering all of Haute-Normandie: only `EnjeuxInte = 1`
  is scored. O remains higher in Eure / Seine-Maritime (mean ≈ 61 vs 37–45) because that layer still covers about half of the former region.

Re-run: `.venv-normandie/bin/python tools/normandie/multilayer_score.py` (≈ 10 min); edit weights in
`tools/normandie/layer_scoring.json`. Previous data: `backups/normandie_before_multilayer_20261111_0039/`.

## 6. Limits that stay explicit
- Weights are expert defaults, documented and editable, not calibrated on field outcomes; the Monte-Carlo
  sensitivity (±20 %) quantifies preference uncertainty.
- Display chunks are simplified at 30 m: fine for 1 km² fractions, not for parcel-level decisions.
- Designations (ZNIEFF, Natura 2000) measure recognised value, not habitat quality on the ground.
- "Presence" layers can only raise a cell; their absence never lowers it.
