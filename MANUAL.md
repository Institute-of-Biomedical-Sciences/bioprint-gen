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
| **Left dock** | All print parameters, grouped into collapsible panels. |
| **Centre** | Layer preview (editable), layer slider with ◀ / ▶ single-step buttons, and the side-view inset. |
| **Right dock** | The generated g-code, with line numbers. |
| **Toolbar** | Generate, Import STL, Export g-code, Help, and the light/dark toggle (far right). |

Click a **panel header** on the left to expand or collapse it. Only *Source*
starts expanded — open the ones you are working with to keep the list short.

**Scrolling is safe:** spin boxes and dropdowns ignore the mouse wheel until you
click them. So you can scroll the parameter list without nudging values by
accident. Click a field first, then the wheel adjusts it.

**Interface scale.** The far-right of the toolbar has an **A− / A+** pair (and
`Ctrl+-` / `Ctrl+=`, with `Ctrl+0` to reset) that scales the whole interface —
text, buttons, panels, tables — from 70 % to 250 %, so it fits comfortably on a
small laptop or a large high-DPI monitor. The 2D preview itself (the toolpath
dots and line weights) is left at its fixed size on purpose. Your chosen scale is
saved to `default_settings.json` (`ui.scale`) and restored next run — this is the
one value the app writes to that file; everything else there is yours to edit.

**Settings that don't apply are greyed out** (field and caption together), so you
can see at a glance what the current selection actually uses:

| Selection | Greyed out |
| --- | --- |
| Cuboid | Diameter |
| Cylinder | Width X, Depth Y |
| Import STL | Width, Depth, Diameter, Height (the mesh supplies them) |
| Gyroid infill | Strand spacing, Base angle, Layer rotation (it uses Gyroid period) |
| Rectilinear infill | Gyroid period |
| Pneumatic drive | Extrusion rate, Start ramp, End retract (no metered axis) |
| Piston drive | Valve value |
| Marlin / custom flavour | Drive, Ramp, Extruder (Planet CNC concepts) |
| Tool change off | Extruder offsets, the ranges table, the selection buttons |

Greying is purely a visual cue — a greyed value is still remembered, so switching
shape back and forth never loses what you typed.

---

## 2. Basic workflow

1. Pick a **Source** — Cuboid, Cylinder, or Import STL.
2. Set **Layers** (layer height) and **Infill** (pattern, spacing, perimeters).
3. Press **Generate** (it also auto-regenerates as you change parameters).
4. Scan layers with the slider or the ◀ / ▶ buttons.
5. Tweak the toolpath by dragging / adding / removing vertices if needed.
6. **Export g-code**.

---

## 3. Preview editing

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

> Manual vertex edits survive parameter changes that don't affect geometry
> (speeds, offsets, flow control, tool sections). Changing a *geometry*
> parameter — size, layer height, infill, perimeters — re-slices and rebuilds
> the toolpath, which discards manual edits.

### Side view (X–Z)

The inset in the preview's top-right corner shows the whole stack from the side:
one band per layer at its z, thickness = layer height, coloured by tool, with the
current layer highlighted. It makes variable layer heights and tool changes
obvious at a glance. **Drag its bottom-left corner to resize it.**

---

## 4. Layers and variable layer height

*Layers* panel:

- **Layer height** — the default for the whole structure.
- **First layer** — 0 means "same as layer height".
- **Safe Z** — lift after the print finishes.
- **Sections table** — add rows of `Z start → Z end → height` to override the
  default over a z range. Any z not covered by a section uses the default.

The relative Z rise emitted between layers always matches the gap between
consecutive layer z values, so a section boundary steps by exactly the height
you asked for.

> **Reading the `z=` in the comments.** `; layer 0  z=0.2` reports the layer's
> **top** surface. The nozzle sits at the layer's *bottom* while printing it — so
> layer 0 is printed with Z at 0, not 0.2. Comparing the comment against the
> machine's Z readout will look off by one layer; that is expected, not a bug.

---

## 5. Flow control (start–stop behaviour)

Extrusion doesn't start or stop instantly. This panel compensates:

| Setting | Effect |
| --- | --- |
| **Start ramp** | *Metered/piston only.* Primes the extrusion axis at each stroke start, before the dwell, to get flow going. Separate from the print-start ramp. |
| **End retract** | *Metered/piston only.* Retracts the extrusion axis at each stroke end. Balances the start ramp so it doesn't accumulate. Keep at 0 if not needed. |
| **Start dwell** | A `G4` pause each time extrusion starts, letting material begin flowing before the nozzle moves. |
| **End dwell** | A `G4` pause after each stroke ends — after the coast and retract, once flow has stopped — before travelling away. Independent of the coast. |
| **Coast distance** | Extrusion turns off this many mm *before* the stroke ends; the tail is travelled at print speed so residual ooze finishes the line. |
| **Travel lift** | *Safe height.* Before every travel between strokes the nozzle hops **up** by this amount (relative), moves in XY, then drops back down — so it never drags across freshly deposited material. 0 = no hop. |

A typical metered stroke ends up as:

```
G1  Z[#<_z> -2] ;safe down       ← drop back after the previous travel
G1  A[#<_a> +0.03] ;flow start   ← start ramp
G4  P2 ;dwell                    ← start dwell
G1  X.. Y.. A[#<_a> +...]        ← extruding moves
G1  X.. Y..                      ← coast (no extrusion)
G1  A[#<_a> -0.02] ;flow end     ← end retract
G4  P1 ;end dwell                ← end dwell
G1  Z[#<_z> +2] ;safe up         ← lift for the travel to the next stroke
G0  X.. Y.. F1600                ← travel
```

Strokes shorter than the coast distance coast entirely (no extrusion).
These settings only change the emitted g-code — they never re-slice. (On Marlin
the hop uses absolute Z; on Planet CNC it is a relative `#<_z>` move.)

---

## 6. Tool change / multiple extruders

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

### Which line numbers?

Ranges refer to the **clean** g-code — the version *without* tool changes
inserted — because inserting them shifts every later line. That is why the
g-code panel shows the clean version by default; its numbering stays stable
while you mark.

Use **Toggle – show tool change** (above the g-code panel) to switch to the
applied version and check the result. The dock title always tells you which view
you are looking at. **Export always includes the tool changes**, whichever view
is on screen.

### What gets emitted

- **Planet CNC** — offsets are stored as variables `#102`–`#105`; entering a tool's
  range saves the position, moves by the offset and `G92`s the frame back, so the
  pattern stays in one logical coordinate system. Leaving the range recalibrates.
  The extruding mechanism switches too: piston axis `A→B/C`, or pneumatic valve
  `M63 P1→P2/P3`.
- **Marlin** — `T0/T1/T2` with `G10 L1` tool offsets.

Tool assignment is a property of each move, so splitting a line inside a marked
section gives both halves the same tool.

---

## 7. G-code dialects and custom flavours

Pick a dialect in *Extrusion & dialect*. Beyond the built-in **Planet CNC** and
**Marlin**, you can define your own via **Manage flavours…**: per-action
templates (header, layer change, travel, extrude, tool change, extruder on/off,
dwell, footer) with placeholders such as `{x} {y} {e} {f} {z} {layer} {tool}`.
Blank template = emit nothing. Flavours are stored as JSON under
`~/.bioprintgen/flavours` and can be imported/exported.

---

## 8. Start / end g-code and the settings block

- **Start g-code** is injected after the machine header, before the first layer.
- **End g-code** is injected before the footer.
- **Write settings as comment header** appends a commented dump of every setting
  at the **end** of the file, so a print can be reproduced later.

### Exported file format

Exports are always written as **UTF-8** with an explicit line terminator, so the
same project produces a byte-identical file on Windows, Linux and macOS. (Without
this, Python would use the machine's locale codec — e.g. cp1250 on a Central
European Windows install — which cannot represent characters like `µ`, `≈` or `→`
and would fail outright if one appeared in your start/end g-code or a flavour name.)

Line endings default to **CRLF**, which is what a Windows export has always
produced. If your controller prefers Unix endings, set it in
`default_settings.json`:

```json
"print_settings": { "gcode_line_ending": "lf" }
```

The status bar confirms the format after each export, e.g.
`Saved part.gcode  (UTF-8, CRLF)`.

The exported filename is suggested automatically as
`<shape>_<flavour>[_<drive>]_<date>.gcode`, e.g.
`falcon-kartusa_planetcnc_piston_2026-07-23.gcode`.

---

## 9. Changing the startup defaults

The app reads `default_settings.json` from the project folder at startup. It
**never writes** this file — edit it in a text editor and restart.

```json
{
  "ui":             { "theme": "dark", "expanded_panels": ["Source"] },
  "source":         { "kind": "cuboid", "width": 10.0, "height": 5.0 },
  "print_settings": { "layer_height": 0.2, "print_speed": 500.0 }
}
```

- `ui.theme` — `"dark"` or `"light"`.
- `ui.scale` — interface scale (0.7–2.5). Also set live by the toolbar A− / A+.
- `print_settings.gcode_line_ending` — `"crlf"` (default) or `"lf"` for exports.
- `ui.expanded_panels` — panel titles to open on startup, e.g.
  `["Source", "Flow control (start–stop behaviour)"]`.
- `source` — the shape and dimensions to start with.
- `print_settings` — any field of the print settings; missing keys keep their
  built-in value and unknown keys are ignored, so a partial file is fine.

---

## 10. Troubleshooting

**Connected infill crosses a hole.** Fixed — connected rectilinear only joins two
strands with extruded material when the connector stays inside the region;
otherwise it travels. If you still see a bridge, check that the hole actually
appears in the slice at that layer.

**My vertex edits disappeared.** A geometry parameter changed (size, layer
height, infill, perimeters), which re-slices. Do manual edits last, or change
only non-geometry settings afterwards.

**The offset sequence isn't in the g-code.** The panel is showing the clean view.
Turn on **Toggle – show tool change**, or just export — the export always
contains it.

**Tool ranges landed in the wrong place.** Line numbers refer to the clean
g-code. Turn the toggle *off* while reading/typing line numbers, or use the
*Set start/end ← selection* buttons, which always resolve correctly.

**A value changed while I scrolled.** It shouldn't — fields ignore the wheel
until clicked. If a field is already focused (you clicked it), the wheel does
adjust it; click elsewhere to defocus.
