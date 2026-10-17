# SPDX-License-Identifier: LGPL-2.1-or-later
"""Experimental in-process native faces. Never import the private extension directly.

Opaque immutable snapshots are NOT Part shapes or solids. Primitive records use
explicit OCCT schema-1 I/O; trimmed/topological records reject rather than lose
geometry. Query residuals have field units, ray brackets/model tolerances mm.
"""
from pathlib import Path
from importlib.util import find_spec
import Part

if not Part.OCC_VERSION.startswith("8."):
    raise ImportError("ImplicitOCCT requires the wholly OCCT-8-linked FreeCAD build")
if Path(Part.__file__).resolve().parents[2] != Path(__file__).resolve().parents[2]:
    raise ImportError("ImplicitOCCT and Part must belong to the same FreeCAD build")

_spec = find_spec("_ImplicitOCCT")
if (_spec is None or _spec.origin is None
        or Path(_spec.origin).resolve().parent != Path(__file__).resolve().parent):
    raise ImportError("Build the native-face extension in the selected OCCT 8 FreeCAD tree")

from _ImplicitOCCT import (sphere, gyroid, value, gradient, normal, in_domain, info,
                          intersect_ray, dumps, loads, translated, trim,
                          boolean_faces, tessellate, kernel_version, classify_mixed,
                          prepare_mixed_mesh, tessellate_mixed, audit_mixed_mesh,
                          check_mixed_coverage, check_mixed_regularity, check_box_regularity,
                          check_mixed_correspondence, check_box_topology, check_mixed_topology,
                          check_box_region_topology, check_mixed_region_topology,
                          check_mixed_cap_attachment, check_mixed_trim_attachment)
from _ImplicitOCCT import mixed_box as _mixed_box, loads_mixed as _loads_mixed, dumps_mixed, inspect_mixed as _inspect_mixed


def mixed_box(field, box, operation="common", tolerance=.1, maximum_cells=512):
    """Experimental F<=0 gyroid/axis-aligned Part box boundary, NOT a Part solid.

    Planar caps are independent conventional Part faces. The opaque native face
    retains shared seam topology internally; do not sew caps into a fake solid.
    Resolved open/closed contours share certified box-edge roots; ambiguous
    corner/tangent cases reject. Planar caps may contain multiple regions/holes.
    """
    if not isinstance(box, Part.Shape):
        raise TypeError("box must be a conventional Part.Shape")
    result = _mixed_box(field, box.exportBrepToString(), operation, tolerance, maximum_cells)
    return _decode_caps(result, operation)


def _decode_caps(result, operation=None):
    if operation is not None:
        result["operation"] = operation
    result["inside_convention"] = "F<=0"
    result["planar_caps"] = []
    for record in result.pop("planar_caps_brep"):
        cap = Part.Shape()
        cap.importBrepFromString(record)
        result["planar_caps"].append(cap.Faces[0])
    return result


def loads_mixed(record):
    """Restore shared native topology, not a recipe rebuild or a Part solid.

    Error-bound metadata is retained as provenance, not re-certified:
    seam_bound_verified is False. Meshes/pointers are never restored.
    """
    return _decode_caps(_loads_mixed(record))


def inspect_mixed(handle):
    """Inspect an immutable native/property snapshot without numerical rebuilding."""
    return _decode_caps(_inspect_mixed(handle))
