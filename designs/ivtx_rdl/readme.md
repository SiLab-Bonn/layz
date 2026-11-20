# ivtx_rdl: iVTX RDL ladder

The full flow of the iVTX RDL ladder (obelix1 chips on the Uni Bonn RDL, Andreas Ulm's design):
the GDS's design rules and connectivity, its HyperLynx board, then DC drop, SI and S-parameters,
all through layz's generic API. `flow.py` reads top to bottom, step by step, like an OpenROAD
flow script; it only names this design's files, nets, pins and aggressors.

```sh
layz run --design designs/ivtx_rdl              # every target, in order (HyperLynx: juno, jupiter)
layz run --design ivtx_rdl drc lvs              # or some, by name
layz run --design ivtx_rdl --list               # the targets
```

`board` writes the HyperLynx board straight from the GDS, and stops until every net there has a
net label on its pin layer (the GDS's labels are on 80/7 today); `lvs` checks no net until then.
The HyperLynx targets use Andreas' KiCad export meanwhile.

Each target names its inputs and limits itself, runs, checks and plots into its folder in
`results/ivtx_rdl/`:

| Target | What | Checks |
| --- | --- | --- |
| `setup` | HyperLynx overlay; the board with its 17 signal routes as traces (from this folder), with Andreas' HyperLynx project (VRMs, DC sinks, driver models) from `/users/aulm` | |
| `info` | stackup, nets with their lengths, VRMs, modelled pins | |
| `dc` | DC drop of the four 3 V rails with their returns; the return re-solved as a supply for its loss map | drop + return rise ≤ 5 % (the HyperLynx constraint) |
| `si` | D4 eye at 160 Mb/s PRBS7, ideal and with loss, roughness, crosstalk and jitter (RJ 100 ps, SJ 300 ps at 5 MHz); D4 held low while ADC_4 and rst switch at 80 MHz | eye ≥ 200 mV, ≥ 0.7 UI; crosstalk ≤ 100 mV p-p |
| `sparams` | 4-port S-parameters of the D4 pair | SDD21 ≥ −3 dB, SDD11 ≤ −10 dB at 80 MHz |

The limits other than the DC drop are first guesses, to be agreed on.

Files:

| File | What |
| --- | --- |
| `obelix1_ivtx_ladder_v2.gds` | the layout |
| `obelix1_ivtx_ladder_f.kicad_sch` | its schematic (`layz lvs --sch`) |
| `obelix1_ivtx_ladder_with_nets_v3.1.hyp` | Andreas' KiCad export, the input of `setup` |
| `kicad_stack.toml` | the stackup typed into KiCad for that export (FR4 placeholders); `layz gds2hyp` of the GDS with it writes the same STACKUP |

Notes from the first runs (November 2026): the export draws every route as pours, which
BoardSim cannot simulate as lines, so `layz gds2hyp` writes the 17 signal nets as traces first; the
stackup is still the KiCad placeholder (FR4, εr 4.5) and needs the polyimide values; the jittered
eye takes several minutes on 50 cores.
