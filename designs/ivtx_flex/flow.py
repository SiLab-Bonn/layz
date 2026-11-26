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

RESULTS = Path(__file__).resolve().parents[2] / "results" / "ivtx_flex"  # this clone's results, from wherever it runs

# the data pairs: chip k's DATA_CHIP_k_P/N from the ladder (iVTX1.3k+3, 3k+4) to the connector
# (J1.6k+5, 6k+7), beside its GPIO line (iVTX1.3k+5 -> J1.4k+16); CLK runs beside chip 4's
PAIRS = {f"DATA_CHIP_{k}": {"ladder": [f"iVTX1.{3 * k + 3}", f"iVTX1.{3 * k + 4}"], "connector": [f"J1.{6 * k + 5}", f"J1.{6 * k + 7}"], "gpio": (f"iVTX1.{3 * k + 5}", f"J1.{4 * k + 16}")} for k in (1, 2, 3, 4)}


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
def power_integrity():
    """DC of the ladder's 3 V supply over the flex: +3V0 from the connector to the ladder at 12 A
    (four chips at 3 A), and its GND return; resistance, drop, current density; the maps."""
    out = RESULTS / "power_integrity"
    # the supply, defined here (the board's HyperLynx project has none): 3.0 V at the connector's
    # +3V0 pins, referenced to GND beside them; the load at the ladder's supply pin
    supply = run.dc(BOARD, out / "supply", license="HyperLynx SI/PI", nets=["+3V0"], include_ref=True, vrms={"+3V0": {"voltage": 3.0, "pins": ["J1.2", "J1.4", "J1.6", "J1.8", "J1.10"], "ref": ["J1.9"]}}, sinks={"+3V0": {"pins": ["iVTX1.1"], "resistance": 1e6}}, vrm_references={}, sink_currents={"+3V0": 12.0}, max_voltage_drop=5.0, max_current_density=1.5e7, max_via_current=1.0, return_from=None, return_vrm_type="simple", return_sink_resistance=1e6)
    # the return, re-solved as the supply with the currents the first run measured (HyperLynx
    # maps the loss of supply nets only)
    ret = run.dc(BOARD, out / "return", license="HyperLynx SI/PI", nets=["+3V0"], include_ref=True, vrms={"+3V0": {"voltage": 3.0, "pins": ["J1.2", "J1.4", "J1.6", "J1.8", "J1.10"], "ref": ["J1.9"]}}, sinks={"+3V0": {"pins": ["iVTX1.1"], "resistance": 1e6}}, vrm_references={}, sink_currents={}, max_voltage_drop=5.0, max_current_density=1.5e7, max_via_current=1.0, return_from=supply / "ports.csv", return_vrm_type="simple", return_sink_resistance=1e6)
    analysis.dc_drop(supply, out=out / "dc_drop.csv")
    analysis.dc_table(supply, ret, out=out / "dc_table.csv")
    analysis.current_density([supply, ret], max_density=1.5e7, out=out / "current_density.csv")

    # every pin's current and voltage, and the resistance from the VRM to each sink pin
    analysis.pins([supply, ret], out=out / "pins.csv")
    analysis.resistance(supply, out=out / "resistance.csv")

    # the maps for the viewer: voltage drop from the VRM per rail, current density, via current
    plots.plot_dc(supply, out, ret)


@target
def sparams():
    """4-port S-parameters of each data pair (P, N at the ladder, then at the connector);
    insertion and return loss at its Nyquist frequency, 80 MHz."""
    out = RESULTS / "sparams"
    runs = [run.sparam(BOARD, out / pair, license="HyperLynx SI/PI", pins=p["ladder"] + p["connector"], fmin=1e6, fmax=5e9, sweep="adaptive", steps=500, steps_per_decade=100, tolerance="medium", reference_impedance=50.0, lossy=True, roughness=True, trapezoid=True, nonfunctional_pads=False) for pair, p in PAIRS.items()]
    # SDD21 at least -3 dB, SDD11 at most -10 dB (first guesses, to agree on)
    analysis.sparams(runs, at_hz=80e6, min_sdd21_db=-3.0, max_sdd11_db=-10.0, out=out / "sparams.csv")
    for r in runs:
        plots.plot_sparam(r, out, name=r.name)


@target
def signal_integrity():
    """Each data pair (ladder to connector over the 45 cm flex) at 160 Mb/s PRBS7: its TDR, eye
    with ideal lines, eye with loss, crosstalk and jitter, and the crosstalk from its chip's GPIO
    line (and CLK, beside chip 4's) onto it."""

    # TDR of the pair from its S-parameters (the sparams step): a 50 ps step into each port and
    # each end's pair; distance at v = c/sqrt(eps_eff), eps_eff 3.6 (the dielectric's, to agree on)
    sps = [RESULTS / "sparams" / pair for pair in PAIRS]
    for sp in sps:
        plots.plot_tdr(sp, RESULTS / "signal_integrity", rise_ps=50.0, er_eff=3.6, name=sp.name)
    analysis.tdr(sps, rise_ps=50.0, er_eff=3.6, out=RESULTS / "signal_integrity" / "tdr.csv")
    board = BOARD
    out = RESULTS / "signal_integrity"

    eyes, xts = [], []
    for pair, p in PAIRS.items():
        # eye with ideal lines: lossless, smooth, no jitter, no coupling
        ideal = run.si(
            board,
            out / pair / "eye_ideal",
            license="HyperLynx SI/PI",
            net=f"{pair}_N",
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
            out / pair / "eye_real",
            license="HyperLynx SI/PI",
            net=f"{pair}_N",
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
            out / pair / "crosstalk",
            license="HyperLynx SI/PI",
            net=f"{pair}_N",
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
            aggressors=[{"driver": p["gpio"][0], "receivers": [p["gpio"][1]], "lib": "modvsez.ibs", "device": "MODvsEZIBIS", "model": "3"}] + ([{"driver": "J1.36", "receivers": ["iVTX1.18"], "lib": "modvsez.ibs", "device": "MODvsEZIBIS", "model": "3"}] if pair == "DATA_CHIP_4" else []),
        )
        eyes += [ideal, real]
        xts.append(xt)
        plots.plot_si([ideal, real, xt], out, at="J1", skip_ui=4, centre_window=0.05, edge_levels=(0.2, 0.8), settle=0.1, name=pair)

    # at the receiver (the connector, J1): eye at least 200 mV and 0.7 UI, crosstalk at most 100 mV p-p (first
    # guesses, to agree on); eyes measured after 4 UI, height within +-5 % UI of the centre,
    # rise and fall 20-80 %; crosstalk after the first 10 % of the run
    analysis.eyes(eyes, min_height=0.2, min_width_ui=0.7, at="J1", skip_ui=4, centre_window=0.05, edge_levels=(0.2, 0.8), out=out / "eyes.csv")
    analysis.crosstalk(xts, max_noise=0.1, at="J1", settle=0.1, out=out / "crosstalk.csv")
