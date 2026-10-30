"""Concentric infill: inset loops that follow the outline, `spacing` apart.

A path-pattern plugin (see templates/path_template.py for the contract).
"""
PATTERN = {
    "name": "Concentric",
    "description": "Loops parallel to the outline, one strand spacing apart.",
}


def generate(region, layer, settings, spacing):
    strokes = []
    i = 0
    while True:
        # the region is where strand centre lines may go, so the first loop
        # runs on its boundary
        ring = region.buffer(-spacing * i, join_style=2)
        if ring.is_empty or i > 10_000:
            break
        polys = list(getattr(ring, "geoms", [ring]))
        for poly in polys:
            if poly.geom_type != "Polygon" or poly.is_empty:
                continue
            strokes.append(list(poly.exterior.coords))
            for hole in poly.interiors:
                strokes.append(list(hole.coords))
        i += 1
    return strokes
