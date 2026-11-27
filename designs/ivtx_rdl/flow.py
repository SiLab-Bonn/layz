# iVTX RDL ladder (obelix1 chips on the Uni Bonn RDL, Andreas Ulm): the full flow, from the
# GDS's design rules and connectivity to SI and power.
#
#   layz run designs/ivtx_rdl          (the HyperLynx targets: on juno or jupiter)
#
# The targets run in this file's order. setup names the inputs; each target after it names
# every setting it uses (layz.drc.run, layz.lvs.run, layz.hyperlynx.run document them), runs,
# checks the results against its limits and plots them, all in RESULTS/<target>/ (this clone's results/ivtx_rdl/).

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

RESULTS = Path(__file__).resolve().parents[2] / "results" / "ivtx_rdl"  # this clone's results, from wherever it runs

# the data pairs: chip k drives D<k>_P/N from its pins .101/.102 to the connector VTX2, beside its
# ADC line (k.114 -> VTX2.110+k); rst runs past all four. (CLK and CMD come from the connector to
# the four chips' coupling capacitors; the HyperLynx project has no models on them yet.)
PAIRS = {f"D{k}": {"driver": [f"V{k}.101", f"V{k}.102"], "receiver": [f"VTX2.{99 + 2 * k}", f"VTX2.{100 + 2 * k}"], "adc": (f"V{k}.114", f"VTX2.{110 + k}")} for k in (1, 2, 3, 4)}

# CLK and CMD: from the connector (VTX2.123/124, .121/122) past the four chips' coupling capacitors
# (C3/C4, C103/C104, ... on CLK; C1/C2, ... on CMD) to their pins k.123/124, k.121/122. The project
# has no models on them: the data pairs' own, fast_drv at the connector, Fast_Rcv at each chip.
# Their S-parameters run to chip 4's capacitors (the farthest), the other branches as stubs.
FAST = {"like": "V1.101"}  # the project's SPICE driver on D1, its ports wired as there
RCV = {"like": "VTX2.101"}  # and its receiver
CHIPS = ["V1-", "V2-", "V3-", "V4-"]  # the chips' waveforms (HyperLynx names them V(V1-123,V1-124))
BUSES = {
    name: {"pin": pin, "driver": [f"VTX2.{pin}", f"VTX2.{pin + 1}"], "chips": [f"V{k}.{pin}" for k in (1, 2, 3, 4)] + [f"V{k}.{pin + 1}" for k in (1, 2, 3, 4)], "far": [f"C{cap}.2", f"C{cap + 1}.2"]}
    for name, pin, cap in (("CLK", 123, 303), ("CMD", 121, 301))
}


@target
def setup():
    """The inputs: Andreas' latest layout and schematic (copied from /users/aulm/ivtx/RDL), the RDL's
    stack, the board HyperLynx simulates, his HyperLynx project and models; HyperLynx's writable
    overlay."""
    global LAYOUT, STACK, SCHEMATIC, BOARD_SOURCE, BOARD
    # Andreas' latest layout and schematic, copied in from his folder on every run
    andreas = Path("/users/aulm/ivtx/RDL")
    inputs = RESULTS / "setup" / "inputs"
    inputs.mkdir(parents=True, exist_ok=True)
    LAYOUT = Path(shutil.copy2(andreas / "obelix1_ivtx_ladder_v2.gds", inputs))
    SCHEMATIC = Path(shutil.copy2(andreas / "obelix1_ivtx_ladder_v2.kicad_sch", inputs))
    STACK = "uni-bonn-rdl"  # tech/uni-bonn-rdl/stack.toml
    # the board HyperLynx simulates: Andreas' KiCad export (in his HyperLynx project), until the
    # GDS has a net label on every net (its labels are on 80/7, the notes layer, today; then:
    # BOARD_SOURCE = LAYOUT)
    project = Path("/users/aulm/HyperLynx/simulations/VTX_Obelix_1/v3.1")
    BOARD_SOURCE = project / "obelix1_ivtx_ladder_with_nets_v3.1.hyp"
    BOARD = RESULTS / "board" / "obelix1_ivtx_ladder_with_nets_v3.1.hyp"  # the name his project goes with

    # Andreas' HyperLynx project next to the board: VRMs, DC sinks and pin models set in the GUI;
    # the SPICE driver and receiver of the data links
    BOARD.parent.mkdir(parents=True, exist_ok=True)
    for suffix in (".bud", ".bbd", ".pjh"):
        shutil.copy2(project / f"obelix1_ivtx_ladder_with_nets_v3.1{suffix}", BOARD.parent)
    shutil.copy2("/users/aulm/iVTX_transmisstion_line/fast_drv.sp", BOARD.parent / "fast_drv.sp")
    shutil.copy2("/users/aulm/iVTX_transmisstion_line/fast_rcv.sp.txt", BOARD.parent / "fast_rcv.sp")
    hyperlynx.prepare()


@target
def drc():
    """The layout against the Uni Bonn RDL's design rules (gdscheck, tech/uni-bonn-rdl)."""
    checked = drc_run.drc(LAYOUT, RESULTS / "drc", kit="uni-bonn-rdl", suite="main", topcell=None, tile=20000.0)
    drc_analysis.violations(checked, max_violations=0, out=checked / "violations.csv")


@target
def lvs():
    """The layout's nets, named by its labels on the pin layers (6/1, 3/1, 8/1, 68/1), against
    the schematic."""
    checked = lvs_run.lvs(LAYOUT, RESULTS / "lvs", stack=STACK, schematic=SCHEMATIC)
    lvs_analysis.findings(checked, out=checked / "summary.csv")


@target
def board():
    """The board for HyperLynx, its signal nets (40 um wide) as traces: BoardSim simulates
    pours as no line; supplies stay pours. Then what HyperLynx sees in it (stackup, nets and
    lengths, VRMs, modelled pins), and the pins their net's copper doesn't reach."""
    gds2hyp.hyp(BOARD_SOURCE, BOARD, stack=STACK, refill=False, traces="auto", trace_max_width=0.08)

    # what HyperLynx sees in it: stackup, nets with their lengths, VRMs, modelled pins
    # (info/info.json); pins their net's copper doesn't reach (more than 25 um away), and copper
    # on no net
    run.info(BOARD, RESULTS / "board" / "info", license="HyperLynx SI/PI")
    analysis.connectivity(BOARD, tolerance_m=25e-6, nets=None, out=RESULTS / "board" / "connectivity.csv")


@target
def power_integrity():
    """DC of the four chips' 3 V rails at 3 A each and their returns: per net the resistance to
    each pin, drop, current density; pin voltages, via currents; the voltage-drop and
    current-density maps. (PSUB and PWell: their VRMs have no reference
    pin, and HyperLynx wants one shared with every chip they feed; how to set that up is open.)"""
    board = BOARD
    out = RESULTS / "power_integrity"

    # the four 3 V rails, one per chip, at 3 A each, with their returns; HyperLynx's report flags
    # more than 5 % drop, 1.5e7 A/m^2 and 1 A per via
    supply = run.dc(board, out / "supply", license="HyperLynx SI/PI", nets=["/3V_1", "/3V_2", "/3V_3", "/3V_4"], include_ref=True, vrms={}, sinks={}, vrm_references={}, sink_currents={"/3V_1": 3.0, "/3V_2": 3.0, "/3V_3": 3.0, "/3V_4": 3.0}, max_voltage_drop=5.0, max_current_density=1.5e7, max_via_current=1.0, return_from=None, return_vrm_type="simple", return_sink_resistance=1e6)

    # HyperLynx maps the loss of supply nets only: the returns, re-solved as the supply with the
    # currents the first run measured as sinks (1 Mohm across each), give theirs
    ret = run.dc(board, out / "return", license="HyperLynx SI/PI", nets=["/3V_1", "/3V_2", "/3V_3", "/3V_4"], include_ref=True, vrms={}, sinks={}, vrm_references={}, sink_currents={}, max_voltage_drop=5.0, max_current_density=1.5e7, max_via_current=1.0, return_from=supply / "ports.csv", return_vrm_type="simple", return_sink_resistance=1e6)

    # per rail: the current its sinks draw, drop and return rise; per net: resistance VRM -> sink
    # pins, drop over them, current density (median, max)
    analysis.dc_drop(supply, out=out / "dc_drop.csv")
    analysis.dc_table(supply, ret, out=out / "dc_table.csv")

    # current density in the copper, and the drop per mm it causes, against 15 A/mm² (the limit
    # set in HyperLynx: a PCB value; thin aluminium takes some 1000 A/mm², to agree on)
    analysis.current_density([supply, ret], max_density=1.5e7, out=out / "current_density.csv")

    # every pin's current and voltage, and the resistance from the VRM to each sink pin
    analysis.pins([supply, ret], out=out / "pins.csv")
    analysis.resistance(supply, out=out / "resistance.csv")

    # the maps for the viewer: voltage drop from the VRM per rail, current density, via current
    plots.plot_dc(supply, out, ret)


@target
def sparams():
    """4-port S-parameters of each data pair (P, N at the chip, then at the connector); insertion
    and return loss at its Nyquist frequency, 80 MHz."""
    board = BOARD
    out = RESULTS / "sparams"

    # 1 MHz to 5 GHz, adaptive sweep at medium tolerance, 50 ohm ports, real line models
    runs = [run.sparam(board, out / pair, license="HyperLynx SI/PI", pins=p["driver"] + p["receiver"], fmin=1e6, fmax=5e9, sweep="adaptive", steps=500, steps_per_decade=100, tolerance="medium", reference_impedance=50.0, lossy=True, roughness=True, trapezoid=True, nonfunctional_pads=False) for pair, p in PAIRS.items()]
    runs += [run.sparam(board, out / name, license="HyperLynx SI/PI", pins=b["driver"] + b["far"], fmin=1e6, fmax=5e9, sweep="adaptive", steps=500, steps_per_decade=100, tolerance="medium", reference_impedance=50.0, lossy=True, roughness=True, trapezoid=True, nonfunctional_pads=False) for name, b in BUSES.items()]

    # SDD21 at least -3 dB, SDD11 at most -10 dB (first guesses, to agree on)
    analysis.sparams(runs, at_hz=80e6, min_sdd21_db=-3.0, max_sdd11_db=-10.0, out=out / "sparams.csv")
    for r in runs:
        plots.plot_sparam(r, out, name=r.name)


@target
def signal_integrity():
    """Each data pair at 160 Mb/s PRBS7: its TDR, eye with loss, crosstalk and
    jitter, and the crosstalk from the ADC lines and rst onto it held low."""

    # TDR of the pair from its S-parameters (the sparams step): a 50 ps step into each port and
    # each end's pair; distance at v = c/sqrt(eps_eff), eps_eff 3.3 (the dielectric's, to agree on)
    sps = [RESULTS / "sparams" / pair for pair in [*PAIRS, *BUSES]]
    for sp in sps:
        plots.plot_tdr(sp, RESULTS / "signal_integrity", rise_ps=50.0, er_eff=3.3, name=sp.name)
    analysis.tdr(sps, rise_ps=50.0, er_eff=3.3, out=RESULTS / "signal_integrity" / "tdr.csv")
    board = BOARD
    out = RESULTS / "signal_integrity"

    eyes, xts = [], []
    for pair, p in PAIRS.items():
        # eye with loss, roughness, crosstalk (traces within 0.5 mm, area fills), and jitter:
        # 100 ps rms random, 300 ps at 5 MHz sine
        real = run.si(
            board,
            out / pair / "eye_real",
            license="HyperLynx SI/PI",
            net=f"/{pair}_N",
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
            models={},
        )

        # the pair's drivers held low while every ADC line and rst switch as an 80 MHz clock
        # (HyperLynx brings in those that couple: D4's own ADC_4 and rst, 95 and 100 um away over
        # 25 mm; D1's ADC_2), with HyperLynx's stock IBIS CMOS driver and receivers
        xt = run.si(
            board,
            out / pair / "crosstalk",
            license="HyperLynx SI/PI",
            net=f"/{pair}_N",
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
            driver_states={pin: "low" for pin in p["driver"]},
            aggressors=[{"driver": q["adc"][0], "receivers": [q["adc"][1]], "lib": "modvsez.ibs", "device": "MODvsEZIBIS", "model": "3"} for q in PAIRS.values()] + [{"driver": "VTX2.100", "receivers": ["V1.100", "V2.100", "V3.100", "V4.100"], "lib": "modvsez.ibs", "device": "MODvsEZIBIS", "model": "3"}],
            models={},
        )
        eyes.append(real)
        xts.append(xt)
        plots.plot_si([real, xt], out, at="VTX2", skip_ui=4, centre_window=0.05, edge_levels=(0.2, 0.8), settle=0.1, name=pair)

    # CLK and CMD at every chip (loss, crosstalk, jitter): CLK's waveforms, CMD's eye; no aggressors set
    bus_eyes = []
    for name, b in BUSES.items():
        # eye with loss, roughness, crosstalk (traces within 0.5 mm, area fills), and jitter:
        # 100 ps rms random, 300 ps at 5 MHz sine
        real = run.si(
            board,
            out / name / "eye_real",
            license="HyperLynx SI/PI",
            net=f"/{name}_N",
            operation="standard" if name == "CLK" else "eye",  # a clock: its waveforms (HyperLynx makes no eye of one)
            simulator="auto",
            corner="typical",
            probe="pin",
            stimulus_scope="global",
            bit_sequence="oscillator" if name == "CLK" else "prbs",
            prbs_order=7,
            repetitions=4,
            frequency=80e6 if name == "CLK" else 160e6,  # CLK: an 80 MHz clock (160 Mb/s DDR), to agree on
            duty_cycle=50.0,
            initial_state="low",
            stop_s=200e-9 if name == "CLK" else None,
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
            models={**{pin: dict(FAST, io="output") for pin in b["driver"]}, **{pin: dict(RCV, io="input") for pin in b["chips"]}},
        )
        # each chip's differential wave at its receiver's input (HyperLynx has no pair of these pins)
        plots.pair_waves(real, {f"V(V{k}-{b['pin']},V{k}-{b['pin'] + 1})": (f"V(V{k}_{b['pin']}-Vin_x)", f"V(V{k}_{b['pin'] + 1}-Vin_x)") for k in (1, 2, 3, 4)})
        bus_eyes.append(real)
        plots.plot_si([real], out, at=CHIPS, skip_ui=4, centre_window=0.05, edge_levels=(0.2, 0.8), settle=0.1, name=name)

    # at the receiver (VTX2): eye at least 200 mV and 0.7 UI, crosstalk at most 100 mV p-p (first
    # guesses, to agree on); eyes measured after 4 UI, height within +-5 % UI of the centre,
    # rise and fall 20-80 %; crosstalk after the first 10 % of the run
    analysis.eyes(eyes, min_height=0.2, min_width_ui=0.7, at="VTX2", skip_ui=4, centre_window=0.05, edge_levels=(0.2, 0.8), out=out / "eyes.csv")
    analysis.eyes(bus_eyes, min_height=0.2, min_width_ui=0.7, at=CHIPS, skip_ui=4, centre_window=0.05, edge_levels=(0.2, 0.8), out=out / "eyes_clk_cmd.csv")
    analysis.crosstalk(xts, max_noise=0.1, at="VTX2", settle=0.1, out=out / "crosstalk.csv")
