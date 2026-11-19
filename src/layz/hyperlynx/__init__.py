"""Run HyperLynx (Siemens, licensed) headless from layz: `layz hl ...`.

HyperLynx ships its own Python (``Scripting/bin/pythonHL``, 3.11) with a ``hyperlynx`` module
that drives BoardSim without its GUI. layz (its own venv) prepares everything around it and
runs small scripts (``runner/``) with that Python:

    setup.py     find the install, build a writable overlay of it, the environment
    cli.py       `layz hl setup|info|dc|si|sparam|plot`: copy the board into a run folder,
                 write job.json, run a runner, collect its CSVs
    runner/      the scripts HyperLynx's Python runs (stdlib + hyperlynx only)
    plots.py     plots of a run folder, in the plot style of layz.plotstyle

What the API needs, found by trying it (it has no documentation):

* HyperLynx writes Bsw.pak/bsw.ini into its own install folder; on a read-only install every
  board fails to open ("Error opening board"). It is run from an overlay: symlinks to the
  install, with writable copies of those files.
* ``app.SetLicenseCollections("HyperLynx SI/PI")`` before ``OpenFile`` (names as in the GUI's
  licensing dialog), and the license server in MGLS_LICENSE_FILE.
* Settings (SimSettings, crosstalk switches, VRMs, sinks, models) are saved into the board's
  project files (.bud, .pjh) when the design closes: runs work on a copy of the board.
* A wrong argument can crash the Python process outright; the runners stick to calls known
  to work.
"""

from layz.hyperlynx.targets import target  # noqa: E402,F401  (for flow files)
