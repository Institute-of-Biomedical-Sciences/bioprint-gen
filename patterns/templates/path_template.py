"""Path-pattern plugin template.

Copy this file to the patterns folder (one level up), rename it - the file name
becomes the pattern id, e.g. my_zigzag.py -> "my_zigzag" - and choose
Patterns… -> Reload patterns in the Layers panel.  Load errors are listed in
that dialog.

Use a path plugin for patterns you can't write as a single equation (those go
in a .json equation pattern instead - see equation_template.json).  Plugins are
ordinary Python run inside BioprintGEN: only install ones you trust.

THE CONTRACT
------------
PATTERN   dict with "name" (shown in the pattern list) and "description"
          (tooltip).  Optional.

generate(region, layer, settings, spacing) -> list of strokes
    region    shapely Polygon / MultiPolygon: where strand *centre lines* may
              go (already inside the walls).  Holes are real holes.
    layer     .z (top of the layer, mm), .index (0-based), .height (mm)
    settings  the PrintSettings in force for this layer (a Z-range infill
              section's pattern/density already applied).  Useful fields:
              line_width, infill_angle, layer_rotation, perimeters
    spacing   strand centre-to-centre distance in mm.  In Infill % mode it is
              derived from the % (spacing = nozzle / fraction), so draw about
              1/spacing mm of strand per mm^2 and % will mean the same as for
              rectilinear.

    Return a list of strokes; each stroke is a list of (x, y) points printed
    as one continuous strand.  Return [] for "no infill on this layer".

WHAT THE APP DOES FOR YOU
    * clips every stroke to `region` (overshooting the outline is fine, and the
      simplest way to cover odd shapes) and drops pieces shorter than 1e-6 mm
    * orders the strokes to keep travels short, adds travels / safe-height
      hops / flow control, and writes the g-code
    * if generate() raises, generation stops with the error and the layer
      number, so you can fix the plugin and reload

GOOD PRACTICE
    * Prefer few, long strokes: every stroke start/stop is a flow start/stop.
    * Avoid strokes that cross each other within a layer (the nozzle would
      drag through fresh material).
    * Keep it deterministic (same input -> same output); the preview and the
      exported file are generated separately.
    * Helpers you may import: math, numpy, shapely (all installed with the app),
      and bioprintgen.infill.base.layer_angle(base, rotation, index).
"""
import math

PATTERN = {
    "name": "Diagonal lines (template)",
    "description": "Parallel lines at the layer's angle - a minimal example.",
}


def generate(region, layer, settings, spacing):
    from bioprintgen.infill.base import layer_angle

    angle = math.radians(layer_angle(settings.infill_angle, settings.layer_rotation,
                                     layer.index))
    dx, dy = math.cos(angle), math.sin(angle)        # along the lines
    nx, ny = -dy, dx                                 # across the lines

    minx, miny, maxx, maxy = region.bounds
    cx, cy = (minx + maxx) / 2, (miny + maxy) / 2
    reach = math.hypot(maxx - minx, maxy - miny) / 2 + spacing

    strokes = []
    n = int(reach / spacing) + 1
    for i in range(-n, n + 1):
        ox, oy = cx + nx * i * spacing, cy + ny * i * spacing
        # long enough to cross the whole region; the app clips it
        strokes.append([(ox - dx * reach, oy - dy * reach),
                        (ox + dx * reach, oy + dy * reach)])
    return strokes
