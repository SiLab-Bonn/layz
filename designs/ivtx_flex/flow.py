# iVTX flex (Andreas Ulm): the 45 cm flex cable from the RDL ladder (iVTX1) to the DAQ's
# connector (J1). The full flow, from KiCad's DRC and schematic parity to SI and power.
#
#   layz run designs/ivtx_flex         (the HyperLynx targets: on juno or jupiter)
#
# The targets run in this file's order; setup names the inputs: Andreas' KiCad board and schematic,
# copied from /users/aulm/ivtx/Flex on every run.

import shutil
from pathlib import Path

from layz.drc import analysis as drc_analysis
from layz.drc import run as drc_run
from layz.flow import target
from layz.gds2hyp import convert as gds2hyp
from layz.hyperlynx import analysis, plots, run
from layz.hyperlynx import setup as hyperlynx
from layz.lvs import analysis as lvs_analysis
from layz.lvs import run as lvs_run

RESULTS = Path("results/ivtx_flex")


@target
def setup():
    """The inputs: Andreas' latest KiCad board (its stackup inside) and schematic, copied from
    /users/aulm/ivtx/Flex, and his HyperLynx project and models; HyperLynx's writable overlay."""
    global LAYOUT, SCHEMATIC, BOARD
    project = Path("/users/aulm/HyperLynx/simulations/Flex")

    # his KiCad board and schematic, copied in on every run; the schematic under the board's
    # name, as KiCad's schematic parity looks for it beside the board
    andreas = Path("/users/aulm/ivtx/Flex")
    kicad = RESULTS / "setup" / "kicad"
    kicad.mkdir(parents=True, exist_ok=True)
    pcb = max(andreas.glob("*.kicad_pcb"), key=lambda f: f.stat().st_mtime)
    LAYOUT = Path(shutil.copy2(pcb, kicad))
    SCHEMATIC = Path(shutil.copy2(max(andreas.glob("*.kicad_sch"), key=lambda f: f.stat().st_mtime), kicad / f"{pcb.stem}.kicad_sch"))
    for f in andreas.glob(f"{pcb.stem}.kicad_pro"):
        shutil.copy2(f, kicad)
    BOARD = RESULTS / "board" / f"{pcb.stem}.hyp"  # his HyperLynx project goes with the board's name

    # his HyperLynx project next to the board: VRMs, DC sinks, pin models set in the GUI; the
    # SPICE driver and receiver of the data links (the ladder's)
    BOARD.parent.mkdir(parents=True, exist_ok=True)
    for suffix in (".bud", ".bbd", ".pjh"):
        if (project / f"{pcb.stem}{suffix}").exists():
            shutil.copy2(project / f"{pcb.stem}{suffix}", BOARD.parent)
    shutil.copy2("/users/aulm/iVTX_transmisstion_line/fast_drv.sp", BOARD.parent / "fast_drv.sp")
    shutil.copy2("/users/aulm/iVTX_transmisstion_line/fast_rcv.sp.txt", BOARD.parent / "fast_rcv.sp")
    hyperlynx.prepare()


@target
def drc():
    """KiCad's DRC of the flex, with the rules in its board."""
    checked = drc_run.board(LAYOUT, RESULTS / "drc", refill_zones=True, all_track_errors=False)
    drc_analysis.violations(checked, max_violations=0, out=checked / "violations.csv")


@target
def lvs():
    """KiCad's schematic parity of the flex: footprints and nets against flex.kicad_sch, and
    unconnected copper."""
    checked = lvs_run.board(LAYOUT, RESULTS / "lvs", refill_zones=True)
    lvs_analysis.parity(checked, out=checked / "summary.csv")


@target
def board():
    """The board for HyperLynx (KiCad's exporter), its signal nets (up to 0.3 mm wide) as traces;
    GND and +3V0 stay pours. Then what HyperLynx sees in it (stackup, nets and
    lengths, VRMs, modelled pins), and the pins their net's copper doesn't reach."""
    gds2hyp.hyp(LAYOUT, BOARD, stack=None, refill=True, traces="auto", trace_max_width=0.3)

    # what HyperLynx sees in it: stackup, nets with their lengths, VRMs, modelled pins
    # (info/info.json); pins their net's copper doesn't reach (more than 25 um away), and copper
    # on no net
    run.info(BOARD, RESULTS / "board" / "info", license="HyperLynx SI/PI")
    analysis.connectivity(BOARD, tolerance_m=25e-6, nets=None, out=RESULTS / "board" / "connectivity.csv")


@target
def dc():
    """DC of the ladder's 3 V supply over the flex: +3V0 from the connector to the ladder at 12 A
    (four chips at 3 A), and its GND return; resistance, drop, current density; drop against 5 %."""
    out = RESULTS / "dc"
    # the supply, defined here (the board's HyperLynx project has none): 3.0 V at the connector's
    # +3V0 pins, referenced to GND beside them; the load at the ladder's supply pin
    supply = run.dc(BOARD, out / "supply", license="HyperLynx SI/PI", nets=["+3V0"], include_ref=True, vrms={"+3V0": {"voltage": 3.0, "pins": ["J1.2", "J1.4", "J1.6", "J1.8", "J1.10"], "ref": ["J1.9"]}}, sinks={"+3V0": {"pins": ["iVTX1.1"], "resistance": 1e6}}, vrm_references={}, sink_currents={"+3V0": 12.0}, max_voltage_drop=5.0, max_current_density=1.5e7, max_via_current=1.0, return_from=None, return_vrm_type="simple", return_sink_resistance=1e6)
    # the return, re-solved as the supply with the currents the first run measured (HyperLynx
    # maps the loss of supply nets only)
    ret = run.dc(BOARD, out / "return", license="HyperLynx SI/PI", nets=["+3V0"], include_ref=True, vrms={"+3V0": {"voltage": 3.0, "pins": ["J1.2", "J1.4", "J1.6", "J1.8", "J1.10"], "ref": ["J1.9"]}}, sinks={"+3V0": {"pins": ["iVTX1.1"], "resistance": 1e6}}, vrm_references={}, sink_currents={}, max_voltage_drop=5.0, max_current_density=1.5e7, max_via_current=1.0, return_from=supply / "ports.csv", return_vrm_type="simple", return_sink_resistance=1e6)
    analysis.dc_table(supply, ret, out=out / "dc_table.csv")
    analysis.dc_drop(supply, max_drop=0.05, out=out / "dc_drop.csv")
    analysis.current_density(supply, max_density=1.5e7, out=out / "current_density_supply.csv")
    analysis.current_density(ret, max_density=1.5e7, out=out / "current_density_return.csv")
    plots.plot_dc(supply, out, ret)


@target
def si():
    """Chip 4's data pair (DATA_CHIP_4, ladder to connector over the 45 cm flex) at 160 Mb/s
    PRBS7: eye with ideal lines, eye with loss, crosstalk and jitter, and the crosstalk from
    CLK and GPIO_4 onto it, quiet."""
    board = BOARD
    out = RESULTS / "si"

    # eye with ideal lines: lossless, smooth, no jitter, no coupling
    ideal = run.si(
        board,
        out / "eye_ideal",
        license="HyperLynx SI/PI",
        net="DATA_CHIP_4_N",
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
        net="DATA_CHIP_4_N",
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

    # chip 4's data pair quiet (its pins have no model in the project: passive) while CLK (from the
    # connector) and GPIO_4 (from the ladder) switch as an 80 MHz clock, with HyperLynx's stock
    # IBIS CMOS driver and receivers
    xt = run.si(
        board,
        out / "crosstalk",
        license="HyperLynx SI/PI",
        net="DATA_CHIP_4_N",
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
        driver_states={},
        aggressors=[{"driver": "J1.36", "receivers": ["iVTX1.18"], "lib": "modvsez.ibs", "device": "MODvsEZIBIS", "model": "3"}, {"driver": "iVTX1.17", "receivers": ["J1.32"], "lib": "modvsez.ibs", "device": "MODvsEZIBIS", "model": "3"}],
    )

    # at the receiver (the connector, J1): eye at least 200 mV and 0.7 UI, crosstalk at most 100 mV p-p (first
    # guesses, to agree on); eyes measured after 4 UI, height within +-5 % UI of the centre,
    # rise and fall 20-80 %; crosstalk after the first 10 % of the run
    analysis.eyes([ideal, real], min_height=0.2, min_width_ui=0.7, at="J1", skip_ui=4, centre_window=0.05, edge_levels=(0.2, 0.8), out=out / "eyes.csv")
    analysis.crosstalk(xt, max_noise=0.1, at="J1", settle=0.1, out=out / "crosstalk.csv")
    plots.plot_si([ideal, real, xt], out, skip_ui=4, centre_window=0.05, edge_levels=(0.2, 0.8), settle=0.1)


@target
def sparams():
    """4-port S-parameters of chip 4's data pair (P, N at the ladder, then at the connector);
    insertion and return loss at its Nyquist frequency, 80 MHz."""
    out = RESULTS / "sparams"
    pair = run.sparam(BOARD, out / "data4", license="HyperLynx SI/PI", pins=["iVTX1.15", "iVTX1.16", "J1.29", "J1.31"], fmin=1e6, fmax=5e9, sweep="adaptive", steps=500, steps_per_decade=100, tolerance="medium", reference_impedance=50.0, lossy=True, roughness=True, trapezoid=True, nonfunctional_pads=False)
    # SDD21 at least -3 dB, SDD11 at most -10 dB (first guesses, to agree on)
    analysis.sparams(pair, at_hz=80e6, min_sdd21_db=-3.0, max_sdd11_db=-10.0, out=out / "sparams.csv")
    plots.plot_sparam(pair, out)
