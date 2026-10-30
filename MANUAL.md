# BioprintGEN — User manual

A practical guide to driving the app. For install instructions and the g-code
dialect reference, see `README.md` (Help → README).

> Images placed next to this file can be embedded with `![caption](my-image.png)`
> and will show up here — the manual is read from disk each time you open it, so
> edits appear immediately (use **Reload** if it is already open).

---

## 1. The window

| Area | What it does |
| --- | --- |
| **Left dock** | All print parameters, grouped into six collapsible panels (see §2). |
| **Centre** | Layer preview (editable), layer slider with ◀ / ▶ single-step buttons, and the side-view inset. |
| **Right dock** | The generated g-code, with line numbers, and the *Toggle – show tool change* button above it. |
| **Toolbar** | Generate, **Import g-code**, Export g-code, Help; on the far right the interface scale (A− / A+) and the light/dark toggle. |

Click a **panel header** on the left to expand or collapse it. Only *Design*
starts expanded — open the ones you are working with to keep the list short.

**Settings that don't apply are hidden**, so each panel only lists what the
current selection actually uses:

| Selection | Hidden |
| --- | --- |
| Cuboid | Diameter, STL picker |
| Cylinder | Width X, Depth Y, STL picker |
| STL file | Width, Depth, Diameter, Height (the mesh supplies them) |
| Infill defined by *strand spacing* | Infill % (and Gyroid period for rectilinear, Strand spacing for gyroid) |
| Infill defined by *%* | Strand spacing, Gyroid period (both are derived; the value is shown underneath) |
| Gyroid infill | Base angle, Layer rotation |
| Pneumatic drive | Piston ink flow, Ramp / retract, Start ramp, End retract, Live flow control |
| Piston drive | Pneumatic ink flow (bar) |
| Marlin / custom flavour | Drive, Extruder, both ink-flow fields, Ramp / retract, Start ramp, End retract, Live flow control |
| Tool change on | Extruder (chosen per move instead) |
| Tool change off | Extruder offsets, the ranges table, the selection buttons |

Hiding is purely cosmetic — a hidden value is still remembered, so switching
shape (or drive) back and forth never loses what you typed.

**Scrolling is safe:** spin boxes and dropdowns ignore the mouse wheel until you
click them, so you can scroll the parameter list without nudging values by
accident. Click a field first, then the wheel adjusts it.

**Interface scale.** **A− / A+** on the toolbar (and `Ctrl+-` / `Ctrl+=`, with
`Ctrl+0` to reset) scales the whole interface — text, buttons, panels, tables —
from 70 % to 250 %, so it fits a small laptop or a large high-DPI monitor. The 2D
preview itself (the toolpath dots and line weights) keeps its fixed size on
purpose. Your chosen scale is saved to `default_settings.json` (`ui.scale`) and
restored next run.

---

## 2. The parameter panels

| Panel | Settings, in order |
| --- | --- |
| **Printer** | Drive · Extruder · Nozzle diameter · G-code flavour · Manage flavours… |
| **Design** | Shape · Width X · Depth Y · Diameter · Height Z · Choose STL file… |
| **Layers** | General layer height · First layer height · variable-height table · Infill pattern · Infill defined by · Strand spacing *or* Gyroid period *or* Infill % · Base angle · Layer rotation · infill-sections table · Perimeters · Rotate layer start point |
| **Extrusion** | Ink flow · Ramp / retract · Start ramp · End retract · Start dwell · End dwell · Coast distance |
| **Printing process** | Printing speed · Travel speed · Layer change speed · Travel safe height · Final safe height · Enable tool change + offsets · extruder range table · Set XY = 0 at current position |
| **Advanced options** | Write settings as comment block · Live flow control (jogpot) · Start g-code · End g-code |

**Renamed in this version** (same setting, new label):

| Old label | New label | Panel |
| --- | --- | --- |
| Line width | Nozzle diameter | Printer |
| Dialect | G-code flavour | Printer |
| Extrusion rate / Valve value | Ink flow (mm/10mm for piston, bar for pneumatic) | Extrusion |
| Print / Travel / Z (speeds) | Printing speed / Travel speed / Layer change speed | Printing process |
| Travel lift | Travel safe height | Printing process |
| Safe Z | Final safe height | Printing process |
| Zero XY at start (G92) | Set XY = 0 at current position (G92) | Printing process |
| Write settings as comment header | Write settings as comment block | Advanced options |

**Removed from the panel:** *Minimise crossings* is now always on — it orders
strokes nearest-first, and switching it off only ever made travel 1.3–6× longer.
*Filament area* (Marlin-only E scaling) is no longer shown; it can still be set
in `default_settings.json` if you need it.

---

## 3. Basic workflow

1. In **Printer**, pick the drive, nozzle diameter and g-code flavour.
2. In **Design**, pick the shape — Cuboid, Cylinder, or an STL file.
3. Set **Layers** (layer height, infill, perimeters) and **Extrusion**.
4. Press **Generate** (it also auto-regenerates as you change parameters).
5. Scan layers with the slider or the ◀ / ▶ buttons.
6. Tweak the toolpath by dragging / adding / removing vertices if needed.
7. **Export g-code**.

To pick up an old job, use **Import g-code** (§10) instead of re-entering the
settings.

---

## 4. Preview editing

The preview is a live, editable view of the current layer.

| Action | Result |
| --- | --- |
| **Left-click a line** | Selects that segment and highlights its g-code line on the right. |
| **Click a g-code line** | Jumps to that layer and highlights the matching segment in the preview. |
| **Drag a vertex** | Moves it; the g-code updates instantly. |
| **Double-click a line** | Inserts a new vertex at that point, splitting the line in two. |
| **Right-click a vertex** | Deletes it, merging the two adjacent segments. |
| **Shift+drag / middle-drag** | Pan. **Wheel** = zoom. **Fit** button = fit to view. |

Colours: perimeters and infill use different colours, travels are dashed and
dim, and the extrude colour also encodes **which extruder** a move belongs to.

> Manual vertex edits survive changes that don't affect geometry (speeds,
> offsets, extrusion settings, tool sections). Changing a *geometry* setting —
> size, layer height, nozzle diameter, infill, perimeters, start rotation —
> re-slices and rebuilds the toolpath, which discards manual edits.

### Side view (X–Z)

The inset in the preview's top-right corner shows the whole stack from the side:
one band per layer at its z, thickness = layer height, coloured by tool, with the
current layer highlighted. It makes variable layer heights and tool changes
obvious at a glance. **Drag its bottom-left corner to resize it.**

---

## 5. Layers and infill

### Layer heights

- **General layer height** — the default for the whole structure.
- **First layer height** — 0 means "same as the general layer height".
- **Variable-height table** — add rows of `Z start → Z end → height` to override
  the default over a z range. Any z not covered by a row uses the default.

The relative Z rise emitted between layers always matches the gap between
consecutive layer z values, so a section boundary steps by exactly the height
you asked for.

> **Reading the `z=` in the comments.** `; layer 0  z=0.2` reports the layer's
> **top** surface. The nozzle sits at the layer's *bottom* while printing it — so
> layer 0 is printed with Z at 0, not 0.2. Comparing the comment against the
> machine's Z readout will look off by one layer; that is expected, not a bug.

### Infill pattern and density

**Infill pattern:** *Rectilinear – connected* (one serpentine strand where the
geometry allows; it never extrudes across a hole), *Rectilinear – separate bars*
(every strand on its own), or *Gyroid*.

**Infill defined by** chooses how density is entered:

- **Strand spacing** — the centre-to-centre distance between strands (rectilinear),
  or the cell size **Gyroid period** (gyroid), exactly as before.
- **Infill %** — the fraction of each layer's area covered by lines, worked out
  from the **Nozzle diameter**. 100 % means the lines touch. The resulting
  spacing / period is shown under the field.
  - Rectilinear: `spacing = nozzle diameter ÷ (% / 100)` — e.g. 0.4 mm at 50 % →
    0.80 mm spacing.
  - Gyroid: `period = 2.494 × nozzle diameter ÷ (% / 100)`. The constant was
    measured on the generator itself, so a given % deposits the same area fraction
    for gyroid as for rectilinear (checked to within 5 %).

**Base angle** / **Layer rotation** set the strand direction of layer 0 and how
much it turns each layer (90° gives the classic woodpile). They don't apply to
gyroid.

### Infill sections (different infill per height band)

The table under the infill settings lets bands of the part use a different
pattern and density: rows of `Z start → Z end → Pattern → Infill %`. Any height
not covered by a row uses the main infill above. Typical use: a dense
rectilinear base, a gyroid middle and a dense top.

- **Infill %** is always a percentage here, because a band usually *changes* the
  pattern and a strand spacing doesn't translate to a gyroid period. A % means
  the same area coverage for every pattern.
- **0 %** keeps the main infill's density, converted for the band's pattern —
  so you can change only the pattern. (E.g. main = rectilinear at 1.0 mm with a
  0.41 mm nozzle = 41 %; a gyroid band at 0 % prints gyroid at 41 %.)
- A row covers the layers whose material lies in `Z start … Z end` (the same rule
  as the layer-height table); if rows overlap, the first one wins.
- Walls, layer heights and everything else stay as set; only the infill changes.

Bands are defined by height rather than g-code line, unlike tool changes: a tool
change only relabels moves that already exist, but changing the pattern replaces
the moves themselves, so line numbers would no longer point at anything.

### Perimeters

The number of contour walls laid before the infill (0–999). Walls stop by
themselves once the part is full, so a large number simply gives a part made of
**walls only** — no infill at all.

### Rotate layer start point

On by default. Each layer starts at the next corner of its bounding box —
bottom-left, bottom-right, top-right, top-left, then repeat — moving both the
perimeter seam and the infill start. Start/stop blobs are spread over four
places instead of stacking into one column. Untick it to start every layer at
the same point.

---

## 6. Extrusion

| Setting | Effect |
| --- | --- |
| **Ink flow** | Piston: plunger travel per 10 mm of nozzle motion (**mm/10mm**). Pneumatic: valve pressure in **bar**, written as `M63 P… Q10000 E{bar × 10}` (so 1 bar → `E10`). |
| **Ramp / retract** | *Piston only.* Primes once at the start of the print and retracts once at the end. |
| **Start ramp** | *Piston only.* Primes the axis at each stroke start, before the dwell. |
| **End retract** | *Piston only.* Retracts the axis at each stroke end, balancing the start ramp. Keep at 0 if not needed. |
| **Start dwell** | A `G4` pause each time extrusion starts, letting material begin flowing before the nozzle moves. |
| **End dwell** | A `G4` pause after each stroke ends — after the coast and retract — before travelling away. Independent of the coast. |
| **Coast distance** | Extrusion turns off this many mm *before* the stroke ends; the tail is travelled at printing speed so residual ooze finishes the line. Strokes shorter than this coast entirely. |

A typical piston stroke, with a travel safe height set (§7):

```
G1  Z[#<_z> -2] ;safe down       ← drop back after the previous travel
G1  A[#<_a> +0.03] ;flow start   ← start ramp
G4  P2 ;dwell                    ← start dwell
G1  X.. Y.. A[#<_a> +...] F500   ← extruding moves (printing speed)
G1  X.. Y..                      ← coast (no extrusion)
G1  A[#<_a> -0.02] ;flow end     ← end retract
G4  P1 ;end dwell                ← end dwell
G1  Z[#<_z> +2] ;safe up         ← lift for the travel to the next stroke
G0  X.. Y.. F1600                ← travel
```

These settings only change the emitted g-code — they never re-slice.

---

## 7. Printing process

| Setting | Effect |
| --- | --- |
| **Printing speed** | Feedrate while extruding (restated at the start of every stroke). |
| **Travel speed** | Feedrate of the `G0` moves between strokes. |
| **Layer change speed** | Feedrate of every Z move: layer changes, travel lifts and the final lift. |
| **Travel safe height** | Before **every** travel between strokes the nozzle hops up by this amount (relative), moves in XY, then drops back down — so it never drags across fresh material. 0 = no hop. (Absolute Z on Marlin, a relative `#<_z>` move on Planet CNC.) |
| **Final safe height** | Lift at the very end of the print. |
| **Set XY = 0 at current position** | Emits `G92 X0 Y0` at the start, so the part is placed wherever the nozzle is when the job starts. |

### Tool change / multiple extruders

Tool changes are placed **by g-code line range**, not by height, so you can put
them exactly where you want after seeing the toolpath.

1. Tick **Enable tool change** and enter the **XY offsets** for extruders 2 and 3
   (extruder 1 is the (0,0) reference).
2. **Generate**, then decide where each tool should run.
3. Add a row to the ranges table: `Start line → End line → Extruder`.
   - Type the line numbers you read in the g-code panel, **or**
   - click a segment in the preview and press **Set start ← selection** /
     **Set end ← selection**.
4. The marked moves change colour in the preview.

**Which line numbers?** Ranges refer to the **clean** g-code — the version
*without* tool changes inserted — because inserting them shifts every later
line. That is why the g-code panel shows the clean version by default; its
numbering stays stable while you mark. Use **Toggle – show tool change** (above
the g-code panel) to see the applied version. The dock title always tells you
which view you are looking at. **Export always includes the tool changes.**

**What gets emitted:**

- **Planet CNC** — offsets are stored as variables `#102`–`#105`; entering a tool's
  range saves the position, moves by the offset and `G92`s the frame back, so the
  pattern stays in one logical coordinate system. Leaving the range recalibrates.
  The extruding mechanism switches too: piston axis `A→B/C`, or pneumatic valve
  `M63 P1→P2/P3`.
- **Marlin** — `T0/T1/T2` with `G10 L1` tool offsets.

Tool assignment is a property of each move, so splitting a line inside a marked
section gives both halves the same tool.

---

## 8. G-code flavours

Pick one under **Printer → G-code flavour**. Beyond the built-in **Planet CNC** and
**Marlin**, you can define your own via **Manage flavours…**: per-action
templates (header, layer change, travel, extrude, tool change, extruder on/off,
dwell, travel hop, footer) with placeholders such as
`{x} {y} {e} {f} {z} {layer} {tool}`. Blank template = emit nothing. Flavours are
stored as JSON under `~/.bioprintgen/flavours` and can be imported/exported.

---

## 9. Advanced options and the settings block

- **Write settings as comment block** appends every setting as comments at the
  **end** of the file, so a print can be reproduced later. It is also what
  **Import g-code** reads (§10) — keep it on unless you have a reason not to.
- **Live flow control (jogpot)** — *piston only*: scales extrusion live with the
  Planet CNC jog potentiometer.
- **Start g-code** is injected after the machine header, before the first layer.
- **End g-code** is injected before the footer / final lift.

The block contains a human-readable list (`; layer_height = 0.2`, …), a `source:`
line (shape and dimensions, or the STL path) and one machine-readable line
starting `; BIOPRINTGEN_JSON {…}`, which holds everything — including start/end
g-code and tool ranges — for an exact restore.

### Exported file format

Exports are always written as **UTF-8** with an explicit line terminator, so the
same project produces a byte-identical file on Windows, Linux and macOS. Line
endings default to **CRLF**; to use Unix endings, set
`"print_settings": { "gcode_line_ending": "lf" }` in `default_settings.json`. The
status bar confirms the format after each export, e.g.
`Saved part.gcode  (UTF-8, CRLF)`.

The filename is suggested as `<shape>_<flavour>[_<drive>]_<date>.gcode`, e.g.
`falcon-kartusa_planetcnc_piston_2026-07-23.gcode`.

---

## 10. Import g-code

**Import g-code** on the toolbar opens a previously exported file and picks up
where it left off:

1. The settings block is read and **every panel is filled in** — printer, design
   (shape and dimensions, or the STL), layers, extrusion, printing process, tool
   ranges and start/end g-code.
2. The toolpath is **rebuilt** from those settings, so the preview, the g-code
   panel, editing and export all work normally afterwards.
3. The rebuilt code is compared with the file. If they match, the status bar says
   so. If not, you're told how many motion lines differ — usually because the
   file contained **manual vertex edits**, which aren't stored in the settings.
   The app shows the rebuilt version; the file on disk is never changed.

STL jobs: the STL is looked for at its stored path, then next to the g-code file;
if it isn't found you're asked to locate it.

Files exported by **older versions** carry the print settings but not the shape:
those are restored and the part is rebuilt with whatever shape is currently set
in *Design* — set the right shape (or choose the STL) and it regenerates. Files
without a settings block (e.g. from another program, or exported with the block
switched off) can't be imported.

---

## 11. Changing the startup defaults

The app reads `default_settings.json` from the project folder at startup. Edit it
in a text editor and restart. The app only ever writes one key back — `ui.scale`,
from the toolbar zoom — leaving everything else as you wrote it.

```json
{
  "ui":             { "theme": "dark", "scale": 1.0, "expanded_panels": ["Design"] },
  "source":         { "kind": "cuboid", "width": 10.0, "height": 5.0 },
  "print_settings": { "layer_height": 0.2, "print_speed": 500.0 }
}
```

- `ui.theme` — `"dark"` or `"light"`.
- `ui.scale` — interface scale (0.7–2.5). Also set live by the toolbar A− / A+.
- `ui.expanded_panels` — panel titles to open on startup, e.g.
  `["Printer", "Design", "Extrusion"]`. (An older file naming `"Source"` simply
  opens *Design*.)
- `source` — the shape and dimensions to start with.
- `print_settings` — any field of the print settings; missing keys keep their
  built-in value and unknown keys are ignored, so a partial file is fine. Useful
  keys not shown in the panel: `gcode_line_ending` (`"crlf"` / `"lf"`),
  `filament_area` (Marlin E scaling), `minimize_crossings`. Also:
  `infill_mode` (`"spacing"` / `"percent"`), `infill_percent`, `rotate_start`,
  `infill_sections` (rows of `[z_start, z_end, "gyroid", percent]`; pattern is
  `"rectilinear_connected"`, `"rectilinear_separate"` or `"gyroid"`).

---

## 12. Troubleshooting

**I can't find a setting.** It's probably hidden because it doesn't apply to the
current selection — see the table in §1 (e.g. Ramp / retract only appears for a
piston drive, Diameter only for a cylinder). Renamed settings are listed in §2.

**Connected infill crosses a hole.** It shouldn't — connected rectilinear only
joins two strands with extruded material when the connector stays inside the
region; otherwise it travels. If you still see a bridge, check that the hole
actually appears in the slice at that layer.

**My vertex edits disappeared.** A geometry setting changed (size, layer height,
nozzle diameter, infill, perimeters, start rotation), which re-slices. Do manual
edits last, or change only non-geometry settings afterwards.

**Import says the rebuilt code differs.** The file had manual vertex edits (or was
made by a different version). Settings are restored either way; redo the edits
if you need them.

**Import can't find my STL.** Point it to the file when asked, or put the STL next
to the g-code file and import again.

**The offset sequence isn't in the g-code.** The panel is showing the clean view.
Turn on **Toggle – show tool change**, or just export — the export always
contains it.

**Tool ranges landed in the wrong place.** Line numbers refer to the clean
g-code. Turn the toggle *off* while reading/typing line numbers, or use the
*Set start/end ← selection* buttons, which always resolve correctly.

**A value changed while I scrolled.** It shouldn't — fields ignore the wheel
until clicked. If a field is already focused (you clicked it), the wheel does
adjust it; click elsewhere to defocus.
