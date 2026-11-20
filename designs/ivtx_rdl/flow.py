# iVTX RDL ladder (obelix1 chips on the Uni Bonn RDL, Andreas Ulm): the full flow, from the
# GDS's design rules and connectivity to SI and power.
#
# Run from the repo (the HyperLynx targets on a machine with HyperLynx: juno, jupiter):
#   layz run --design designs/ivtx_rdl              every target, in this file's order
#   layz run --design ivtx_rdl drc lvs              some, by name
#   layz run --design ivtx_rdl --list               the targets
#   layz run --design ivtx_rdl -k                   on past a failing target
# Each target names its own inputs and every setting it uses (layz.drc.run, layz.lvs.run,
# layz.hyperlynx.run document them), runs, checks the results against its limits and plots
# them, all in results/ivtx_rdl/<target>/.

import shutil
from pathlib import Path

from layz import stack
from layz.drc import analysis as drc_analysis
from layz.drc import run as drc_run
from layz.flow import target
from layz.gds2hyp import convert as gds2hyp
from layz.gds2hyp import gds as gds_hyp
from layz.hyperlynx import analysis, plots, run
from layz.hyperlynx import setup as hyperlynx
from layz.lvs import analysis as lvs_analysis
from layz.lvs import run as lvs_run

HERE = Path(__file__).parent
GDS = HERE / "obelix1_ivtx_ladder_v2.gds"
SCHEMATIC = HERE / "obelix1_ivtx_ladder_f.kicad_sch"


@target
def drc():
    """The GDS against the Uni Bonn RDL's design rules (gdscheck, tech/uni-bonn-rdl)."""
    checked = drc_run.drc(GDS, Path("results/ivtx_rdl/drc"), kit="uni-bonn-rdl", suite="main", topcell=None, tile=20000.0)
    drc_analysis.violations(checked, max_violations=0, out=checked / "violations.csv")


@target
def lvs():
    """The GDS's nets, named by its labels on the pin layers (6/1, 3/1, 8/1, 68/1), against the
    schematic."""
    checked = lvs_run.lvs(GDS, Path("results/ivtx_rdl/lvs"), stack="uni-bonn-rdl", schematic=SCHEMATIC)
    lvs_analysis.findings(checked, out=checked / "summary.csv")


@target
def board():
    """The HyperLynx board straight from the GDS (no KiCad), its nets and pins from the GDS's
    labels. Stops until the GDS has a net label on every net: its labels are on 80/7 (notes)
    today, not on the pin layers. The targets below still use Andreas' KiCad export."""
    out = Path("results/ivtx_rdl/board")
    out.mkdir(parents=True, exist_ok=True)
    hyp = out / "obelix1_ivtx_ladder_v2.hyp"
    gds_hyp.write_hyp(GDS, stack.load("uni-bonn-rdl"), hyp, drill_shrink_um=10.0)
    gds2hyp.traces_pass(hyp, "auto", 0.08)


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
    gds2hyp.main([str(export), "-o", str(out / "obelix1_ivtx_ladder_with_nets_v3.1.hyp"), "--traces", "auto", "--trace-max-width", "0.08"])

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
    """Stackup, nets with their lengths, VRMs and modelled pins (info/info.json); pins their
    net's copper doesn't reach, and copper on no net."""
    board = Path("results/ivtx_rdl/setup/obelix1_ivtx_ladder_with_nets_v3.1.hyp")
    if not board.exists():
        setup()
    run.info(board, Path("results/ivtx_rdl/info"), license="HyperLynx SI/PI")

    # pins their net's copper doesn't reach (more than 25 um away), and copper on no net
    analysis.connectivity(board, tolerance_m=25e-6, nets=None, out=Path("results/ivtx_rdl/info/connectivity.csv"))


@target
def dc():
    """DC of the four chips' 3 V rails at 3 A each and their returns: per net the resistance to
    each pin, drop, current density; drop against 5 % (the constraint set in HyperLynx); pin
    voltages, via currents, loss and current maps. (PSUB and PWell: their VRMs have no reference
    pin, and HyperLynx wants one shared with every chip they feed; how to set that up is open.)"""
    board = Path("results/ivtx_rdl/setup/obelix1_ivtx_ladder_with_nets_v3.1.hyp")
    if not board.exists():
        setup()
    out = Path("results/ivtx_rdl/dc")

    # the four 3 V rails, one per chip, at 3 A each, with their returns; HyperLynx's report flags
    # more than 5 % drop, 1.5e7 A/m^2 and 1 A per via
    supply = run.dc(board, out / "supply", license="HyperLynx SI/PI", nets=["/3V_1", "/3V_2", "/3V_3", "/3V_4"], include_ref=True, vrm_references={}, sink_currents={"/3V_1": 3.0, "/3V_2": 3.0, "/3V_3": 3.0, "/3V_4": 3.0}, max_voltage_drop=5.0, max_current_density=1.5e7, max_via_current=1.0, return_from=None, return_vrm_type="simple", return_sink_resistance=1e6)

    # HyperLynx maps the loss of supply nets only: the returns, re-solved as the supply with the
    # currents the first run measured as sinks (1 Mohm across each), give theirs
    ret = run.dc(board, out / "return", license="HyperLynx SI/PI", nets=["/3V_1", "/3V_2", "/3V_3", "/3V_4"], include_ref=True, vrm_references={}, sink_currents={}, max_voltage_drop=5.0, max_current_density=1.5e7, max_via_current=1.0, return_from=supply / "ports.csv", return_vrm_type="simple", return_sink_resistance=1e6)

    # per chip and net: resistance VRM -> sink pins, drop over them, current density (median, max)
    analysis.dc_table(supply, ret, out=out / "dc_table.csv")

    # supply drop + return rise, at most 5 % of the VRM voltage
    analysis.dc_drop(supply, max_drop=0.05, out=out / "dc_drop.csv")

    # current density in the copper, and the drop per mm it causes, against 15 A/mm² (the limit
    # set in HyperLynx: a PCB value; thin aluminium takes some 1000 A/mm², to agree on)
    analysis.current_density(supply, max_density=1.5e7, out=out / "current_density_supply.csv")
    analysis.current_density(ret, max_density=1.5e7, out=out / "current_density_return.csv")
    plots.plot_dc(supply, out, ret)


@target
def si():
    """The longest data pair, D4 (108 mm), at 160 Mb/s PRBS7: eye with ideal lines, eye with
    loss, crosstalk and jitter, and the crosstalk from ADC_4 and rst onto D4 held low."""
    board = Path("results/ivtx_rdl/setup/obelix1_ivtx_ladder_with_nets_v3.1.hyp")
    if not board.exists():
        setup()
    out = Path("results/ivtx_rdl/si")

    # eye with ideal lines: lossless, smooth, no jitter, no coupling
    ideal = run.si(
        board,
        out / "eye_ideal",
        license="HyperLynx SI/PI",
        net="/D4_N",
        operation="eye",
        simulator="auto",
        corner="typical",
        probe="pin",
        stimulus_scope="global",
        bit_sequence="prbs",
        prbs_order=7,
        repetitions=4,
        frequency=160e6,
        duty_cycle=50.0,
        initial_state="low",
        stop_s=None,
        step_s=None,
        jitter={"Gaussian": 0.0, "GaussianFreq": 1e6, "Sine": 0.0, "SineFreq": 1e6, "SineInitPhase": 0.0, "Uniform": 0.0, "UniformMean": 0.0, "Distortion": 0.0},
        lossy=False,
        roughness=False,
        trapezoid=False,
        nonfunctional_pads=False,
        crosstalk=False,
        trace_coupling={"enabled": False, "method": "geometric", "threshold": 0.001, "max_distance": 0.5e-3, "min_segment": 0.0127, "horizontal_neighbours": 1, "vertical_neighbours": 1, "nonparallel": False, "self": True},
        area_fill_coupling={"enabled": False, "grid": 0.001016, "search_distance": 0.001016},
        sparameter_coupling={"connector": False, "connector_threshold": -20.0, "package": False, "package_threshold": -20.0, "em": False, "em_threshold": -20.0, "fmin": 1e5, "fmax": 2e10},
        driver_states={},
        aggressors=[],
    )

    # eye with loss, roughness, crosstalk (traces within 0.5 mm, area fills), and jitter:
    # 100 ps rms random, 300 ps at 5 MHz sine
    real = run.si(
        board,
        out / "eye_real",
        license="HyperLynx SI/PI",
        net="/D4_N",
        operation="eye",
        simulator="auto",
        corner="typical",
        probe="pin",
        stimulus_scope="global",
        bit_sequence="prbs",
        prbs_order=7,
        repetitions=4,
        frequency=160e6,
        duty_cycle=50.0,
        initial_state="low",
        stop_s=None,
        step_s=None,
        jitter={"Gaussian": 100e-12, "GaussianFreq": 1e6, "Sine": 300e-12, "SineFreq": 5e6, "SineInitPhase": 0.0, "Uniform": 0.0, "UniformMean": 0.0, "Distortion": 0.0},
        lossy=True,
        roughness=True,
        trapezoid=True,
        nonfunctional_pads=False,
        crosstalk=True,
        trace_coupling={"enabled": True, "method": "geometric", "threshold": 0.001, "max_distance": 0.5e-3, "min_segment": 0.0127, "horizontal_neighbours": 1, "vertical_neighbours": 1, "nonparallel": False, "self": True},
        area_fill_coupling={"enabled": True, "grid": 0.001016, "search_distance": 0.001016},
        sparameter_coupling={"connector": False, "connector_threshold": -20.0, "package": False, "package_threshold": -20.0, "em": False, "em_threshold": -20.0, "fmin": 1e5, "fmax": 2e10},
        driver_states={},
        aggressors=[],
    )

    # D4's drivers held low while ADC_4 (95 um away, 25 mm) and rst (100 um, 26 mm) switch as an
    # 80 MHz clock, with HyperLynx's stock IBIS CMOS driver and receivers
    xt = run.si(
        board,
        out / "crosstalk",
        license="HyperLynx SI/PI",
        net="/D4_N",
        operation="standard",
        simulator="auto",
        corner="typical",
        probe="pin",
        stimulus_scope="global",
        bit_sequence="oscillator",
        prbs_order=7,
        repetitions=1,
        frequency=80e6,
        duty_cycle=50.0,
        initial_state="low",
        stop_s=200e-9,
        step_s=None,
        jitter={"Gaussian": 0.0, "GaussianFreq": 1e6, "Sine": 0.0, "SineFreq": 1e6, "SineInitPhase": 0.0, "Uniform": 0.0, "UniformMean": 0.0, "Distortion": 0.0},
        lossy=True,
        roughness=True,
        trapezoid=True,
        nonfunctional_pads=False,
        crosstalk=True,
        trace_coupling={"enabled": True, "method": "geometric", "threshold": 0.001, "max_distance": 0.5e-3, "min_segment": 0.0127, "horizontal_neighbours": 1, "vertical_neighbours": 1, "nonparallel": False, "self": True},
        area_fill_coupling={"enabled": True, "grid": 0.001016, "search_distance": 0.001016},
        sparameter_coupling={"connector": False, "connector_threshold": -20.0, "package": False, "package_threshold": -20.0, "em": False, "em_threshold": -20.0, "fmin": 1e5, "fmax": 2e10},
        driver_states={"V4.101": "low", "V4.102": "low"},
        aggressors=[{"driver": "V4.114", "receivers": ["VTX2.114"], "lib": "modvsez.ibs", "device": "MODvsEZIBIS", "model": "3"}, {"driver": "VTX2.100", "receivers": ["V1.100", "V2.100", "V3.100", "V4.100"], "lib": "modvsez.ibs", "device": "MODvsEZIBIS", "model": "3"}],
    )

    # at the receiver (VTX2): eye at least 200 mV and 0.7 UI, crosstalk at most 100 mV p-p (first
    # guesses, to agree on); eyes measured after 4 UI, height within +-5 % UI of the centre,
    # rise and fall 20-80 %; crosstalk after the first 10 % of the run
    analysis.eyes([ideal, real], min_height=0.2, min_width_ui=0.7, at="VTX2", skip_ui=4, centre_window=0.05, edge_levels=(0.2, 0.8), out=out / "eyes.csv")
    analysis.crosstalk(xt, max_noise=0.1, at="VTX2", settle=0.1, out=out / "crosstalk.csv")
    plots.plot_si([ideal, real, xt], out, skip_ui=4, centre_window=0.05, edge_levels=(0.2, 0.8), settle=0.1)


@target
def sparams():
    """4-port S-parameters of D4 (P, N at the driver, then at the receiver); insertion and
    return loss at its Nyquist frequency, 80 MHz."""
    board = Path("results/ivtx_rdl/setup/obelix1_ivtx_ladder_with_nets_v3.1.hyp")
    if not board.exists():
        setup()
    out = Path("results/ivtx_rdl/sparams")

    # 1 MHz to 5 GHz, adaptive sweep at medium tolerance, 50 ohm ports, real line models
    d4 = run.sparam(board, out / "d4", license="HyperLynx SI/PI", pins=["V4.101", "V4.102", "VTX2.107", "VTX2.108"], fmin=1e6, fmax=5e9, sweep="adaptive", steps=500, steps_per_decade=100, tolerance="medium", reference_impedance=50.0, lossy=True, roughness=True, trapezoid=True, nonfunctional_pads=False)

    # SDD21 at least -3 dB, SDD11 at most -10 dB (first guesses, to agree on)
    analysis.sparams(d4, at_hz=80e6, min_sdd21_db=-3.0, max_sdd11_db=-10.0, out=out / "sparams.csv")
    plots.plot_sparam(d4, out)
