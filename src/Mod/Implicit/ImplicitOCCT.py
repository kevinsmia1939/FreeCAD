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
