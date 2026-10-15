# SPDX-License-Identifier: LGPL-2.1-or-later
"""Experimental local implicit-to-B-spline bridge, not whole-solid conversion."""
import math
import FreeCAD as App
import Implicit
import Part


def fit_patch(feature, seed, width, height, depth, point_count=9,
              validation_count=17, field_tolerance=1e-5,
              normal_tolerance_degrees=2.0, distance_tolerance=1e-9,
              minimum_alignment=0.2, ray_samples=128, cancellation_token=None):
    """Return a local-coordinate open B-spline face only after sampled checks.

    Field/normal checks are sampled, not a geometric error or coverage certificate.
    No document object, file or manufacturing solid is created by this function.
    """
    if isinstance(validation_count, bool) or not isinstance(validation_count, int) \
            or not 5 <= validation_count <= 65:
        raise ValueError("validation_count must be an integer in 5..65")
    if not math.isfinite(field_tolerance) or field_tolerance <= 0 \
            or not math.isfinite(normal_tolerance_degrees) or not 0 < normal_tolerance_degrees < 90:
        raise ValueError("positive finite field tolerance and normal tolerance in (0,90) required")
    def sources_ready():
        return all(obj.isValid() and "Touched" not in obj.State
                   for obj in [feature] + feature.OutListRecursive)

    if not sources_ready():
        raise ValueError("source or dependency is invalid/touched; recompute before fitting")
    def check_cancelled():
        if cancellation_token is not None and Implicit.isCancelled(cancellation_token):
            raise RuntimeError("implicit operation cancelled")

    check_cancelled()
    revision = feature.CacheRevision
    chart = Implicit.sampleChart(feature, tuple(seed), width, height, depth,
                                 point_count, ray_samples, distance_tolerance,
                                 minimum_alignment, cancellation_token)
    surface = Part.BSplineSurface()
    surface.interpolate([[App.Vector(*p) for p in row] for row in chart["points"]])
    check_cancelled()
    face = surface.toShape()
    if face.isNull() or not face.isValid() or face.ShapeType != "Face":
        raise ValueError("OCCT produced an invalid local B-spline face")
    u0, u1, v0, v1 = face.ParameterRange
    points = []
    parameters = []
    for u in range(validation_count):
        check_cancelled()
        for v in range(validation_count):
            uv = (u0 + (u1 - u0) * u / (validation_count - 1),
                  v0 + (v1 - v0) * v / (validation_count - 1))
            parameters.append(uv)
            points.append(tuple(face.valueAt(*uv)))
    bounds = Implicit.bounds(feature)
    if any(not all(bounds[0][axis] <= p[axis] <= bounds[1][axis] for axis in range(3)) for p in points):
        raise ValueError("fitted patch leaves the source domain at validation samples")
    residual = max(abs(value) for value in Implicit.evaluateBatch(feature, points))
    max_angle = 0.0
    axis = App.Vector(*chart["normal"])
    for point, uv in zip(points, parameters):
        check_cancelled()
        gradient = App.Vector(*Implicit.gradient(feature, *point))
        normal = face.normalAt(*uv)
        if not math.isfinite(gradient.Length) or not math.isfinite(normal.Length) \
                or gradient.Length == 0 or normal.Length == 0:
            raise ValueError("critical point or singular fitted normal")
        gradient.normalize()
        normal.normalize()
        if normal.dot(axis) < minimum_alignment:
            raise ValueError("fitted chart folds or reverses at validation samples")
        cosine = max(-1.0, min(1.0, normal.dot(gradient)))
        max_angle = max(max_angle, math.degrees(math.acos(cosine)))
    if residual > field_tolerance or max_angle > normal_tolerance_degrees:
        raise ValueError("patch sampled checks failed: field residual " + str(residual)
                         + ", normal angle " + str(max_angle))
    if feature.CacheRevision != revision or not sources_ready():
        raise ValueError("source changed during fitting; discard the approximation and retry")
    check_cancelled()
    report = {
        "schema": 1,
        "representation": "local_bspline_open_face",
        "source_document": feature.Document.Name,
        "source_object": feature.Name,
        "source_revision": revision,
        "seed": tuple(seed),
        "width": width, "height": height, "depth": depth,
        "point_count": point_count, "validation_count": validation_count,
        "distance_tolerance": distance_tolerance,
        "minimum_alignment": minimum_alignment, "ray_samples": ray_samples,
        "chart_center": chart["center"],
        "chart_u_axis": chart["u_axis"], "chart_v_axis": chart["v_axis"],
        "chart_normal": chart["normal"],
        "field_tolerance": field_tolerance,
        "normal_tolerance_degrees": normal_tolerance_degrees,
        "max_sampled_field_residual": residual,
        "max_sampled_normal_angle_degrees": max_angle,
        "max_chart_residual": chart["max_residual"],
        "coordinate_frame": "feature_local",
        "surface_coverage_verified": False,
        "manufacturing_solid": False,
    }
    return {"face": face, "chart": chart, "report": report}
