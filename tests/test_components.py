"""Multi-component parts: extra shapes with their own infill, extruder and walls."""
from __future__ import annotations

import pytest
from shapely.geometry import Point

from bioprintgen import settingsio
from bioprintgen.gcode import writer as gw
from bioprintgen.geometry.components import component_polygon, compose_layers
from bioprintgen.infill.base import perimeter_strokes
from bioprintgen.model import (
    Component, InfillSection, InfillType, PrintSettings, ToolLineRange, WALLS_MERGE,
)
from bioprintgen.pipeline import Project


def _settings(**kw) -> PrintSettings:
    s = PrintSettings()
    s.layer_height = 0.2
    s.line_width = 0.4
    s.tool_change_enabled = True
    s.extruder2_offset = (20.0, 0.0)
    for k, v in kw.items():
        setattr(s, k, v)
    return s


def _core(**kw) -> Component:
    """A 4 mm cylinder in the middle of a 12 x 10 block."""
    c = Component(shape="cylinder", size_x=4.0, height=1.0, x=6.0, y=5.0)
    for k, v in kw.items():
        setattr(c, k, v)
    return c


def _project(s, w=12, d=10, h=1.0):
    p = Project.from_cuboid(w, d, h, s)
    p.plan()
    return p


def _loops(lt, ext=None):
    """Closed perimeter strokes (start point revisited) in a layer."""
    n, start = 0, None
    for m in lt.moves:
        if m.kind.value != "perimeter" or (ext is not None and m.extruder != ext):
            start = None
            continue
        if start is None:
            start = m.start
        if m.end == start:
            n += 1
            start = None
    return n


# --------------------------------------------------------------------------- #
#  composition
# --------------------------------------------------------------------------- #
def test_no_components_changes_nothing():
    a = _project(_settings())
    b = _project(_settings(components=[_core(enabled=False)]))
    assert a.gcode_text().split("; =====")[0] == b.gcode_text().split("; =====")[0]
    assert all(L.parts is None for L in b.layers)


def test_higher_in_the_list_owns_the_overlap():
    s = _settings(components=[Component(size_x=4, size_y=4, height=1, x=4, y=5),
                              Component(size_x=4, size_y=4, height=1, x=6, y=5)])
    layer = compose_layers(Project.from_cuboid(12, 10, 1.0, _settings()).layers, s)[0]
    first, second, main = layer.parts
    assert (first.component, second.component, main.component) == (0, 1, None)
    assert first.region.area == pytest.approx(16.0)
    assert second.region.area == pytest.approx(8.0)          # half was taken
    assert main.region.area == pytest.approx(120 - 24.0)
    assert layer.regions.area == pytest.approx(120.0)


def test_component_occupies_its_own_z_span():
    s = _settings(components=[_core(z=0.4, height=0.4)])
    p = _project(s)
    tops = [round(L.z, 3) for L in p.layers if any(pt.component == 0 for pt in L.parts)]
    assert tops == [0.6, 0.8]


def test_component_above_the_main_shape_extends_the_stack():
    s = _settings(components=[_core(height=2.0)])
    p = _project(s, h=1.0)
    assert round(p.layers[-1].z, 3) == 2.0
    plain = Project.from_cuboid(12, 10, 2.0, _settings())
    assert [L.z for L in p.layers] == [L.z for L in plain.layers]
    assert all(len(L.parts) == 1 for L in p.layers if L.z > 1.0 + 1e-9)


def test_rotated_cuboid_footprint():
    poly = component_polygon(Component(size_x=4, size_y=2, x=1, y=1, rotation=90))
    minx, miny, maxx, maxy = poly.bounds
    assert (maxx - minx, maxy - miny) == (pytest.approx(2), pytest.approx(4))
    assert poly.centroid.x == pytest.approx(1) and poly.centroid.y == pytest.approx(1)


# --------------------------------------------------------------------------- #
#  walls and infill
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("walls,loops", [(WALLS_MERGE, 1), (1, 2), (2, 3), (3, 4)])
def test_walls_value_is_the_number_of_walls_at_the_interface(walls, loops):
    """merge -> just the part's outline; n -> the outline + n walls round the
    core, and the main part adds none of its own along the shared edge."""
    lt = _project(_settings(components=[_core(walls=walls, extruder=2)])).toolpath[0]
    assert _loops(lt) == loops
    assert _loops(lt, ext=2) == loops - 1


def test_legacy_minus_one_still_means_merge():
    a = _project(_settings(components=[_core(walls=-1)])).gcode_text().split("; =====")[0]
    b = _project(_settings(components=[_core(walls=0)])).gcode_text().split("; =====")[0]
    assert a == b


def test_body_infill_meets_the_component_wall_without_a_gap():
    """Body strands end half a strand from the shared edge, the component's
    wall runs half a strand inside it: one strand width apart = touching."""
    s = _settings(components=[Component(size_x=6, size_y=10, height=1, x=9, y=5,
                                        walls=1, extruder=2)], strand_spacing=1.0)
    lt = _project(s).toolpath[0]
    body_x = max(m.end[0] for m in lt.moves
                 if m.extrude and m.kind.value == "infill" and m.extruder == 1)
    wall_x = min(min(m.start[0], m.end[0]) for m in lt.moves
                 if m.extrude and m.kind.value == "perimeter" and m.extruder == 2)
    assert wall_x - body_x == pytest.approx(0.4, abs=1e-6)


def test_component_crossing_the_outline_gets_its_own_walls_there():
    """Half of the core sticks out of the block: the block's wall stops at the
    core (no wall of ink 1 across ink 2), the core's own wall closes round it."""
    s = _settings(components=[_core(x=12.0, walls=1, extruder=2)])
    lt = _project(s).toolpath[0]
    core = component_polygon(s.components[0])
    for m in lt.moves:
        if m.extrude and m.kind.value == "perimeter" and m.extruder == 1:
            mid = Point((m.start[0] + m.end[0]) / 2, (m.start[1] + m.end[1]) / 2)
            assert not core.buffer(0.2 - 1e-6).contains(mid)
    assert _loops(lt, ext=2) == 1


def test_covered_component_is_reported_and_still_outlined():
    from bioprintgen.geometry.components import hidden_components
    s = _settings(components=[_core(size_x=6), _core(size_x=3, extruder=2)])
    p = _project(s)
    assert hidden_components(p.layers) == [1]
    assert len(p.toolpath[0].outlines) == 2
    assert all(m.extruder == 1 for m in p.toolpath[0].moves)


def test_component_infill_stays_in_the_component():
    s = _settings(components=[_core(extruder=2, walls=1, pattern="gyroid", percent=50)])
    p = _project(s)
    core = component_polygon(s.components[0]).buffer(1e-6)
    for lt in p.toolpath:
        for m in lt.moves:
            if m.extrude and m.extruder == 2:
                assert core.contains(Point(m.end))
            elif m.extrude:
                assert not core.buffer(-1e-3).contains(Point(m.end))


def test_merged_zones_meet_a_strand_width_apart():
    """Strands of the main zone and a merged zone stop half a strand short of
    the shared edge each, so they end one strand width apart, not overlapping."""
    s = _settings(components=[Component(size_x=6, size_y=10, height=1, x=9, y=5,
                                        percent=60)], strand_spacing=1.0)
    lt = _project(s).toolpath[0]
    xs = [m.end[0] for m in lt.moves if m.extrude and m.kind.value == "infill"]
    left = max(x for x in xs if x < 6.0)
    right = min(x for x in xs if x > 6.0)
    assert right - left == pytest.approx(0.4, abs=1e-6)


def test_component_density_is_its_own():
    s = _settings(components=[Component(size_x=10, size_y=8, height=1, x=6, y=5,
                                        walls=0, percent=80,
                                        pattern="rectilinear_separate")],
                  infill_mode="percent", infill_percent=30)
    p = _project(s, w=12, d=10)
    region = component_polygon(s.components[0])
    inner, _ = perimeter_strokes(region, 0, s.line_width)
    lt = p.toolpath[0]
    length = sum(m.length for m in lt.moves if m.extrude and m.kind.value == "infill"
                 and region.contains(Point(m.end)))
    assert s.line_width * length / inner.area == pytest.approx(0.8, rel=0.1)


def test_blank_pattern_follows_the_infill_sections():
    s = _settings(components=[_core(percent=50)],
                  infill_sections=[InfillSection(0.0, 0.4, InfillType.GYROID, 0)])
    layer_s = s.for_layer(0.0)
    assert layer_s.for_component(s.components[0]).infill_type == InfillType.GYROID
    assert s.for_layer(0.6).for_component(s.components[0]).infill_type == \
        InfillType.RECTILINEAR_CONNECTED


# --------------------------------------------------------------------------- #
#  extruders / tool change
# --------------------------------------------------------------------------- #
def test_component_extruder_drives_the_tool_change():
    s = _settings(components=[_core(extruder=2, walls=1)])
    p = _project(s)
    text = p.gcode_text()
    assert text.count("; --- tool change: extruder 2 ---") >= 2
    exts = [{m.extruder for m in lt.moves if m.extrude} for lt in p.toolpath]
    assert all(e == {1, 2} for e in exts)


def test_each_layer_starts_with_the_loaded_extruder():
    """Extruder order alternates so a layer begins with the tool the previous
    one ended on: one change per layer instead of two."""
    p = _project(_settings(components=[_core(extruder=2, walls=1)]))
    seq = []
    for lt in p.toolpath:
        e = [m.extruder for m in lt.moves if m.extrude]
        seq.append((e[0], e[-1]))
    for (_a, end), (start, _b) in zip(seq, seq[1:]):
        assert end == start


def test_other_extruder_needs_tool_change_on():
    s = _settings(tool_change_enabled=False, components=[_core(extruder=2)])
    assert any("turn on Tool change" in m for m in s.validate())


def test_line_ranges_override_on_top_of_component_extruders():
    s = _settings(components=[_core(extruder=2, walls=1)])
    p = _project(s)
    for lt in p.toolpath:
        for m in lt.moves:
            m.extruder = 1
    clean = p.glines()
    move_lines = [i + 1 for i, g in enumerate(clean) if g.move is not None]
    gw.apply_line_ranges(p.toolpath, clean, [ToolLineRange(move_lines[0], move_lines[2], 3)])
    first = p.toolpath[0].moves
    assert [m.extruder for m in first[:3]] == [3, 3, 3]
    assert {m.extruder for lt in p.toolpath for m in lt.moves[3:]} == {1, 2}


# --------------------------------------------------------------------------- #
#  validation / persistence
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("bad,msg", [
    (dict(size_x=0), "size"), (dict(height=0), "size"), (dict(z=-1), "Z start"),
    (dict(extruder=4), "extruder"), (dict(percent=120), "%"), (dict(walls=-2), "walls"),
    (dict(pattern="nope"), "not available"), (dict(shape="sphere"), "shape"),
])
def test_component_validation(bad, msg):
    s = _settings(components=[_core(**bad)])
    assert any("Component 1" in m and msg in m for m in s.validate())


def test_disabled_components_are_not_validated():
    s = _settings(components=[_core(size_x=0, enabled=False)])
    assert s.validate() == []


def test_defaults_file_round_trip():
    comps = [_core(extruder=2, walls=1, pattern="schwarz_p", percent=35, name="core"),
             Component(rotation=30, enabled=False)]
    back = settingsio.dict_to_settings(settingsio.settings_to_dict(_settings(components=comps)))
    assert back.components == comps


def test_malformed_component_values_fall_back_to_defaults():
    c = settingsio.dict_to_component({"size_x": "wide", "walls": "2", "x": 3, "junk": 1})
    assert c.size_x == Component().size_x and c.walls == 2 and c.x == 3.0


def test_export_import_rebuilds_the_same_print():
    s = _settings(components=[_core(extruder=2, walls=1, percent=60),
                              Component(size_x=3, size_y=12, height=1.4, x=11, y=5)])
    s.source = {"kind": "cuboid", "width": 12.0, "depth": 10.0, "height": 1.0,
                "diameter": 12.0, "stl_path": None}
    text = _project(s).gcode_text()
    assert "; components (highest priority first):" in text
    back, source, _f, complete = settingsio.parse_gcode_settings(text)
    assert complete and back.components == s.components
    rebuilt = Project.from_cuboid(source["width"], source["depth"], source["height"], back)
    rebuilt.plan()
    motion = lambda t: [l for l in t.splitlines() if l.strip() and not l.startswith(";")]
    assert motion(rebuilt.gcode_text()) == motion(text)


# --------------------------------------------------------------------------- #
#  stage 2b: subtract (voids / channels) and horizontal cylinders
# --------------------------------------------------------------------------- #
def _void(**kw) -> Component:
    c = Component(shape="cylinder", size_x=3.0, height=1.0, x=6.0, y=5.0,
                  operation="subtract")
    for k, v in kw.items():
        setattr(c, k, v)
    return c


def _extruded_mids(lt):
    return [Point((m.start[0] + m.end[0]) / 2, (m.start[1] + m.end[1]) / 2)
            for m in lt.moves if m.extrude]


def test_subtract_leaves_a_walled_void():
    s = _settings(components=[_void()])
    p = _project(s)
    hole = component_polygon(s.components[0])
    for lt in p.toolpath:
        assert not any(hole.buffer(-1e-6).contains(q) for q in _extruded_mids(lt))
        assert _loops(lt) == 2                     # outline + wall round the void
    assert p.layers[0].regions.area == pytest.approx(120 - hole.area, rel=1e-6)


def test_subtract_only_cuts_what_is_below_it():
    """Above the void in the list: kept (e.g. a lining or plug of another ink);
    below it: cut."""
    plug = _core(size_x=2.0, walls=1, extruder=2)              # inside the void
    below = Component(size_x=4, size_y=4, height=1, x=6, y=5, percent=80)
    p = _project(_settings(components=[plug, _void(), below]))
    L = p.layers[0]
    plug_part, void_part, below_part, main_part = L.parts
    assert plug_part.region.area == pytest.approx(component_polygon(plug).area)
    assert void_part.void and below_part.region.area == pytest.approx(
        16 - component_polygon(_void()).area, rel=1e-3)
    assert any(m.extruder == 2 for m in p.toolpath[0].moves if m.extrude)


def test_void_never_raises_the_part_or_adds_an_extruder():
    s = _settings(tool_change_enabled=False,
                  components=[_void(height=5.0, extruder=3, pattern="nope")])
    assert s.validate() == []                      # its add-only fields are ignored
    p = _project(s, h=1.0)
    assert round(p.layers[-1].z, 3) == 1.0
    assert s.component_extruders() == set()


def test_channel_through_the_side_opens_the_outline():
    s = _settings(components=[Component(size_x=20, size_y=1.0, height=0.6, x=6, y=5,
                                        z=0.2, operation="subtract")])
    p = _project(s)
    assert p.layers[0].regions.geom_type == "Polygon"          # below the channel
    assert p.layers[1].regions.geom_type == "MultiPolygon"     # split in two
    assert _loops(p.toolpath[1]) == 2                          # each half walled


def test_horizontal_cylinder_slices_into_a_narrowing_slot():
    c = Component(shape="cylinder", axis="horizontal", size_x=2.0, size_y=8.0,
                  x=5, y=5, z=1.0)
    assert c.z_top() == 3.0
    mid = component_polygon(c, 2.0)                # through the axis: full width
    assert mid.bounds == pytest.approx((1, 4, 9, 6))
    low = component_polygon(c, 1.4)                # 0.6 below the axis
    w = 2 * (1.0 - 0.6 ** 2) ** 0.5
    assert low.bounds[3] - low.bounds[1] == pytest.approx(w)
    assert component_polygon(c, 0.9).is_empty and component_polygon(c, 3.1).is_empty


def test_horizontal_cylinder_follows_its_direction():
    c = Component(shape="cylinder", axis="horizontal", size_x=2.0, size_y=8.0,
                  x=0, y=0, z=0, rotation=90)
    minx, miny, maxx, maxy = component_polygon(c, 1.0).bounds
    assert (maxx - minx, maxy - miny) == (pytest.approx(2), pytest.approx(8))


def test_horizontal_channel_layers_follow_the_circle():
    s = _settings(components=[Component(shape="cylinder", axis="horizontal",
                                        size_x=1.2, size_y=20, x=6, y=5, z=0.2,
                                        operation="subtract")])
    p = _project(s, h=1.6)
    widths = []
    for L in p.layers:
        void = next((q for q in L.parts if q.void), None)
        widths.append(round(void.shape.bounds[3] - void.shape.bounds[1], 3) if void else 0)
    # 0.2 mm layers, channel from z 0.2 to 1.4: narrow - wide - narrow, symmetric
    assert widths[0] == 0 and widths[-1] == 0
    inside = [w for w in widths if w]
    assert inside == inside[::-1] and max(inside) <= 1.2 and len(inside) == 6


def test_void_that_misses_the_part_is_reported():
    from bioprintgen.geometry.components import hidden_components
    s = _settings(components=[_void(x=50.0), _void(x=6.0)])
    assert hidden_components(_project(s).layers) == [0]


def test_old_component_dicts_default_to_add_and_vertical():
    c = settingsio.dict_to_component({"shape": "cylinder", "size_x": 3})
    assert c.operation == "add" and c.axis == "vertical"
    back = settingsio.dict_to_settings(settingsio.settings_to_dict(
        _settings(components=[_void(axis="horizontal", size_y=9.0)])))
    assert back.components[0].subtract and back.components[0].horizontal


def test_void_export_import_round_trip():
    s = _settings(components=[_void(), Component(shape="cylinder", axis="horizontal",
                                                 size_x=1.0, size_y=20, x=6, y=5, z=0.2,
                                                 rotation=30, operation="subtract")])
    s.source = {"kind": "cuboid", "width": 12.0, "depth": 10.0, "height": 1.0,
                "diameter": 12.0, "stl_path": None}
    text = _project(s).gcode_text()
    assert "subtract cylinder d1.0 length 20 horizontal" in text
    back, source, _f, complete = settingsio.parse_gcode_settings(text)
    rebuilt = Project.from_cuboid(source["width"], source["depth"], source["height"], back)
    rebuilt.plan()
    motion = lambda t: [l for l in t.splitlines() if l.strip() and not l.startswith(";")]
    assert motion(rebuilt.gcode_text()) == motion(text)


# --------------------------------------------------------------------------- #
#  stage 2c: STL components
# --------------------------------------------------------------------------- #
@pytest.fixture
def box_stl(tmp_path):
    import trimesh
    path = tmp_path / "box.stl"
    trimesh.creation.box(extents=(4.0, 6.0, 1.0)).export(path)
    return str(path)


@pytest.fixture
def tube_stl(tmp_path):
    import trimesh
    path = tmp_path / "tube.stl"
    trimesh.creation.annulus(r_min=1.0, r_max=2.0, height=1.0, sections=64).export(path)
    return str(path)


def _stl(path, **kw) -> Component:
    c = Component(shape="stl", stl_path=path, x=6.0, y=5.0)
    for k, v in kw.items():
        setattr(c, k, v)
    return c


def test_stl_component_is_placed_by_centre_and_bottom(box_stl):
    from bioprintgen.geometry.components import component_top, stl_extents
    c = _stl(box_stl, z=0.4)
    assert stl_extents(c) == pytest.approx((4.0, 6.0, 1.0))
    assert component_top(c) == pytest.approx(1.4)
    poly = component_polygon(c, 0.9)
    assert poly.bounds == pytest.approx((4.0, 2.0, 8.0, 8.0))
    assert component_polygon(c, 0.3).is_empty and component_polygon(c, 1.5).is_empty


def test_stl_box_slices_like_the_same_cuboid(box_stl):
    a = _project(_settings(components=[_stl(box_stl, walls=1, percent=60)]))
    b = _project(_settings(components=[Component(size_x=4, size_y=6, height=1, x=6, y=5,
                                                 walls=1, percent=60)]))
    for la, lb in zip(a.layers, b.layers):
        for pa, pb in zip(la.parts, lb.parts):
            assert pa.region.symmetric_difference(pb.region).area < 1e-6
    ext = lambda p: sum(m.length for lt in p.toolpath for m in lt.moves if m.extrude)
    assert ext(a) == pytest.approx(ext(b), rel=1e-6)


@pytest.mark.parametrize("kw,size", [
    (dict(scale=200), (8.0, 12.0, 2.0)),
    (dict(rotation=90), (6.0, 4.0, 1.0)),
    (dict(rot_x=90), (4.0, 1.0, 6.0)),
    (dict(rot_y=90), (1.0, 6.0, 4.0)),
])
def test_stl_scale_and_rotation(box_stl, kw, size):
    from bioprintgen.geometry.components import stl_extents
    assert stl_extents(_stl(box_stl, **kw)) == pytest.approx(size, abs=1e-6)


def test_stl_hole_is_walled_and_outlined(tube_stl):
    s = _settings(components=[_stl(tube_stl, walls=1, extruder=2)])
    lt = _project(s).toolpath[0]
    assert _loops(lt, ext=2) == 2                 # outside + inside of the tube
    assert len(lt.outlines) == 2                  # both rings drawn in the preview
    # the tube's bore is not part of the component: the block fills it
    bore = Point(6.0, 5.0).buffer(0.8)
    assert any(bore.contains(q) for q in _extruded_mids(lt))


def test_stl_subtract_cuts_a_cavity(box_stl):
    s = _settings(components=[_stl(box_stl, operation="subtract", z=0.2, rotation=90)])
    p = _project(s, h=1.6)
    cut = component_polygon(s.components[0], 0.5)
    assert p.layers[0].regions.area == pytest.approx(120.0)             # below it
    assert p.layers[2].regions.area == pytest.approx(120.0 - cut.area)  # through it


def test_missing_stl_is_a_clear_error(tmp_path):
    s = _settings(components=[_stl(str(tmp_path / "gone.stl"))])
    assert any("STL file not found" in m for m in s.validate())
    with pytest.raises(ValueError, match="STL file not found"):
        Project.from_cuboid(12, 10, 1.0, s)
    assert any("choose an STL" in m for m in _settings(components=[_stl("")]).validate())


def test_stl_component_round_trip(box_stl):
    s = _settings(components=[_stl(box_stl, scale=50, rot_x=10, rot_y=20, rotation=30,
                                   extruder=2, walls=1)])
    s.source = {"kind": "cuboid", "width": 12.0, "depth": 10.0, "height": 1.0,
                "diameter": 12.0, "stl_path": None}
    text = _project(s).gcode_text()
    assert "box.stl scale 50% rot (10, 20, 30)" in text
    back, source, _f, _c = settingsio.parse_gcode_settings(text)
    assert back.components == s.components
    rebuilt = Project.from_cuboid(source["width"], source["depth"], source["height"], back)
    rebuilt.plan()
    motion = lambda t: [l for l in t.splitlines() if l.strip() and not l.startswith(";")]
    assert motion(rebuilt.gcode_text()) == motion(text)


def test_real_stl_component(stl_path):
    """The bundled falcon tube, scaled down, as an ink-2 insert."""
    s = _settings(components=[_stl(str(stl_path), scale=20, x=6, y=5, extruder=2, walls=1)])
    p = _project(s, h=1.0)
    assert round(p.layers[-1].z, 1) == pytest.approx(6.7, abs=0.2)      # taller than the block
    assert all(any(m.extruder == 2 for m in lt.moves) for lt in p.toolpath)
