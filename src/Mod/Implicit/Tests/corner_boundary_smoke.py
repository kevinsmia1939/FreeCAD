# SPDX-License-Identifier: LGPL-2.1-or-later
"""Default gyroid native trim graph and policy-aware I/O, not a qualified solid."""
import os
import traceback
import FreeCAD as App
import Part
import ImplicitOCCT as native


def rejected(call):
    try:
        call()
    except (ValueError, TypeError, RuntimeError):
        return
    raise AssertionError("unsupported policy/consumer accepted")


def main():
    face = native.gyroid(10, 0, (0, 0, 0), (10, 10, 10))
    record = native.dumps(face)
    box = Part.makeBox(10, 10, 10)
    before = box.exportBrepToString()
    for operation in ("common", "box_minus_field"):
        result = native.mixed_box(face, box, operation, corner_policy="regularized")
        assert result["corner_policy"] == "regularized"
        assert result["exact_corner_count"] == 8
        assert result["corner_contour_ends"] == result["planar_corner_contacts"] == 12
        excluded = (0., 0., 0.) if operation == "common" else (10., 10., 10.)
        assert result["excluded_corner_contacts"] == [excluded]
        assert result["seam_count"] == 18 and result["box_edge_root_count"] == 12
        assert len(result["edge_points"]) == 30 and len(result["vertex_points"]) == 19
        assert excluded not in result["vertex_points"]
        assert result["seam_bound_verified"] and result["seam_geometric_bound"] <= .1
        assert not result["solid_validated"]
        assert all(cap.isValid() for cap in result["planar_caps"])
        handle = result["boundary_handle"]
        inspected = native.inspect_mixed(handle)
        assert inspected["edge_vertices"] == result["edge_vertices"]
        assert inspected["excluded_corner_contacts"] == [excluded]
        restored = native.loads_mixed(native.dumps_mixed(handle))
        assert restored["corner_policy"] == "regularized"
        assert restored["excluded_corner_contacts"] == [excluded]
        assert not restored["seam_bound_verified"]
        query = native.classify_mixed(handle, excluded)
        assert query["state"] == "outside" and query["distance_lower_bound"] > .1
        assert query["corner_policy"] == "regularized" and not query["solid_validated"]
        rejected(lambda: native.build_mixed_shells(handle))
        rejected(lambda: native.build_mixed_solids(handle))
        doc = App.newDocument("CornerPolicyGuard")
        obj = doc.addObject("Implicit::NativeFeaturePython", "Boundary")
        obj.Geometry = handle
        assert native.inspect_mixed(obj.Geometry)["corner_policy"] == "regularized"
        App.closeDocument(doc.Name)
        assert native.inspect_mixed(handle)["corner_policy"] == "regularized"
        rejected(lambda: native.mixed_box(face, box, operation))
        rejected(lambda: native.mixed_box(face, box, operation, maximum_cells=4,
                                          corner_policy="regularized"))
    rejected(lambda: native.mixed_box(face, box, corner_policy="guess"))
    restored = native.loads(record)
    assert native.mixed_box(restored, box, corner_policy="regularized")["exact_corner_count"] == 8
    assert native.dumps(face) == record and box.exportBrepToString() == before
    print("native implicit corner boundary smoke test passed", flush=True)


try:
    main()
except BaseException:
    traceback.print_exc()
    os._exit(1)
