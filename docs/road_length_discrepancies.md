# Road length discrepancies

`length_meters` / `expected_travel_time_seconds` are **unchanged** from the committed config. They were never derived from geometry. This report documents how far apart they are. **Nothing here has been recalibrated**; fixing it changes routing costs and requires re-running the experiments.

Ratio = declared length / geometry length (1.0 would be consistent).

## A. The 15 original discrepancies (declared vs the old hand-drawn geometry, ratio outside 0.9-2.5)

These were present before this calibration. They are documented here, not fixed.

| Road | Declared m | Old geometry m | Old ratio | New OSM geometry m | New ratio |
|---|---|---|---|---|---|
| vitap-road-academic-lot-to-mh1 | 50 | 106 | 0.47 | 63 | 0.79 |
| vitap-road-academic-lot-to-library | 140 | 275 | 0.51 | 143 | 0.98 |
| vitap-road-academic-lot-to-cb | 175 | 334 | 0.52 | 219 | 0.80 |
| vitap-road-academic-lot-to-ap2 | 380 | 693 | 0.55 | removed (destination removed) | n/a |
| vitap-road-academic-lot-to-ab2 | 310 | 487 | 0.64 | 409 | 0.76 |
| vitap-road-hostel-lot-to-food-street | 230 | 339 | 0.68 | 696 | 0.33 |
| vitap-road-overflow-to-ab2 | 220 | 309 | 0.71 | 308 | 0.71 |
| vitap-road-admin-lot-to-cb | 200 | 275 | 0.73 | 269 | 0.74 |
| vitap-road-sports-lot-to-sports | 280 | 377 | 0.74 | 543 | 0.52 |
| vitap-road-academic-lot-to-sports | 360 | 482 | 0.75 | 354 | 1.02 |
| vitap-road-admin-lot-to-library | 180 | 232 | 0.78 | 295 | 0.61 |
| vitap-road-sports-lot-to-lh2 | 250 | 316 | 0.79 | 401 | 0.62 |
| vitap-road-sports-lot-to-ab2 | 420 | 509 | 0.83 | 716 | 0.59 |
| vitap-road-sports-lot-to-lh1 | 180 | 218 | 0.83 | 406 | 0.44 |
| vitap-road-hostel-lot-to-mh2 | 95 | 108 | 0.88 | 225 | 0.42 |

## B. All 38 drawn roads against the new OSM geometry

| Road | Mode | Declared m | New geometry m | Ratio | Longest open-ground gap (m) |
|---|---|---|---|---|---|
| vitap-road-main-gate-to-overflow | drive | 220 | 37 | 5.99 | 7 |
| vitap-road-main-gate-to-admin-lot | drive | 480 | 416 | 1.15 | 53 (!) |
| vitap-road-main-gate-to-academic-lot | drive | 620 | 363 | 1.71 | 6 |
| vitap-road-main-gate-to-hostel-lot | drive | 720 | 516 | 1.40 | 4 |
| vitap-road-main-gate-to-sports-lot | drive | 870 | 814 | 1.07 | 86 (!) |
| vitap-road-visitor-gate-to-academic-lot | drive | 130 | 160 | 0.81 | 6 |
| vitap-road-visitor-gate-to-admin-lot | drive | 280 | 172 | 1.62 | 53 (!) |
| vitap-road-visitor-gate-to-hostel-lot | drive | 320 | 318 | 1.01 | 5 |
| vitap-road-visitor-gate-to-overflow | drive | 420 | 458 | 0.92 | 7 |
| vitap-road-overflow-to-ab1 | walk | 110 | 323 | 0.34 | 7 |
| vitap-road-overflow-to-ab2 | walk | 220 | 308 | 0.71 | 7 |
| vitap-road-admin-lot-to-ab1 | walk | 130 | 307 | 0.42 | 49 (!) |
| vitap-road-admin-lot-to-cb | walk | 200 | 269 | 0.74 | 49 (!) |
| vitap-road-admin-lot-to-library | walk | 180 | 295 | 0.61 | 49 (!) |
| vitap-road-admin-lot-to-mh1 | walk | 140 | 274 | 0.51 | 49 (!) |
| vitap-road-academic-lot-to-ab1 | walk | 200 | 273 | 0.73 | 6 |
| vitap-road-academic-lot-to-ab2 | walk | 310 | 409 | 0.76 | 6 |
| vitap-road-academic-lot-to-cb | walk | 175 | 219 | 0.80 | 6 |
| vitap-road-academic-lot-to-library | walk | 140 | 143 | 0.98 | 19 |
| vitap-road-academic-lot-to-sports | walk | 360 | 354 | 1.02 | 24 |
| vitap-road-academic-lot-to-mh1 | walk | 50 | 63 | 0.79 | 6 |
| vitap-road-sports-lot-to-sports | walk | 280 | 543 | 0.52 | 86 (!) |
| vitap-road-sports-lot-to-ab2 | walk | 420 | 716 | 0.59 | 86 (!) |
| vitap-road-sports-lot-to-lh1 | walk | 180 | 406 | 0.44 | 86 (!) |
| vitap-road-sports-lot-to-lh2 | walk | 250 | 401 | 0.62 | 86 (!) |
| vitap-road-hostel-lot-to-mh1 | walk | 200 | 284 | 0.70 | 6 |
| vitap-road-hostel-lot-to-mh5 | walk | 175 | 270 | 0.65 | 4 |
| vitap-road-hostel-lot-to-mh2-food | walk | 110 | 252 | 0.44 | 9 |
| vitap-road-hostel-lot-to-mh2 | walk | 95 | 225 | 0.42 | 5 |
| vitap-road-hostel-lot-to-mh7 | walk | 80 | 86 | 0.93 | 19 |
| vitap-road-hostel-lot-to-mh3 | walk | 150 | 253 | 0.59 | 4 |
| vitap-road-hostel-lot-to-mh4 | walk | 210 | 224 | 0.94 | 4 |
| vitap-road-hostel-lot-to-mh6 | walk | 175 | 292 | 0.60 | 18 |
| vitap-road-hostel-lot-to-food-street | walk | 230 | 696 | 0.33 | 9 |
| vitap-road-hostel-lot-to-lh1 | walk | 580 | 718 | 0.81 | 9 |
| vitap-road-hostel-lot-to-lh2 | walk | 640 | 712 | 0.90 | 7 |
| vitap-road-sports-lot-to-lh3 | walk | 304 | 304 | 1.00 | 86 (!) |
| vitap-road-hostel-lot-to-lh3 | walk | 540 | 540 | 1.00 | 4 |

New roads (no earlier value exists): vitap-road-sports-lot-to-lh3, vitap-road-hostel-lot-to-lh3. Their length/time/edge weights are derived from the OSM geometry (0.8 s per metre, the convention of the existing walk roads), so their ratio is 1.00 by construction. They are the only weights not carried over from v3.

(!) = more than 30 m of open ground between a node (or building wall) and the nearest mapped road; expected for approximate nodes. Building interiors are not counted as gaps.
