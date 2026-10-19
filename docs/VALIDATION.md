# Validation record — 19 October 2026

## Completed

- Real DREAL source archive downloaded and read: 1947, 2010 and 2016 hedgerows
  and woodland, with original projection metadata.
- Official Natura 2000 FR2502014 boundary downloaded and used for clipping.
- Commune names joined from the public administrative API snapshot.
- 280 unique planning cells; 21,510.326 ha represented.
- Official boundary area: 21,510.909 ha; 0.583 ha excluded in fragments under 1 ha.
- 18 structural core components; candidate paths between the 12 largest yield
  66 modelled patch-pair connections.
- Five PuLP/CBC preset solutions returned proven OPTIMAL status.
- 1,000 Monte Carlo runs with fixed seed 42.
- 14 Python unit/integrity tests passed.
- 10 Node numerical/worker tests passed.
- Python and JavaScript objective calculations agree on the real-data presets.
- Small ILP fixtures match exhaustive subset enumeration under all three constraints.
- Browser worker checked on a real-data area-constrained case: feasible, respects
  budget, objective at least as good as its baseline, upper bound not below incumbent.
- 17 DOM smoke assertions passed in jsdom: data loading, 2D fallback polygons,
  ranking, presets, filter behaviour, stale-result invalidation, cell details,
  complete-score exclusion, language switching and page navigation.
- All original frontend JavaScript files passed syntax checks.
- A second full processing run produced byte-identical cells.geojson,
  scenarios.json, sensitivity.json and connectivity.json from the same snapshots.
- Static app payload is approximately 15.21 MB uncompressed, below 30 MB.
  Most bytes are optional historical hedgerow layers.
- More than 3,400 original code lines, excluding vendored MapLibre, generated
  data, documentation and raw source metadata.

## Preset comparison

These are improvements in the model's combined objective, not ecological outcomes.

| Preset | Selected cells | Model objective gain vs naive |
| --- | ---: | ---: |
| Five sites | 5 | 3.27% |
| Twelve sites | 12 | 1.84% |
| Twenty-five sites | 25 | 1.46% |
| 500 hectares | 37 | 166.93% |
| 1,000 proxy units | 50 | 101.84% |

Large area-budget improvements are affected by the additive cell-score objective
and unequal boundary-clipped cell sizes. See methodology before interpretation.

## Not verified / not complete

- No actual browser rendering or visual screenshot review was available in this
  environment; jsdom tests do not test CSS layout or WebGL rendering.
- No physical iPad/Safari performance, memory, battery or offline restart test.
- No measured broadband first-load time or sustained 60 fps claim.
- No full accessibility audit; keyboard/focus/reduced-motion features are implemented.
- No three-case ecological expert validation or field ground-truthing.
- No complete P/O data, full protection index or Normandy-wide assessment.
- No real restoration cost or property-availability validation.

## Suggested acceptance check on the target iPad

1. Open the HTTPS app and verify 280 cells and historical-data notice.
2. Switch 2D/3D, rotate and reset. Inspect a cell and compare raw source values.
3. Load the five-site preset: five orange outlines should appear.
4. Change a weight: previous scenario is marked stale and selected outlines clear.
5. Recompute a custom scenario and export JSON. Verify budget is not exceeded.
6. Disable partial scoring: RP is unavailable; no P/O values are fabricated.
7. Prepare offline layers, close and reopen the PWA in airplane mode.
8. Test portrait/landscape, keyboard navigation, larger text and reduced motion.
