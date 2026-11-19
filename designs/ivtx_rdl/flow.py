# iVTX RDL ladder (obelix1 chips on the Uni Bonn RDL, Andreas Ulm): HyperLynx SI/PI flow.
#
# Run on a machine with HyperLynx (juno, jupiter), from the repo:
#   layz hyp -d ivtx_rdl                 list the targets
#   layz hyp -d ivtx_rdl dc si           run some, by name
#   layz hyp -d ivtx_rdl all             run them all, in this file's order
# Each target names its own inputs, runs HyperLynx, checks the results against its limits and
# plots them, all in results/ivtx_rdl/<target>/.

import shutil
from pathlib import Path

from layz.gds2hyp import convert as gds2hyp
from layz.hyperlynx import analysis, plots, run, setup as hyperlynx, target


@target
def setup():
    """HyperLynx's overlay, and the board: Andreas' KiCad export with its 17 signal nets as
    traces, plus his HyperLynx project and models."""
    hyperlynx.prepare()

    # The export draws every route as a pour, which BoardSim cannot simulate as a line;
    # gds2hyp writes the signal nets (40 um wide) as traces, supplies stay pours.
    out = Path("results/ivtx_rdl/setup")
    out.mkdir(parents=True, exist_ok=True)
    export = Path(__file__).parent / "obelix1_ivtx_ladder_with_nets_v3.1.hyp"
    gds2hyp.main([str(export), "-o", str(out / "obelix1_ivtx_ladder_with_nets_v3.1.hyp")])

    # Andreas' HyperLynx project: VRMs, DC sinks and pin models he set up in the GUI
    project = Path("/users/aulm/HyperLynx/simulations/VTX_Obelix_1/v3.1")
    shutil.copy2(project / "obelix1_ivtx_ladder_with_nets_v3.1.bud", out)
    shutil.copy2(project / "obelix1_ivtx_ladder_with_nets_v3.1.bbd", out)
    shutil.copy2(project / "obelix1_ivtx_ladder_with_nets_v3.1.pjh", out)

    # the SPICE driver and receiver of the data links
    shutil.copy2("/users/aulm/iVTX_transmisstion_line/fast_drv.sp", out / "fast_drv.sp")
    shutil.copy2("/users/aulm/iVTX_transmisstion_line/fast_rcv.sp.txt", out / "fast_rcv.sp")


@target
def info():
    """Stackup, nets with their lengths, VRMs and modelled pins (info/info.json)."""
    board = Path("results/ivtx_rdl/setup/obelix1_ivtx_ladder_with_nets_v3.1.hyp")
    if not board.exists():
        setup()
    run.info(board, Path("results/ivtx_rdl/info"))


@target
def dc():
    """DC drop of /3V_1../3V_4 and their returns, against 5 % (the constraint set in HyperLynx);
    pin voltages, via currents, supply and return loss maps."""
    board = Path("results/ivtx_rdl/setup/obelix1_ivtx_ladder_with_nets_v3.1.hyp")
    if not board.exists():
        setup()
    out = Path("results/ivtx_rdl/dc")

    # the four 3 V rails (PSUB and PWell have VRMs without reference pins)
    supply = run.dc(board, out / "supply", nets=["/3V_1", "/3V_2", "/3V_3", "/3V_4"])

    # HyperLynx maps the loss of supply nets only: the returns, re-solved as the supply with the
    # currents the first run measured, give theirs.
    ret = run.dc(board, out / "return", nets=["/3V_1", "/3V_2", "/3V_3", "/3V_4"],
                 return_from=supply / "ports.csv")

    # supply drop + return rise, at most 5 % of the VRM voltage
    analysis.dc_drop(supply, 0.05, out / "dc_drop.csv")
    plots.plot_dc(supply, out, ret)


@target
def si():
    """The longest data pair, D4 (108 mm), at 160 Mb/s PRBS7: eye with ideal lines, eye with
    loss, crosstalk and jitter, and the crosstalk from ADC_4 and rst onto D4 held low."""
    board = Path("results/ivtx_rdl/setup/obelix1_ivtx_ladder_with_nets_v3.1.hyp")
    if not board.exists():
        setup()
    out = Path("results/ivtx_rdl/si")

    # eye with ideal lines: lossless, smooth, no jitter
    ideal = run.si(board, out / "eye_ideal", net="/D4_N", mode="eye", bitrate=160e6,
                   lossy=False, roughness=False, trapezoid=False)

    # eye with loss, roughness, crosstalk, and jitter: 100 ps rms random, 300 ps at 5 MHz sine
    real = run.si(board, out / "eye_real", net="/D4_N", mode="eye", bitrate=160e6, crosstalk=True,
                  jitter={"Gaussian": 100e-12, "Sine": 300e-12, "SineFreq": 5e6})

    # D4 held low while ADC_4 (95 um away, 25 mm) and rst (100 um, 26 mm) switch at 80 MHz,
    # with HyperLynx's stock IBIS CMOS driver and receivers
    xt = run.si(board, out / "crosstalk", net="/D4_N", mode="osc", bitrate=160e6, stop_s=200e-9,
                crosstalk=True, victim_quiet=True,
                aggressors=[{"driver": "V4.114", "receivers": ["VTX2.114"]},
                            {"driver": "VTX2.100", "receivers": ["V1.100", "V2.100", "V3.100", "V4.100"]}])

    # at the receiver (VTX2): eye at least 200 mV and 0.7 UI, crosstalk at most 100 mV p-p
    # (first guesses, to agree on)
    analysis.eyes([ideal, real], 0.2, 0.7, out / "eyes.csv", at="VTX2")
    analysis.crosstalk(xt, 0.1, out / "crosstalk.csv", at="VTX2")
    plots.plot_si([ideal, real, xt], out)


@target
def sparams():
    """4-port S-parameters of D4 (P, N at the driver, then at the receiver); insertion and
    return loss at its Nyquist frequency, 80 MHz."""
    board = Path("results/ivtx_rdl/setup/obelix1_ivtx_ladder_with_nets_v3.1.hyp")
    if not board.exists():
        setup()
    out = Path("results/ivtx_rdl/sparams")

    d4 = run.sparam(board, out / "d4", pins=["V4.101", "V4.102", "VTX2.107", "VTX2.108"])

    # SDD21 at least -3 dB, SDD11 at most -10 dB (first guesses, to agree on)
    analysis.sparams(d4, 80e6, -3.0, -10.0, out / "sparams.csv")
    plots.plot_sparam(d4, out)
