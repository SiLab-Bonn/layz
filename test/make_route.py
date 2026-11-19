"""Route test board (stack: test/route.toml): two pads joined by an L-shaped 40 µm route on
F.Cu, one via down to an In1.Cu plane, a 3 x 2 mm outline. Run: python test/make_route.py"""

from pathlib import Path

from klayout import db

ly = db.Layout()
ly.dbu = 0.001
top = ly.create_cell("ROUTE")
fcu, in1, via, edge = (ly.layer(l, 0) for l in (1, 2, 3, 70))

pad = ly.create_cell("PAD")  # a footprint with one pad
pad.shapes(fcu).insert(db.DBox(-100, -100, 100, 100))
for x, y in ((500, 500), (2500, 1500)):
    top.insert(db.DCellInstArray(pad.cell_index(), db.DTrans(x, y)))

top.shapes(fcu).insert(db.DBox(500, 480, 2520, 520))  # the route: across ...
top.shapes(fcu).insert(db.DBox(2480, 480, 2520, 1500))  # ... and up
top.shapes(fcu).insert(db.DBox(1400, 1100, 1600, 1300))  # a via landing
top.shapes(via).insert(db.DBox(1450, 1150, 1550, 1250))
top.shapes(in1).insert(db.DBox(100, 100, 2900, 1900))  # the plane
for a, b in (((0, 0), (3000, 0)), ((3000, 0), (3000, 2000)), ((3000, 2000), (0, 2000)), ((0, 2000), (0, 0))):
    top.shapes(edge).insert(db.DPath([db.DPoint(*a), db.DPoint(*b)], 10))

ly.write(str(Path(__file__).with_name("route.gds")))
