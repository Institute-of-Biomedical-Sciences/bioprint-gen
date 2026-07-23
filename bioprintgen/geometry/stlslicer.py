"""STL import + planar slicing.

trimesh does the heavy lifting: robust mesh loading and multi-plane sectioning.
We convert each z-section into shapely polygons (with holes filled correctly)
and hand back the same Layer objects the primitive generator produces.
"""
from __future__ import annotations

from typing import List, Optional, Tuple

import numpy as np
import trimesh
from shapely.geometry import Polygon, MultiPolygon
from shapely.ops import unary_union

from ..model import Layer, PrintSettings, build_z_levels


class SlicedModel:
    def __init__(self, mesh: trimesh.Trimesh, path: str):
        self.mesh = mesh
        self.path = path

    # ---- metadata used by the GUI ----
    @property
    def extents(self) -> Tuple[float, float, float]:
        e = self.mesh.extents
        return (float(e[0]), float(e[1]), float(e[2]))

    @property
    def zmin(self) -> float:
        return float(self.mesh.bounds[0][2])

    @property
    def zmax(self) -> float:
        return float(self.mesh.bounds[1][2])


def load_stl(path: str, drop_to_bed: bool = True, center_xy: bool = True) -> SlicedModel:
    """Load an STL (or any trimesh-supported mesh) and normalise its position."""
    mesh = trimesh.load(path, force="mesh")
    if isinstance(mesh, trimesh.Scene):
        mesh = mesh.dump(concatenate=True)
    if mesh.is_empty or len(mesh.faces) == 0:
        raise ValueError("Mesh contains no faces.")

    transform = np.eye(4)
    bounds = mesh.bounds.copy()
    if drop_to_bed:
        transform[2, 3] -= bounds[0][2]         # z-min to 0
    if center_xy:
        cx = (bounds[0][0] + bounds[1][0]) / 2.0
        cy = (bounds[0][1] + bounds[1][1]) / 2.0
        transform[0, 3] -= cx
        transform[1, 3] -= cy
    mesh.apply_transform(transform)
    return SlicedModel(mesh, path)


def _levels(height: float, settings: PrintSettings) -> List[Tuple[float, float]]:
    return build_z_levels(height, settings)


def _section_to_polygon(mesh: trimesh.Trimesh, z: float):
    """Return a shapely (Multi)Polygon for the cross-section at height z, or None."""
    section = mesh.section(plane_origin=[0, 0, z], plane_normal=[0, 0, 1])
    if section is None:
        return None
    # trimesh renamed Path3D.to_planar -> to_2D (to_planar is deprecated and
    # scheduled for removal); prefer the new name, fall back for older trimesh.
    to_2d = getattr(section, "to_2D", None) or section.to_planar
    planar, _to_3d = to_2d()
    polys = list(planar.polygons_full)  # shapely polygons with holes resolved
    if not polys:
        return None
    geom = unary_union(polys)
    if geom.is_empty:
        return None
    return geom


def slice_model(model: SlicedModel, settings: PrintSettings) -> List[Layer]:
    """Slice a loaded mesh into Layer objects using the print settings."""
    height = model.zmax - model.zmin
    layers: List[Layer] = []
    for i, (z, h) in enumerate(_levels(height, settings)):
        geom = _section_to_polygon(model.mesh, z)
        if geom is None:
            # keep index continuity but skip empty slices
            continue
        layers.append(Layer(z=round(z, 6), index=len(layers), regions=geom, height=h))
    if not layers:
        raise ValueError("Slicing produced no layers - check model size vs layer height.")
    return layers
