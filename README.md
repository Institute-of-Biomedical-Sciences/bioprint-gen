# BioprintGen

A g-code generator for **extrusion bioprinting**.

Generate toolpaths for simple primitives (cuboids, cylinders) or import and slice
 **STL** meshes, choose an infill pattern, preview the result layer-by-layer,
**edit individual toolpath vertices by drag-and-drop**, and export g-code in either a
**Planet CNC**-compatible dialect (matching the [Vitaprint bioprinting system](https://github.com/Institute-of-Biomedical-Sciences/vitaprint-gcode-generator)) or a
generic **Marlin** flavor with absolute E.

For questions and suggestions, contact bostjan.vihar@um.si

---

## Features

- **Sources**
  - Cuboid (X × Y × Z)
  - Cylinder (walls discretised into a fine 128-segment polygon)
  - STL import + planar slicing (interior holes preserved)
- **Infill patterns**
  - Rectilinear **connected** — a single boustrophedon (serpentine) strand per layer
  - Rectilinear **separate bars** — individual parallel strands
  - **Gyroid** — true zero-isocontour of the gyroid field, sampled at each layer's Z
  - Rectilinear patterns have an adjustable **X-to-Y angle** (layer rotation, default **90°**)
  - Connected rectilinear only joins strands with an **extruded** connector when that
    connector stays inside the region, so holes/bores and concave gaps are bridged by a
    (non-extruding) travel rather than filled with material.
- **Minimum crossings** — within any single layer only parallel strands are laid down,
  so there are **zero strand crossings per layer**; the woodpile is built by rotating
  the strand direction between layers. Travel moves are ordered greedily
  (nearest-endpoint) to further reduce in-air crossings and travel distance.
- **Flow control (start–stop behaviour)** — a dedicated panel to counter start-up delay
  and ooze: a **start ramp** and matching **end retract** (metered/piston only — prime the
  extrusion axis at each stroke start / retract it at each stroke end; both separate from
  the print-start ramp), a **start dwell** (`G4` pause each time extrusion begins, seconds)
  and a **coast distance** (extrusion turns off this many mm before each stroke's end and
  coasts at print speed). Works in all dialects; strokes shorter than the coast distance
  coast entirely.
- **Perimeters** — 0–8 contour walls inset before infill (default 1).
- **Variable layer height** — a default height for the whole structure, plus any number
  of **Z-range sections** (`Z start → Z end → height`) that override it. Uncovered Z uses
  the default.
- **Tool change / multiple extruders** — placed by **g-code line range**, not by Z: you
  generate first, then declare ranges like "lines 45–52 → extruder 2" (type the numbers
  from the g-code panel, or select a segment in the preview and hit *Set start/end ←
  selection*). Each extruder has a manually entered **XY offset** (extruder 1 is the (0,0)
  reference). On Planet CNC the offset is applied with offset variables (`#102`–`#105`)
  plus a `G92` frame shift and the extruding mechanism is switched for the wrapped moves
  (piston axis A→B/C, or pneumatic valve `M63 P1→P2/P3`); on Marlin with `T0/T1/T2` +
  `G10 L1` tool offsets. Line numbers refer to the **clean** generation, so the panel
  shows that by default (stable numbering to mark against); toggle *Show tool changes* in
  the toolbar to see the applied output with the offset sequence inserted (export always
  includes it — the dock title tells you which view you're in). Tool assignments are a
  per-move property: they survive vertex edits (splitting a line inherits its tool), and
  changing tool sections or offsets no longer re-slices, so **manual geometry edits are
  preserved** — only changing a geometry parameter (size, layer height, infill, …)
  rebuilds the toolpath.
- **Custom start / end g-code** — free-text blocks injected after the machine header and
  before the footer.
- **Settings footer** — an optional commented dump of every setting at the **end** of the
  file, so a print can be reproduced later.
- **Custom g-code flavours** — define per-action templates (travel, extrude, layer change,
  tool change, …) with placeholders, saved to disk and importable/exportable.
- **Live preview** with a layer slider (plus **◀ / ▶ single-step buttons**), pan/zoom,
  and colour-coded moves (perimeter / infill / travel). Extrude colours also encode the
  **active extruder** so tool changes are visible.
- **Side view (X–Z elevation)** — a non-editable, **resizable** inset in the top-right
  corner of the preview (drag its bottom-left corner) showing the whole layer stack from
  the side, each layer a band at its z coloured by tool, making variable layer heights and
  tool changes obvious. The current layer is highlighted.
- **Line-numbered g-code panel**, with **two-way selection**: clicking a segment
  highlights its g-code line, and clicking a g-code line jumps to that layer and
  highlights the matching segment.
- **Drag-and-drop editing** — every toolpath vertex is a draggable handle; moving it
  rewrites the underlying move(s) and **regenerates the g-code instantly**.
  **Double-click a line to insert a vertex; right-click a vertex to delete it.**
- **Light and dark themes**, toggled from the top-right of the toolbar.
- **Scalable interface** — A− / A+ (and `Ctrl+-` / `Ctrl+=` / `Ctrl+0`) scale the whole
  UI from 70 % to 250 % for small or high-DPI screens; the choice is saved to
  `default_settings.json` (`ui.scale`) and the 2D preview stays at its fixed size.
- **Collapsible parameter panels** so a long settings list stays navigable, and inputs
  that **ignore the mouse wheel until clicked**, so scrolling can't nudge a value.
- **Editable startup defaults** — `default_settings.json` in the project folder is read
  at launch (theme, scale, which panels are open, source shape, and every print setting).
  Edit it in a text editor and restart. The app only ever writes one key back —
  `ui.scale`, from the zoom control — leaving everything else you hand-edit untouched;
  unknown/missing keys are tolerated.
- **Help menu** — renders `README.md` and `MANUAL.md` live from disk (with images), so
  edits show up without restarting.
- **Platform-independent export** — g-code is written as UTF-8 with an explicit line
  terminator (CRLF by default, `"gcode_line_ending": "lf"` to change), so the same
  project exports byte-identically on Windows, Linux and macOS. The suggested filename
  is `<shape>_<flavour>[_<drive>]_<date>.gcode`.
- **Three g-code dialects** (see below), with **piston (metered)** or
  **pneumatic (valve)** extrusion drive.

---

## Install

Requires **Python 3.10+**.

```bash
cd bioprintgen
python -m venv .venv
source .venv/bin/activate         # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

> **Why the extra packages?** trimesh declares only `numpy` as a hard dependency and
> treats `scipy`, `networkx`, `rtree` and `manifold3d` as optional extras, so pip will
> not install them on its own — but STL slicing fails without them. They are listed
> explicitly in `requirements.txt` for that reason. (`pip install "trimesh[easy]"` is
> an equivalent catch-all if you prefer.)
>
> If no `rtree` wheel is available for your platform, install the system
> `libspatialindex` package first (e.g. `apt install libspatialindex-dev`,
> `brew install spatialindex`).

## Run

```bash
python main.py
```
Instead of running the file from command line on Windows, you can also use the bat file, in which you set the repository folder path and use it as a shortcut by double clicking.

## Tests

A regression suite covers the g-code-correctness invariants (feedrates, relative Z
rises across variable-height sections, hole-free infill, tool-change offsets and
mechanism switching, flow-control arithmetic, settings round-tripping). It is
Qt-free, so it runs headless anywhere in a few seconds.

```bash
pip install -r requirements-dev.txt
pytest
```

Pick a shape (or import an STL), tweak the parameters on the left, hit **Generate**,
scan through layers with the slider, drag any vertex to nudge it, then **Export g-code**.

---

## G-code dialects

### Planet CNC (reference-compatible)

Matches the conventions of the
[Vitaprint reference generator](https://github.com/Institute-of-Biomedical-Sciences/vitaprint-gcode-generator):

- `%` program start/end delimiters, tab-separated fields.
- `G92 X0 Y0` zeroes XY at the start.
- **Piston drive** meters extrusion on a letter axis via an expression variable, e.g.
  `G1 X.. Y.. A[#<_a> +<delta>]` (extruder 1 → `A`, 2 → `B`, 6 → `C`). The delta is
  `segment_length/10 × extrusion_rate`. Optional live flow scaling with
  `* #<_hw_jogpot>/511`.
- **Pneumatic drive** toggles a digital valve: `M63 P<e> Q10000 E<value×10>` to open,
  `… E0` to close.
- All motion is linear (`G0`/`G1`). The writer can emit `G2/G3 … R<radius>` arcs, but
  nothing currently produces them — curves are discretised into short line segments.

### Marlin (absolute E)

A portable flavor for FFF-style firmware:

- `G21` / `G90` / `M82` header, `G92 … E0` reset.
- Extrusion tracked as an **absolute, monotonically increasing E** value.
  E per segment = `length × line_width × layer_height / filament_area`
  (`filament_area = 1.0` tracks mm³ directly — convenient for volumetric bioinks).
- Travels use `G0`, prints use `G1 … E.. F..`.

### Custom flavours

Define your own dialect as a set of small `str.format` templates — one per common
action (`header`, `layer_change`, `travel`, `extrude`, `tool_change`, `extruder_on/off`,
`footer`). Placeholders like `{x} {y} {e} {f} {z} {layer} {tool} {offx} {offy}` are filled
in per move; a blank template emits nothing. Manage them via **Manage flavours…** in the
panel — saved flavours live under `~/.bioprintgen/flavours` (override with the
`BIOPRINTGEN_FLAVOURS` environment variable) and can be imported/exported as JSON.

---

## Project layout

```
bioprintgen/
├── main.py                     entry point
├── requirements.txt
├── default_settings.json       user-editable startup defaults (app only writes ui.scale)
├── MANUAL.md                   detailed user manual (Help → User manual)
├── bioprintgen/
│   ├── model.py                dataclasses / enums / PrintSettings
│   ├── pipeline.py             Project façade (from_cuboid / from_cylinder / from_stl)
│   ├── settingsio.py           reads default_settings.json
│   ├── geometry/
│   │   ├── primitives.py       cuboid & cylinder layer regions
│   │   └── stlslicer.py        STL load, drop-to-bed, planar slicing
│   ├── infill/
│   │   ├── base.py             insets, clipping, parallel line sets, layer angle
│   │   ├── rectilinear.py      connected (serpentine) & separate bars
│   │   └── gyroid.py           zero-isocontour extraction
│   ├── planning/
│   │   └── toolpath.py         perimeter+infill ordering, travels, min-crossing greedy
│   ├── gcode/
│   │   ├── writer.py           Planet CNC + Marlin + custom-template writers
│   │   └── flavour.py          custom flavour templates + JSON store
│   └── gui/
│       ├── app.py              MainWindow, docks, auto-regenerate
│       ├── controls.py         parameter panel (sections, tool change, start/end)
│       ├── flavourdialog.py    custom flavour editor (save / import / export)
│       ├── preview2d.py        editable QGraphicsScene (drag / add / remove vertices)
│       ├── sideview.py         non-editable X–Z elevation of the layer stack
│       ├── codeview.py         line-numbered g-code view
│       ├── helpview.py         live markdown viewer for the Help menu
│       └── theme.py            light + dark Fusion themes
```

The pipeline is headless-usable without the GUI:

```python
from bioprintgen.pipeline import Project
from bioprintgen.model import PrintSettings, InfillType, Dialect

s = PrintSettings(infill_type=InfillType.GYROID, dialect=Dialect.PLANET_CNC)
p = Project.from_cuboid(20, 20, 4, s)
p.plan()
with open("out.gcode", "w", encoding="utf-8", newline=s.line_terminator()) as f:
    f.write(p.gcode_text())
```

Settings are validated before any g-code is emitted, so an invalid value raises a
`ValueError` naming the problem rather than silently producing something the machine
shouldn't run (a zero feedrate, for instance, would stall the head mid-print). Call
`s.validate()` yourself if you'd rather check up front — it returns a list of
human-readable problems, empty when everything is in order.

---

## Notes & safety

- Always dry-run generated g-code against your machine's soft limits and a viewer
  before printing. Extrusion rates, valve values, and speeds are machine/bioink
  specific — the defaults are starting points, not calibrated values.
- No support structures are generated (by design).

## Licensing

This tool follows the conventions of, and is intended to interoperate with, the
Vitaprint reference generator, which is licensed under **GPLv3**. If you distribute
BioprintGen or derivatives, treat it as **GPLv3-compatible** and retain that license.
