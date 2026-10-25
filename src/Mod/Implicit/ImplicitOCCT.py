# SPDX-License-Identifier: LGPL-2.1-or-later
"""Experimental in-process native faces. Never import the private extension directly.

Opaque immutable snapshots are NOT Part shapes or solids. Primitive records use
explicit versioned OCCT I/O, including box-exclusion and cylinder query masks;
unsupported trim topology rejects rather than losing geometry. Query residuals
have field units, ray brackets/model tolerances mm.
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
                          prepare_mixed_mesh, tessellate_mixed, tessellate_mixed_checked, audit_mixed_mesh,
                          check_mixed_coverage, check_mixed_regularity, check_box_regularity,
                          check_box_corners, classify_box_corner,
                          check_mixed_correspondence, check_box_topology, check_mixed_topology,
                          check_box_region_topology, check_mixed_region_topology,
                          check_mixed_cap_attachment, check_mixed_trim_attachment,
                          check_mixed_cap_geometry,
                          build_mixed_shells, inspect_mixed_shells, classify_mixed_shells,
                          build_mixed_solids, inspect_mixed_solids, classify_mixed_solids,
                          start_solid_job, solid_job_status, cancel_solid_job, take_solid_job,
                          start_surface_job, take_surface_job, native_job_status, cancel_native_job,
                          dumps_mixed_solids, loads_mixed_solids,
                          source_mixed_solids as _source_mixed_solids)
from _ImplicitOCCT import mixed_box as _mixed_box, loads_mixed as _loads_mixed, dumps_mixed, inspect_mixed as _inspect_mixed
from _ImplicitOCCT import start_boundary_job as _start_boundary_job, take_boundary_job as _take_boundary_job
from _ImplicitOCCT import trace_gyroid_plane as _trace_gyroid_plane
from _ImplicitOCCT import trace_gyroid_cylinder as _trace_gyroid_cylinder
from _ImplicitOCCT import trace_gyroid_cylinder_periodic as _trace_gyroid_cylinder_periodic
from _ImplicitOCCT import trace_gyroid_cylinder_boundary as _trace_gyroid_cylinder_boundary
from _ImplicitOCCT import build_gyroid_cylinder_rings as _build_gyroid_cylinder_rings
from _ImplicitOCCT import restrict_cylinder_local as _restrict_cylinder_local
from _ImplicitOCCT import trace_gyroid_cylinder_disks as _trace_gyroid_cylinder_disks
from _ImplicitOCCT import build_cylinder_caps as _build_cylinder_caps, inspect_cylinder_caps as _inspect_cylinder_caps


def _decode_cylinder_caps(result):
    result["caps"] = []
    for records in result.pop("caps_brep"):
        faces = []
        for record in records:
            face = Part.Shape()
            face.importBrepFromString(record)
            faces.append(face.Faces[0])
        result["caps"].append(faces)
    return result


def build_cylinder_caps(face, origin, axis, x_direction, radius, angle_bounds, height_bounds,
                        distance_tolerance=.1, maximum_cells=512, negative=True,
                        maximum_nesting_tests=2000000):
    """Actual planar cap regions, with retained source field/shared native topology.

    caps_handle owns the complete graph; caps contains independent conventional
    face previews. Cap topology and contour bounds are separate from solid proof.
    cap_areas use adaptive integration for the many-knot bounded seam curves.
    """
    if type(negative) is not bool:
        raise TypeError("negative must be an explicit bool")
    if type(maximum_nesting_tests) is not int or not 1 <= maximum_nesting_tests <= 10000000:
        raise ValueError("maximum_nesting_tests must be an integer from 1 to 10000000")
    return _decode_cylinder_caps(_build_cylinder_caps(face, origin, axis, x_direction, radius,
        angle_bounds, height_bounds, distance_tolerance, maximum_cells, negative, maximum_nesting_tests))


def inspect_cylinder_caps(handle):
    return _decode_cylinder_caps(_inspect_cylinder_caps(handle))


def trace_gyroid_cylinder_disks(face, origin, axis, x_direction, radius, angle_bounds,
                                height_bounds, distance_tolerance=.1, maximum_cells=512):
    """Disk contours, including interior loops, attached by accepted-cell/root IDs.

    Check disk_contours_verified. The parent resolved flag describes the side
    section; failed disk batches publish no cap curves. No native cap-region,
    cylindrical-face or solid validation follows from these polylines.
    """
    return _trace_gyroid_cylinder_disks(face, origin, axis, x_direction, radius, angle_bounds,
                                        height_bounds, distance_tolerance, maximum_cells)


def restrict_cylinder_local(face, origin, axis, x_direction, radius, height_bounds):
    """Native field-domain mask in field-local coordinates; no cap/trim/solid proof.

    Source geometry/instance placement is retained. The conservative cylinder
    enclosure must fit inside the computational box. Existing restrictions and
    child topology reject; schema-3 records preserve the new cylinder predicate.
    """
    return _restrict_cylinder_local(face, origin, axis, x_direction, radius, height_bounds)


def build_gyroid_cylinder_rings(face, origin, axis, x_direction, radius, angle_bounds,
                                height_bounds, distance_tolerance=.1, maximum_cells=512):
    """Native analytic cap-circle partitions with shared roots and sign intervals.

    Returns copied edge descriptors, not mutable Part shapes. The native result
    owns actual circle edges. ring_edges_verified is separate from cap topology
    and solid validation; uncertain root neighborhoods retain their brackets.
    """
    return _build_gyroid_cylinder_rings(face, origin, axis, x_direction, radius, angle_bounds,
                                        height_bounds, distance_tolerance, maximum_cells)


def trace_gyroid_cylinder_boundary(face, origin, axis, x_direction, radius, angle_bounds,
                                   height_bounds, distance_tolerance=.1, maximum_cells=512):
    """Full-turn curves and shared end-cap root descriptors from one native pass.

    Root IDs are snapshot-local, 1-based, ordered by height boundary then angle.
    Closed curves have endpoint IDs (0,0). Unresolved queries expose no anchors.
    This report does not expose mutable OCCT vertices or prove native trim/solids.
    """
    return _trace_gyroid_cylinder_boundary(face, origin, axis, x_direction, radius, angle_bounds,
                                           height_bounds, distance_tolerance, maximum_cells)


def trace_gyroid_cylinder(face, origin, axis, x_direction, radius, angle_bounds, height_bounds,
                          distance_tolerance=.1, maximum_cells=512, periodic=False):
    """Bounded open/full cylinder curves; no native trim/solid proof.

    Angles are radians, heights/radius/tolerance are model lengths. The whole
    conservative cylinder enclosure must fit in the mathematical field domain.
    Check resolved before consuming curves; ambiguous partial output is diagnostic.
    Explicit periodic=True requires angle_max == angle_min + 2*pi and shares
    seam root identity. It does not weld nearby endpoints or create trim topology.
    """
    if type(periodic) is not bool:
        raise TypeError("periodic must be an explicit bool")
    trace = _trace_gyroid_cylinder_periodic if periodic else _trace_gyroid_cylinder
    return trace(face, origin, axis, x_direction, radius, angle_bounds,
                 height_bounds, distance_tolerance, maximum_cells)


def trace_gyroid_plane(face, origin, normal, x_direction, u_bounds, v_bounds,
                       distance_tolerance=.1, maximum_cells=512, allow_exact_lattice_nodes=False):
    """Tolerance-bearing section curves PLUS explicit isolated point contacts.

    Exact lattice-node mode is opt-in: contacts must not be discarded merely
    because curves is empty. Unknown near-zeros remain unresolved. This returns
    no native trim topology, solid or persisted proof flags.
    """
    return _trace_gyroid_plane(face, origin, normal, x_direction, u_bounds, v_bounds,
                               distance_tolerance, maximum_cells, allow_exact_lattice_nodes)


def start_boundary_job(field, box, operation="common", tolerance=.1, maximum_cells=512,
                       corner_policy="reject"):
    """Private source preparation; no document/Part objects enter the worker."""
    if not isinstance(box, Part.Shape):
        raise TypeError("box must be a conventional Part.Shape")
    return start_boundary_job_from_record(field, box.exportBrepToString(), operation,
                                          tolerance, maximum_cells, corner_policy)


def start_boundary_job_from_record(field, box_record, operation="common", tolerance=.1,
                                   maximum_cells=512, corner_policy="reject"):
    """Submit an already captured conventional B-Rep record without copying/re-encoding it."""
    if not isinstance(box_record, str):
        raise TypeError("box_record must be a conventional B-Rep string")
    return _start_boundary_job(field, box_record, operation, tolerance, maximum_cells, corner_policy)


def take_boundary_job(job):
    return _decode_caps(_take_boundary_job(job))


def mixed_box(field, box, operation="common", tolerance=.1, maximum_cells=512,
              corner_policy="reject"):
    """Experimental F<=0 gyroid/axis-aligned Part box boundary, NOT a Part solid.

    Planar caps are independent conventional Part faces. The opaque native face
    retains shared seam topology internally; do not sew caps into a fake solid.
    Resolved open/closed contours share certified box-edge roots; ambiguous
    corner/tangent cases reject by default. Explicit regularized corner policy
    retains isolated-contact metadata in schema-2 topology/property persistence.
    Planar caps may contain multiple regions/holes; this is not solid validation.
    """
    if not isinstance(box, Part.Shape):
        raise TypeError("box must be a conventional Part.Shape")
    # Mesh/reference and solid factories retain explicit guards until their
    # whole-domain algorithms support the regularized corner policy.
    result = _mixed_box(field, box.exportBrepToString(), operation, tolerance, maximum_cells,
                        corner_policy)
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


def source_mixed_solids(handle):
    """Owned source-boundary snapshot, explicitly not the stored result solids."""
    return _decode_caps(_source_mixed_solids(handle))
