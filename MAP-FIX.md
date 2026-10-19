# Map startup fix and 3D heat colours

The original MapLibre 5.6.2 bundle does not export supported(). The call occurred outside the exception handler and prevented both the map and SVG fallback from starting. The corrected code checks for the Map constructor and catches WebGL initialization errors.

The heat palette is enabled by default. Click 3D to show score columns; the thermometer button switches heat/green palettes. Height is score × 8 metres for visualization, NOT measured terrain elevation. Grey indicates missing data. All existing data and analytical methods are unchanged.

## Start on macOS
Extract this complete project into a new folder. From its Renatura-Normandie folder:

```sh
python3 -m http.server 8081 --directory dist
```

Open http://localhost:8081 . A new port avoids the previous service-worker cache. The included data is ready; no pipeline rebuild is needed. To regenerate analysis later, use bash run.sh.

## Validation
12 JavaScript tests passed, including two new mocked map regression tests. Existing DOM smoke suite: 17 assertions passed. These tests do not validate actual GPU rendering or physical Safari/iPad performance. The hosted site has not been updated by this patch.
