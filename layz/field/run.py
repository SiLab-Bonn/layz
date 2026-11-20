"""E-field and potential for a flow's targets (layz.flow): of a `layz.pex.run` folder solved with
charges=True, every option given. The command line (`layz field`) is the same with defaults.

    from layz.field import run as field

    field.field(caps, voltages={"D4_P": 1.0}, plane="x=1500", window=None, res=320, ...)

Writes into the pex folder: section_*.png/.pdf (potential and |E| with arrows, in
layz.plotstyle) and section_*.vtk for a plane; field.vtk, panels.vtk, field.html for the 3-D grid.
"""

from layz.field.compute import field  # noqa: F401
