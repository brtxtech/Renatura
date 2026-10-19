# Scientific and operational methodology

## Study scope

FR2502014 is the official pilot boundary. The same dataset contains three
hedgerow/woodland observation years: 1947, 2010 and 2016. The analytical comparison
uses 2010–2016. The older year is provided as an observed context layer only.

No data have been simulated for the application. Synthetic fixtures exist only
in isolated tests to exercise edge cases. DREAL source geometry is clipped to the
official boundary. Hexagons have 1 km² before clipping. Fragments below 1 ha are
excluded; the omitted surface is exported in summary.json.

Exact duplicate geometries are removed. Invalid geometries are repaired with
Shapely make_valid. CRS is read from each file; a missing CRS fails the build.
Only hedgerow features whose Nature attribute equals `haie` are included.
`CR` and `ZB` features are not counted as standalone hedgerows. Woodland polygons
are unioned within each cell to avoid double-counting overlap.

## Scores

V is the arithmetic mean of two within-pilot midrank percentiles: observed
hedgerow length per hectare and woodland area fraction, both for 2016. This is a
structural proxy, not a biodiversity inventory or habitat-quality measurement.
Zero observed values are assigned zero; positive ties use midranks.

D = 100 × max(0, 1 − hedge_length_2016 / hedge_length_2010). It is null where
hedge_length_2010 is zero. This is net change, so replacement growth can conceal
loss elsewhere in a cell. Woodland succession and source interpretation matter.
The value cannot establish a cause or a species response.

P and O are null. Neither zero nor a simulated value is substituted. Criterion
coverage is available criteria / 4. It is not source-layer completeness, positional
accuracy or a probability of correctness. In this pilot it is 50%.

Default weights are 0.30, 0.30, 0.15, 0.25. The clearly labelled partial mode
renormalises over observed criteria, giving V and D equal effective weights at
defaults. Full-score mode excludes incomplete cells. V < 10 cells are ineligible
for restoration optimisation. Protection priority remains unavailable because
neighbouring pressure is unknown.

## Connectivity graph

Adjacent clipped cells form an undirected graph. Structural cores are connected
components of V≥60 cells. Patches are ranked by observed woodland area. For each
pair of the twelve largest patches, a minimum weighted route between any two
member cells is selected. Disconnected pairs are skipped.

Resistance = centroid distance × (1 + 4 × (1 − mean V / 100)). These constants and
thresholds are assumptions. They have not been calibrated for a species or
validated with movement observations. Betweenness uses these positive distances.
The exported route geometry connects cell centroids and is schematic: it is not
an engineered corridor or a fine-resolution raster least-cost surface.

Connection gain = geometric mean of the two patches' woodland areas, normalised
to 100 for the highest pair in the candidate set. It is not unique habitat area.
The model considers a route completed only if all intermediate cells are restored.
Route geometry and all required cells are exported. Ecological ground-truthing,
resistance calibration and sensitivity to core thresholds remain necessary.

The optional graph report halves resistance on edges incident to a selected
cell. This is explicitly a hypothetical intervention effect and is reported
separately from the optimisation objective.

## Optimisation

Choose binary x_i for candidate planning cells. Choose binary y_p for connections.
For every cell i required by p, y_p ≤ x_i. Also y_p ≥ Σx_i − |p| + 1.
Maximise Σ RP_i x_i + λ Σ gain_p y_p. A site-count, area or proxy resource sum
cannot exceed the chosen limit. Missing-score/low-stake candidates are excluded;
routes requiring an excluded cell cannot earn credit.

Proxy cost is exactly clipped cell area in hectares. Its units are not euros.
This means hectares and proxy modes are numerically equivalent in this release.
Do not invent land-cover multipliers without external justification.

An additive per-cell priority objective with an area constraint favours small
clipped cells. Large gains over naive score order may reflect this mathematical
choice rather than better real-world ecology. Excluding fragments under 1 ha
reduces, but does not remove, this bias. Before operational use, review whole-cell
costs, area-weighted ecological benefit or actual restoration parcels.

The baseline ranks by RP and skips unaffordable cells. All comparisons use the
same candidates, weights and budget. Gain percentage refers to the combined
objective, not an observed biodiversity increase. Baseline objective zero yields
an undefined percentage, displayed as an em dash.

## Sensitivity

1,000 independent offline draws multiply each default weight by Uniform(0.8,1.2)
then normalise the vector. Seed 42. Report top-20 inclusion frequency, 5th/95th rank
percentiles, median rank, mean top-20 Jaccard and correlation of ordinal ranks.
Ties use the site ID for deterministic order. The browser offers 200 analogous
runs with its own documented deterministic PRNG; streams are not identical to
Python. Null P/O weights have no effective influence in partial scoring.

This analysis covers preference uncertainty only. It does not estimate uncertainty
in surveys, land availability, restoration response, data coverage or costs.

## Audit boundaries

The programme checks geometry validity, duplicate IDs, positive costs and budget
feasibility. Numerical tests compare ILP with exhaustive enumeration on small
fixtures and compare Python with browser objectives on the real pilot data.
A reproducibility check reruns analytical outputs against the same raw snapshot.
No field validation, legal site assessment or three-case expert comparison has
been completed. Those are release gates for decision-making beyond exploration.
