# SPDX-License-Identifier: LGPL-2.1-or-later
"""Whole-box corner homotopy/reference, not stored attachment or native solids."""
from collections import Counter
import os
import traceback
import FreeCAD as App
import ImplicitOCCT as native
import Part


def check(report):
    assert report["whole_box_homotopy_resolved"] and report["reference_manifold"], report["reason"]
    for flag in ("stored_trim_correspondence_validated", "topology_validated", "solid_validated",
                 "geometry_accuracy_verified"):
        assert not report[flag]
    assert report["corner_policy"] == "regularized" and report["fixed_corner_count"] == 8
    assert report["resolution"] == 31
    points, triangles = report["reference_vertices"], report["reference_triangles"]
    origins = report["reference_grid_edges"]
    assert len(origins) == len(points) == len(set(origins))
    assert sum(a == b for a, b in origins) == 6
    assert report["point_contacts"] == [(0., 0., 0.), (10., 10., 10.)]
    assert all(p not in points for p in report["point_contacts"])
    parent = list(range(len(points)))

    def root(n):
        while parent[n] != n:
            parent[n] = parent[parent[n]]
            n = parent[n]
        return n

    edges, directed = Counter(), Counter()
    for a, b, c in triangles:
        assert len({a, b, c}) == 3
        assert (App.Vector(points[b]) - App.Vector(points[a])).cross(
            App.Vector(points[c]) - App.Vector(points[a])).Length > 0
        for x, y in ((a, b), (b, c), (c, a)):
            edges[tuple(sorted((x, y)))] += 1
            directed[x, y] += 1
            parent[root(x)] = root(y)
    assert all(n in (1, 2) for n in edges.values())
    for (a, b), n in edges.items():
        if n == 2:
            assert directed[a, b] == directed[b, a] == 1
    boundary = {(a, b) for (a, b), n in directed.items() if edges[tuple(sorted((a, b)))] == 1}
    paths = report["reference_boundary_loops"]
    assert paths and all(path[0] == path[-1] for path in paths)
    assert boundary == {(a, b) for path in paths for a, b in zip(path, path[1:])}
    euler = Counter(root(n) for n in range(len(points)))
    for a, b in edges:
        euler[root(a)] -= 1
    for a, b, c in triangles:
        euler[root(a)] += 1
    assert sorted(euler.values()) == report["reference_component_euler"]


def rejected(call):
    try:
        call()
    except (ValueError, TypeError, RuntimeError):
        return
    raise AssertionError("unsupported topology policy accepted")


def main():
    face = native.gyroid(10, 0, (0, 0, 0), (10, 10, 10))
    before = native.dumps(face)
    report = native.check_box_topology(face, 32, 16, 4000000, "regularized")
    check(report)
    restored_face = native.loads(before)
    check(native.check_box_topology(restored_face, 32, 16, 4000000, "regularized"))
    legacy = native.check_box_topology(face)
    assert not legacy["whole_box_homotopy_resolved"] and legacy["corner_policy"] == "reject"
    limited = native.check_box_topology(face, 32, 16, 1, "regularized")
    assert not limited["whole_box_homotopy_resolved"]
    box = Part.makeBox(10, 10, 10)
    for operation in ("common", "box_minus_field"):
        source = native.mixed_box(face, box, operation, corner_policy="regularized")
        handle = source["boundary_handle"]
        record = native.dumps_mixed(handle)
        check(native.check_mixed_topology(handle))
        restored = native.loads_mixed(record)
        check(native.check_mixed_topology(restored["boundary_handle"]))
        assert not native.inspect_mixed(restored["boundary_handle"])["seam_bound_verified"]
        assert native.dumps_mixed(handle) == record
        rejected(lambda: native.check_mixed_topology(handle, 32, 16, 4000000, "reject"))
        region = native.check_mixed_region_topology(handle)
        assert region["closed_reference_manifold"] and not region["native_shell_constructed"]
        rejected(lambda: native.build_mixed_shells(handle))
    rejected(lambda: native.check_box_topology(face, 32, 16, 4000000, "guess"))
    assert native.dumps(face) == before
    print("corner reference", report["reference_component_euler"],
          "loops", len(report["reference_boundary_loops"]),
          "nodes", len(report["reference_vertices"]), flush=True)
    print("native implicit corner topology smoke test passed", flush=True)


try:
    main()
except BaseException:
    traceback.print_exc()
    os._exit(1)
