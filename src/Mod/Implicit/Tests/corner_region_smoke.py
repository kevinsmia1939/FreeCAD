# SPDX-License-Identifier: LGPL-2.1-or-later
"""Closed corner reference and strict material grouping, not native CAD solids."""
from collections import Counter
import math
import os
import traceback
import FreeCAD as App
import ImplicitOCCT as native
import Part


def check(report, surface, operation):
    assert report["whole_box_homotopy_resolved"] and report["surface_reference_manifold"]
    assert report["closed_reference_manifold"], report["reason"]
    for flag in ("stored_trim_correspondence_validated", "native_shell_constructed",
                 "topology_validated", "solid_validated", "geometry_accuracy_verified"):
        assert not report[flag]
    assert report["corner_policy"] == "regularized" and report["fixed_corner_count"] == 8
    assert report["surface_point_contacts"] == surface["point_contacts"]
    assert report["resolution"] == 31 and report["reference_region_count"] == 1
    assert report["reference_component_euler"] == [-2]
    assert report["reference_component_regions"] == [0]
    points, triangles = report["reference_vertices"], report["reference_triangles"]
    count, faces = report["reference_implicit_vertex_count"], report["reference_implicit_triangle_count"]
    assert points[:count] == surface["reference_vertices"]
    assert triangles[:faces] == surface["reference_triangles"]
    excluded = (0., 0., 0.) if operation == "common" else (10., 10., 10.)
    retained = (10., 10., 10.) if operation == "common" else (0., 0., 0.)
    assert excluded not in points and points.count(retained) == 1
    assert points.index(retained) >= count
    edges, directed, caps = Counter(), Counter(), set()
    volumes = []
    for i, (a, b, c) in enumerate(triangles):
        assert len({a, b, c}) == 3
        for x, y in ((a, b), (b, c), (c, a)):
            edges[tuple(sorted((x, y)))] += 1
            directed[x, y] += 1
        p, q, r = (App.Vector(points[n]) for n in (a, b, c))
        side = report["reference_triangle_sides"][i]
        if i < faces:
            assert side == -1
        else:
            assert 0 <= side < 6
            normal = (q - p).cross(r - p)
            assert normal[side // 2] * (1 if side % 2 else -1) > 0
            caps.update((a, b, c))
        center = App.Vector(5, 5, 5)
        volumes.append((p - center).dot((q - center).cross(r - center)) / 6)
    assert all(n == 2 for n in edges.values())
    assert all(directed[a, b] == directed[b, a] == 1 for a, b in edges)
    assert len(points) - len(edges) + len(triangles) == -2
    for i, (a, b) in enumerate(surface["reference_grid_edges"]):
        if a == b:
            assert i in caps  # Actual shared ID, not a coordinate-welded cap copy.
    volume = math.fsum(volumes)
    assert abs(volume - 500.) < 1e-8
    assert abs(volume - report["reference_region_volumes"][0]) < 1e-8
    return volume


def rejected(call):
    try:
        call()
    except (ValueError, TypeError, RuntimeError):
        return
    raise AssertionError("unsupported native attachment/solid consumer accepted")


def main():
    face = native.gyroid(10, 0, (0, 0, 0), (10, 10, 10))
    before = native.dumps(face)
    box = Part.makeBox(10, 10, 10)
    total = 0.
    for operation in ("common", "box_minus_field"):
        source = native.mixed_box(face, box, operation, corner_policy="regularized")
        handle = source["boundary_handle"]
        record = native.dumps_mixed(handle)
        surface = native.check_mixed_topology(handle)
        report = native.check_mixed_region_topology(handle)
        total += check(report, surface, operation)
        loaded = native.loads_mixed(record)
        check(native.check_mixed_region_topology(loaded["boundary_handle"]), surface, operation)
        assert not native.inspect_mixed(loaded["boundary_handle"])["seam_bound_verified"]
        assert native.inspect_mixed(handle)["seam_bound_verified"]
        assert native.dumps_mixed(handle) == record
        limited = native.check_mixed_region_topology(handle, 32, 16, 1)
        assert not limited["closed_reference_manifold"] and not limited["native_shell_constructed"]
        rejected(lambda: native.check_mixed_region_topology(handle, 32, 16, 4000000, "reject"))
        assert native.check_mixed_cap_attachment(handle)["cap_regions_attached"]
        rejected(lambda: native.build_mixed_solids(handle))
        doc = App.newDocument("CornerRegionReference")
        obj = doc.addObject("Implicit::NativeFeaturePython", "Boundary")
        obj.Geometry = loaded["boundary_handle"]
        owned = obj.Geometry
        App.closeDocument(doc.Name)
        assert native.check_mixed_region_topology(owned)["closed_reference_manifold"]
    assert abs(total - 1000.) < 1e-8
    raw = native.check_box_region_topology(face, 32, 16, 4000000, "regularized")
    assert raw["closed_reference_manifold"] and raw["reference_component_euler"] == [-2]
    raw_restored = native.loads(before)
    assert native.check_box_region_topology(raw_restored, 32, 16, 4000000, "regularized")["closed_reference_manifold"]
    assert not native.check_box_region_topology(face)["closed_reference_manifold"]
    assert native.dumps(face) == before
    print("native implicit corner region smoke test passed", flush=True)


try:
    main()
except BaseException:
    traceback.print_exc()
    os._exit(1)
