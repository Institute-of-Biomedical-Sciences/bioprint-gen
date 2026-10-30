# BioprintGen

A g-code generator for **extrusion bioprinting** with a PySide6 GUI.

Generate toolpaths for simple primitives (cuboids, cylinders) or import and slice your own **STL** meshes, choose an infill pattern, preview the result layer-by-layer, **edit individual toolpath vertices by drag-and-drop**, and export g-code in either a **[Planet CNC](https://planet-cnc.com/)**-compatible dialect (matching the Vitaprint reference machine) or a generic **[Marlin](https://marlinfw.org/)** flavor with absolute E. 

This tool is developed to ease and optimize the flow control of gels and other soft materials with varying viscosity ranges and shear thinning properties. The main features for this purpose include controlled dwell (to compensate for flow delays), coasting (to compensate for oozing at stroke-end), as well as ramp and retraction of the material for piston-driven extruders.

Contact: bostjan.vihar@um.si

---

## Features

The parameter panel is organised the way a job is set up — **Printer → Design →
Layers → Extrusion → Printing process → Advanced options** — and only lists the
settings that apply to the current selection (see `MANUAL.md` §1–2).

- **Design (geometry sources)**
  - Cuboid (X × Y × Z)
  - Cylinder (walls discretised into a fine 128-segment polygon)
  - STL file + planar slicing (interior holes preserved)
- **Infill patterns**
  - Rectilinear **connected** — a serpentine strand that is only joined with
    extruded material where the connector stays inside the part, so holes/bores and
    concave gaps are bridged by a (non-extruding) travel rather than filled
  - Rectilinear **separate bars** — individual parallel strands
  - **Gyroid** — true zero-isocontour of the gyroid field, sampled at each layer's Z
  - Rectilinear patterns have an adjustable base angle and **layer rotation**
    (default **90°**, the classic woodpile)
- **Infill density as spacing or %** — enter the strand spacing / gyroid period
  directly, or an **infill %** of the area, derived from the nozzle diameter
  (`spacing = nozzle ÷ %`; for gyroid `period = 2.494 × nozzle ÷ %`, a constant
  measured on the generator so a given % deposits the same area fraction for both).
- **Infill sections** — bands of height with their own pattern and density (e.g. dense
  rectilinear base, gyroid middle, dense top); density is a % so it carries across
  patterns, and 0 % keeps the main infill's density.
- **Perimeters** — 0–999 contour walls before infill (default 1); walls stop by
  themselves once the part is full, so a high count gives a **walls-only** part.
- **Rotating layer start** — each layer starts at the next bounding-box corner
  (perimeter seam and infill start), spreading start/stop artefacts over four places.
- **Travel ordering** — strokes are ordered nearest-endpoint first, with zero strand
  crossings inside a layer.
- **Variable layer height** — a general height for the whole structure, plus any
  number of **Z-range sections** (`Z start → Z end → height`) that override it.
- **Extrusion control** — one **ink flow** field whose unit follows the drive
  (mm/10mm for a piston, bar for a pneumatic valve), plus start-stop behaviour:
  print-start **ramp / retract**, per-stroke **start ramp** and **end retract**
  (piston only), **start / end dwell** (`G4` pauses) and **coast distance**
  (extrusion off this many mm before a stroke's end).
- **Printing process** — printing / travel / layer-change speeds, a **travel safe
  height** (Z-hop before every travel), a **final safe height**, and `G92` zeroing at
  the current position.
- **Tool change / multiple extruders** — placed by **g-code line range**, not by Z:
  generate first, then declare ranges like "lines 45–52 → extruder 2" (type the
  numbers, or select a segment in the preview and hit *Set start/end ← selection*).
  Each extruder has an **XY offset** (extruder 1 is the (0,0) reference). On Planet
  CNC the offset is applied with offset variables (`#102`–`#105`) plus a `G92` frame
  shift and the extruding mechanism is switched (piston axis A→B/C, or valve
  `M63 P1→P2/P3`); on Marlin with `T0/T1/T2` + `G10 L1`. Line numbers refer to the
  **clean** generation, which the g-code panel shows by default; *Toggle – show tool
  change* shows the applied output (export always includes it). Tool assignments
  survive vertex edits (splitting a line inherits its tool).
- **Import g-code** — opens a previously exported file, fills every panel from its
  settings block (including the shape / STL, tool ranges and start/end g-code),
  rebuilds the toolpath and confirms the rebuild matches the file.
- **Custom start / end g-code** — free-text blocks injected after the machine header
  and before the footer.
- **Settings block** — every setting written as comments at the **end** of the file
  (plus one machine-readable `BIOPRINTGEN_JSON` line), so a print can be reproduced or
  re-imported later.
- **Custom g-code flavours** — define per-action templates (travel, extrude, layer
  change, tool change, dwell, travel hop, …) with placeholders, saved to disk and
  importable/exportable.
- **Live preview** with a layer slider (plus **◀ / ▶ single-step buttons**), pan/zoom,
  and colour-coded moves (perimeter / infill / travel). Extrude colours also encode the
  **active extruder** so tool changes are visible.
- **Side view (X–Z elevation)** — a non-editable, **resizable** inset in the top-right
  corner of the preview showing the whole layer stack from the side, each layer a band
  coloured by tool. The current layer is highlighted.
- **Line-numbered g-code panel**, with **two-way selection**: clicking a segment
  highlights its g-code line, and clicking a g-code line jumps to that layer and
  highlights the matching segment.
- **Drag-and-drop editing** — every toolpath vertex is a draggable handle; moving it
  rewrites the underlying move(s) and **regenerates the g-code instantly**.
  **Double-click a line to insert a vertex; right-click a vertex to delete it.**
- **Light and dark themes**, toggled from the top-right of the toolbar.
- **Scalable interface** — A− / A+ (and `Ctrl+-` / `Ctrl+=` / `Ctrl+0`) scale the whole
  UI from 70 % to 250 %; the choice is saved to `default_settings.json` (`ui.scale`)
  and the 2D preview stays at its fixed size.
- **Collapsible parameter panels** that **hide** settings which don't apply, and inputs
  that **ignore the mouse wheel until clicked**, so scrolling can't nudge a value.
- **Editable startup defaults** — `default_settings.json` in the project folder is read
  at launch (theme, scale, which panels are open, design, and every print setting).
  The app only ever writes `ui.scale` back; unknown/missing keys are tolerated.
- **Help menu** — renders `README.md` and `MANUAL.md` live from disk (with images).
- **Platform-independent export** — UTF-8 with an explicit line terminator (CRLF by
  default), so the same project exports byte-identically on Windows, Linux and macOS.
  The suggested filename is `<shape>_<flavour>[_<drive>]_<date>.gcode`.
- **Three g-code flavours** (see below), with **piston (metered)** or
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
mechanism switching, flow-control arithmetic, infill-% density, the rotating layer
start, export → import round-tripping, which settings are shown per selection). It runs
headless anywhere in a few seconds.

```bash
pip install -r requirements-dev.txt
pytest
```

Set up the job top to bottom in the left panel (Printer → Design → Layers → …), hit
**Generate**, scan through layers with the slider, drag any vertex to nudge it, then
**Export g-code**. To continue an earlier job, **Import g-code** restores its settings.

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
│   ├── settingsio.py           default_settings.json + settings block of exports (import)
│   ├── geometry/
│   │   ├── primitives.py       cuboid & cylinder layer regions
│   │   └── stlslicer.py        STL load, drop-to-bed, planar slicing
│   ├── infill/
│   │   ├── base.py             insets, clipping, parallel line sets, layer angle
│   │   ├── rectilinear.py      connected (serpentine) & separate bars
│   │   └── gyroid.py           zero-isocontour extraction
│   ├── planning/
│   │   └── toolpath.py         perimeter+infill ordering, travels, rotating layer start
│   ├── gcode/
│   │   ├── writer.py           Planet CNC + Marlin + custom-template writers
│   │   └── flavour.py          custom flavour templates + JSON store
│   └── gui/
│       ├── app.py              MainWindow, docks, auto-regenerate
│       ├── controls.py         parameter panel (six collapsible panels, hides inapplicable rows)
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

This work is licensed under a [Creative Commons Attribution-ShareAlike 4.0 International
License][cc-by-sa]: [![CC BY-SA 4.0][cc-by-sa-shield]][cc-by-sa].