"""Parallel-plate test: two 1000x1000 µm plates, 10 µm gap, 1 µm thick (vacuum)."""
import klayout.db as db
ly = db.Layout(); ly.dbu = 0.001
c = ly.create_cell("PLATES")
for l in (1, 2):
    c.shapes(ly.layer(l, 0)).insert(db.DBox(0, 0, 1000, 1000))
c.shapes(ly.layer(1, 0)).insert(db.DText("bot", db.DTrans(500, 500)))
c.shapes(ly.layer(2, 0)).insert(db.DText("top", db.DTrans(500, 500)))
ly.write("plates.gds")
