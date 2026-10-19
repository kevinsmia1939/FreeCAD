# SPDX-License-Identifier: LGPL-2.1-or-later
"""Corner-aware complete directed trim cycles, not whole-face/native-solid validity."""
from collections import Counter
import os
import traceback
import FreeCAD as App
import ImplicitOCCT as native
import Part


def check(handle):
    source = native.inspect_mixed(handle)
    assert source["surface_domain_exclusion_count"] == 2
    face = source["implicit_face"]
    assert not native.in_domain(face, (0, 0, 0))
    assert not native.in_domain(face, (10, 10, 10))
    assert native.in_domain(face, (10, 0, 0))
    assert native.in_domain(face, (5, 5, 5))
    placed = native.translated(face, (2, 3, 4))
    assert not native.in_domain(placed, (2, 3, 4))
    assert not native.in_domain(placed, (12, 13, 14))
    assert native.in_domain(placed, (12, 3, 4))
    report = native.check_mixed_trim_attachment(handle)
    assert report["trim_wires_attached"], report
    assert report["cap_regions_attached"] and report["complement_cap_regions_attached"]
    assert report["corner_policy"] == "regularized" and report["reference_resolution"] == 31
    assert (report["reference_arc_count"], report["reference_wire_count"],
            report["reference_surface_component_count"]) == (18, 1, 1)
    assert sorted(report["seam_reference_arcs"]) == list(range(18))
    assert report["wire_reference_loops"] == report["wire_surface_components"] == [0]
    assert report["surface_component_euler"] == [-3]
    assert report["surface_component_shells"] == report["surface_component_regions"] == [0]
    for flag in ("implicit_face_attachment_validated", "topology_validated",
                 "native_shell_constructed", "solid_validated"):
        assert not report[flag]
    pairs = [source["edge_vertices"][i] for i in source["seam_edges"]]
    degree = Counter(n for pair in pairs for n in pair)
    assert len(pairs) == len(degree) == 18 and set(degree.values()) == {2}
    neighbors = {n: set() for n in degree}
    for a, b in pairs:
        neighbors[a].add(b)
        neighbors[b].add(a)
    seen, todo = set(), [next(iter(degree))]
    while todo:
        n = todo.pop()
        if n not in seen:
            seen.add(n)
            todo.extend(neighbors[n])
    assert len(seen) == 18
    corners = {tuple(source["vertex_points"][n]) for n in degree
               if all(x in (0., 10.) for x in source["vertex_points"][n])}
    assert len(corners) == 6 and (0., 0., 0.) not in corners and (10., 10., 10.) not in corners
    reference = native.check_mixed_topology(handle)
    loop = reference["reference_boundary_loops"][0]
    ref_corners = {tuple(reference["reference_vertices"][n]) for n in loop
                   if all(x in (0., 10.) for x in reference["reference_vertices"][n])}
    assert ref_corners == corners
    return report


def main():
    face = native.gyroid(10, 0, (0, 0, 0), (10, 10, 10))
    box = Part.makeBox(10, 10, 10)
    for operation in ("common", "box_minus_field"):
        source = native.mixed_box(face, box, operation, corner_policy="regularized")
        handle = source["boundary_handle"]
        record = native.dumps_mixed(handle)
        report = check(handle)
        loaded = native.loads_mixed(record)
        again = check(loaded["boundary_handle"])
        assert again["seam_reference_arcs"] == report["seam_reference_arcs"]
        assert not native.inspect_mixed(loaded["boundary_handle"])["seam_bound_verified"]
        assert native.inspect_mixed(handle)["seam_bound_verified"]
        assert native.dumps_mixed(handle) == record
        limited = native.check_mixed_trim_attachment(handle, 32, 16, 1)
        assert not limited["trim_wires_attached"] and limited["reason"]
        doc = App.newDocument("CornerTrimAttachment")
        obj = doc.addObject("Implicit::NativeFeaturePython", "Boundary")
        obj.Geometry = loaded["boundary_handle"]
        owned = obj.Geometry
        App.closeDocument(doc.Name)
        assert native.check_mixed_trim_attachment(owned)["trim_wires_attached"]
    print("native implicit corner trim smoke test passed", flush=True)


try:
    main()
except BaseException:
    traceback.print_exc()
    os._exit(1)
