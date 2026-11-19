# iVTX RDL ladder (obelix1 chips on the Uni Bonn RDL, Andreas Ulm): HyperLynx SI/PI flow.
#
# Run on a machine with HyperLynx (juno, jupiter), from the repo:
#   layz hyp -d ivtx_rdl                 list the targets
#   layz hyp -d ivtx_rdl dc si           run some, by name
#   layz hyp -d ivtx_rdl all             run them all, in this file's order
# Each target takes the inputs it needs, runs HyperLynx, checks the results against the limits
# below and plots them, all in results/ivtx_rdl/<target>/ ($IVTX_RDL_HL_RUNS for another place).
# The analyses are layz's (layz.hyperlynx); only files, nets, pins and limits are this design's.

import os
import shutil
from pathlib import Path

from layz import gds2hyp
from layz.hyperlynx import analysis, plots, run, setup as hyperlynx, target

###########################################################################
# Inputs, outputs and limits

REPO = Path(__file__).resolve().parents[2]
EXPORT = REPO / "example_files" / "obelix1_ivtx_ladder_with_nets_v3.1.hyp"  # Andreas' KiCad export
# Andreas' HyperLynx project: VRMs, DC sinks and pin models he set up in the GUI (.bud .bbd .pjh)
PROJECT = Path(os.environ.get("IVTX_RDL_HL_PROJECT", "/users/aulm/HyperLynx/simulations/VTX_Obelix_1/v3.1"))
MODELS = {"fast_drv.sp": "/users/aulm/iVTX_transmisstion_line/fast_drv.sp",       # SPICE driver
          "fast_rcv.sp": "/users/aulm/iVTX_transmisstion_line/fast_rcv.sp.txt"}   # and receiver

RESULTS = Path(os.environ.get("IVTX_RDL_HL_RUNS", "results/ivtx_rdl"))
BOARD = RESULTS / "setup" / EXPORT.name

SUPPLIES = ["/3V_1", "/3V_2", "/3V_3", "/3V_4"]  # PSUB and PWell have VRMs without reference pins
BITRATE = 160e6                                  # the data links (D1..D4)
D4_PORTS = ["V4.101", "V4.102", "VTX2.107", "VTX2.108"]  # P, N at the driver, P, N at the receiver
AGGRESSORS = [{"driver": "V4.114", "receivers": ["VTX2.114"]},                          # ADC_4: 95 um, 25 mm
              {"driver": "VTX2.100", "receivers": ["V1.100", "V2.100", "V3.100", "V4.100"]}]  # rst: 100 um, 26 mm

# Limits (the DC drop is the constraint set in HyperLynx; the others are first guesses to agree on)
MAX_DC_DROP = 0.05            # supply drop + return rise, share of the VRM voltage
MIN_EYE_HEIGHT = 0.2          # V, differential at the receiver
MIN_EYE_WIDTH = 0.7           # share of a UI
MAX_CROSSTALK = 0.1           # V peak-to-peak, differential, onto a quiet pair
MIN_SDD21, MAX_SDD11 = -3.0, -10.0   # dB at the Nyquist frequency, BITRATE / 2


###########################################################################
# setup: HyperLynx, and the board with its signal routes as traces

@target
def setup():
    """HyperLynx's overlay, and the board: the export with its 17 signal nets as traces, plus
    Andreas' HyperLynx project and models."""
    hyperlynx.prepare()
    # The export draws every route as a pour, which BoardSim cannot simulate as a line;
    # gds2hyp writes the signal nets (40 um wide) as traces, supplies stay pours.
    BOARD.parent.mkdir(parents=True, exist_ok=True)
    gds2hyp.main([str(EXPORT), "-o", str(BOARD)])
    for ext in (".bud", ".bbd", ".pjh"):
        shutil.copy2(PROJECT / (EXPORT.stem + ext), BOARD.parent)
    for name, src in MODELS.items():
        shutil.copy2(src, BOARD.parent / name)


###########################################################################
# info: what HyperLynx sees

@target
def info():
    """Stackup, nets with their lengths, VRMs and modelled pins (info/info.json)."""
    if not BOARD.exists():
        setup()
    run.info(BOARD, RESULTS / "info")


###########################################################################
# dc: DC drop of the four 3 V rails and their returns

@target
def dc():
    """DC drop of /3V_1../3V_4 and their returns, against MAX_DC_DROP; pin voltages, via
    currents, supply and return loss maps."""
    if not BOARD.exists():
        setup()
    out = RESULTS / "dc"
    supply = run.dc(BOARD, out / "supply", nets=SUPPLIES)
    # HyperLynx maps the loss of supply nets only: the returns, re-solved as the supply with the
    # currents the first run measured, give theirs.
    ret = run.dc(BOARD, out / "return", nets=SUPPLIES, return_from=supply / "ports.csv")
    analysis.dc_drop(supply, MAX_DC_DROP, out / "dc_drop.csv")
    plots.plot_dc(supply, out, ret)


###########################################################################
# si: the eye of the longest data pair, D4 (108 mm), and crosstalk onto it

@target
def si():
    """D4 at 160 Mb/s PRBS7: eye with ideal lines, eye with loss, crosstalk and jitter, and the
    crosstalk from ADC_4 and rst onto D4 held low; against the eye and crosstalk limits."""
    if not BOARD.exists():
        setup()
    out = RESULTS / "si"
    ideal = run.si(BOARD, out / "eye_ideal", net="/D4_N", mode="eye", bitrate=BITRATE,
                   lossy=False, roughness=False, trapezoid=False)
    real = run.si(BOARD, out / "eye_real", net="/D4_N", mode="eye", bitrate=BITRATE, crosstalk=True,
                  jitter={"Gaussian": 100e-12, "Sine": 300e-12, "SineFreq": 5e6})
    # the aggressors get HyperLynx's stock IBIS CMOS driver and receivers, a clock at BITRATE / 2
    xt = run.si(BOARD, out / "crosstalk", net="/D4_N", mode="osc", bitrate=BITRATE, stop_s=200e-9,
                crosstalk=True, victim_quiet=True, aggressors=AGGRESSORS)
    analysis.eyes([ideal, real], MIN_EYE_HEIGHT, MIN_EYE_WIDTH, out / "eyes.csv")
    analysis.crosstalk(xt, MAX_CROSSTALK, out / "crosstalk.csv")
    plots.plot_si([ideal, real, xt], out)


###########################################################################
# sparams: the D4 pair as a 4-port

@target
def sparams():
    """4-port S-parameters of D4 (P, N at the driver, then at the receiver), insertion and
    return loss at the Nyquist frequency against MIN_SDD21 and MAX_SDD11."""
    if not BOARD.exists():
        setup()
    out = RESULTS / "sparams"
    d4 = run.sparam(BOARD, out / "d4", pins=D4_PORTS)
    analysis.sparams(d4, BITRATE / 2, MIN_SDD21, MAX_SDD11, out / "sparams.csv")
    plots.plot_sparam(d4, out)
