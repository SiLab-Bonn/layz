# uni-bonn-rdl DRC deck

gdscheck PDK for the in-house RDL (maskless lithography), with the layers of asiclab's
`tech/uni-bonn-rdl`: chip pads 68/0, Al M1 1/0, M2 3/0, M3 6/0, polyimide openings V1 2/0,
V2 4/0, pad openings 7/0, outline 70/0. Run it with `layz drc --kit uni-bonn-rdl`.

| Rule | Value |
| --- | --- |
| M1, M2, M3 width, spacing, notch | ≥ 10 µm |
| M1, M2, M3 area (minimum feature 10 × 10 µm) | ≥ 100 µm² |
| V1, V2, pad opening size / spacing (spacing assumed = metal spacing) | ≥ 10 µm |
| V1 by M2, V2 by M2 and M3, pad openings by M3, every side | ≥ 10 µm (pads ≥ 30 × 30 µm) |
| V1 landing on M1 or a chip pad | contained |
| metal density in any 1 × 1 mm window (step 500 µm), inside the outline 70/0 | ≤ 95 % |

Chip pads (68/0) are the chip's and aren't checked. V2 is the 4/0 opening alone (asiclab's tech
has 4/0 AND 5/0; designs draw V2 on 4/0). Suites: `main` (everything), `geometry` (without
density).

Performance: on the obelix1 ladder the M2 and M3 width checks are 98 % of the run
(`layz drc --benchmark`). layz uses a 20 mm merge tile (`--tile`), about 5x faster than 2 mm on
the ladder's long planes; the ladder GDS takes about 35 s (18 threads) and reports 261
violations: V2 enclosure by M2 (52) and M3 (138), density in 19 + 20 windows on M2/M3,
19 notches, 1 width, and 12 at V1 and pad openings.
