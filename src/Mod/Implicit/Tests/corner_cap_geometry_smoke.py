# SPDX-License-Identifier: LGPL-2.1-or-later
"""Corner-aware native cap coverage, not topology or solid qualification."""
import os
import traceback
import FreeCAD as App
import Part
import ImplicitOCCT as native


def check(handle):
    report = native.check_mixed_cap_geometry(handle)
    assert report["cap_geometry_resolved"], report
    assert report["corner_policy"] == "regularized"
    assert report["boundary_bound"] <= .1
    assert report["mathematical_to_caps_bound"] <= .1
    assert report["caps_to_mathematical_bound"] + report["edge_vertex_deviation"] <= .1
    assert all(report["cells"]) and report["segment_tests"] > 0
    assert report["regularized_empty_cells"] > 0
    assert report["unresolved_side"] == report["unresolved_direction"] == -1
    assert not report["topology_validated"] and not report["solid_validated"]
    return report


def rejected(call):
    try:
        call()
    except (TypeError, ValueError, RuntimeError):
        return
    raise AssertionError("Invalid/unsupported cap geometry request accepted")


def main():
    face = native.gyroid(10, 0, (0, 0, 0), (10, 10, 10))
    for operation in ("common", "box_minus_field"):
        source = native.mixed_box(face, Part.makeBox(10, 10, 10), operation,
                                  corner_policy="regularized")
        handle = source["boundary_handle"]
        record = native.dumps_mixed(handle)
        check(handle)
        assert native.dumps_mixed(handle) == record
        assert native.inspect_mixed(handle)["seam_bound_verified"]
        for args in ((handle, .1, 16, 1), (handle, .1, 16, 2000000, 1), (handle, .1, 1)):
            limited = native.check_mixed_cap_geometry(*args)
            assert not limited["cap_geometry_resolved"] and limited["reason"]
            assert not limited["solid_validated"]
        loaded = native.loads_mixed(record)["boundary_handle"]
        check(loaded)
        assert not native.inspect_mixed(loaded)["seam_bound_verified"]
        doc = App.newDocument("CornerCapGeometry")
        obj = doc.addObject("Implicit::NativeFeaturePython", "Boundary")
        obj.Geometry = loaded
        owned = obj.Geometry
        App.closeDocument(doc.Name)
        check(owned)
        rejected(lambda: native.check_mixed_cap_geometry(handle, 0))
    rejected(lambda: native.check_mixed_cap_geometry(face))
    print("native implicit corner cap geometry smoke test passed", flush=True)


try:
    main()
except BaseException:
    traceback.print_exc()
    os._exit(1)
