# SPDX-License-Identifier: LGPL-2.1-or-later
"""Stored corner graph/cap-region correspondence, not trim-cycle or solid validity."""
import os
import traceback
import FreeCAD as App
import ImplicitOCCT as native
import Part


def check(handle, face, operation):
    graph = native.check_mixed_correspondence(handle)
    assert graph["stored_graph_correspondence_resolved"], graph
    assert graph["field_box_regularity_resolved"]
    assert graph["corner_policy"] == "regularized"
    assert graph["regularity_policy"] == "fixed_corner_homotopy"
    assert (graph["matched_edges"], graph["matched_vertices"], graph["matched_caps"],
            graph["matched_wires"]) == (30, 19, 12, 1)
    assert graph["minimum_tangent_alignment"] > 0
    assert graph["curve_deviation_bound"] <= graph["matching_tolerance"]
    assert graph["cap_parameter_deviation_bound"] <= graph["matching_tolerance"]
    assert not graph["topology_validated"] and not graph["solid_validated"]
    report = native.check_mixed_cap_attachment(handle)
    assert report["cap_regions_attached"], report
    assert report["stored_graph_correspondence_resolved"] and report["region_reference_resolved"]
    assert report["corner_policy"] == "regularized" and report["reference_resolution"] == 31
    assert (report["reference_cap_count"], report["reference_shell_count"],
            report["reference_region_count"]) == (12, 1, 1)
    assert set(report["reference_caps"]) == set(range(12))
    assert report["reference_shells"] == report["reference_regions"] == [0] * 12
    for flag in ("trim_wire_attachment_validated", "topology_validated", "solid_validated",
                 "native_shell_constructed"):
        assert not report[flag]
    caps = native.inspect_mixed(handle)["planar_caps"]
    sign = -1 if operation == "common" else 1
    for cap, point, clearance in zip(caps, report["witness_points"], report["boundary_clearance_bounds"]):
        assert clearance > report["required_clearance"] > 0
        assert sign * native.value(face, point) > 0
        vertex = Part.Vertex(App.Vector(point))
        assert cap.distToShape(vertex)[0] < 1e-8
        distance = min(edge.distToShape(vertex)[0] for edge in cap.Edges)
        assert distance + 1e-8 >= clearance


def rejected(call):
    try:
        call()
    except (ValueError, TypeError, RuntimeError):
        return
    raise AssertionError("unsupported native trim/shell/solid consumer accepted")


def main():
    face = native.gyroid(10, 0, (0, 0, 0), (10, 10, 10))
    before = native.dumps(face)
    box = Part.makeBox(10, 10, 10)
    for operation in ("common", "box_minus_field"):
        result = native.mixed_box(face, box, operation, corner_policy="regularized")
        handle = result["boundary_handle"]
        record = native.dumps_mixed(handle)
        check(handle, face, operation)
        loaded = native.loads_mixed(record)
        check(loaded["boundary_handle"], face, operation)
        assert not native.inspect_mixed(loaded["boundary_handle"])["seam_bound_verified"]
        assert native.inspect_mixed(handle)["seam_bound_verified"]
        assert native.dumps_mixed(handle) == record
        limited = native.check_mixed_correspondence(handle, 512, 1)
        assert not limited["stored_graph_correspondence_resolved"] and limited["reason"]
        limited = native.check_mixed_cap_attachment(handle, 32, 16, 4000000, 1)
        assert not limited["cap_regions_attached"] and limited["reason"]
        rejected(lambda: native.build_mixed_solids(handle))
        doc = App.newDocument("CornerCapAttachment")
        obj = doc.addObject("Implicit::NativeFeaturePython", "Boundary")
        obj.Geometry = loaded["boundary_handle"]
        owned = obj.Geometry
        App.closeDocument(doc.Name)
        assert native.check_mixed_cap_attachment(owned)["cap_regions_attached"]
    assert native.dumps(face) == before
    print("native implicit corner attachment smoke test passed", flush=True)


try:
    main()
except BaseException:
    traceback.print_exc()
    os._exit(1)
