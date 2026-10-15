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
                          boolean_faces, tessellate, kernel_version)
from _ImplicitOCCT import mixed_box as _mixed_box


def mixed_box(field, box, operation="common", tolerance=.1, maximum_cells=512):
    """Experimental F<=0 gyroid/axis-aligned Part box boundary, NOT a Part solid.

    Planar caps are independent conventional Part faces. The opaque native face
    retains shared seam topology internally; do not sew caps into a fake solid.
    Only closed, resolved, single contours away from box edges are supported.
    """
    if not isinstance(box, Part.Shape):
        raise TypeError("box must be a conventional Part.Shape")
    result = _mixed_box(field, box.exportBrepToString(), operation, tolerance, maximum_cells)
    result["operation"] = operation
    result["inside_convention"] = "F<=0"
    result["planar_caps"] = []
    for record in result.pop("planar_caps_brep"):
        cap = Part.Shape()
        cap.importBrepFromString(record)
        result["planar_caps"].append(cap.Faces[0])
    return result
