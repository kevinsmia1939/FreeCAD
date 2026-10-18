# SPDX-License-Identifier: LGPL-2.1-or-later
"""Regularized region queries use real corner material, including placed owners."""
import os
import tempfile
import traceback
import FreeCAD as App
import Implicit
import ImplicitOCCT as native
import Part


def check(snapshot, pose, local, state):
    point = pose.multVec(App.Vector(local))
    result = Implicit.classifyNative(snapshot, tuple(point), .1)
    assert result["state"] == state, result
    assert result["placement_resolved"] and not result["solid_validated"]
    if state == "outside":
        assert result["distance_lower_bound"] > .1
        assert not result["has_boundary_witness"]
    else:
        assert result["has_boundary_witness"]
        assert result["witness_distance_upper_bound"] <= .1
        assert (App.Vector(result["witness_first"]) - point).Length <= .1


def main():
    face = native.gyroid(10, 0, (0, 0, 0), (10, 10, 10))
    box = Part.makeBox(10, 10, 10)
    doc = App.newDocument("CornerClassification")
    obj = doc.addObject("Implicit::NativeFeaturePython", "Boundary")
    for operation in ("common", "box_minus_field"):
        source = native.mixed_box(face, box, operation, corner_policy="regularized")
        handle = source["boundary_handle"]
        before = native.dumps_mixed(handle)
        excluded = 0 if operation == "common" else 7
        for index in range(8):
            point = tuple(10. if index & (1 << axis) else 0. for axis in range(3))
            result = native.classify_mixed(handle, point)
            assert result["corner_policy"] == "regularized" and not result["solid_validated"]
            assert result["state"] == ("outside" if index == excluded else "near_boundary"), result
            if index == excluded:
                assert result["distance_lower_bound"] > .1 and not result["has_boundary_witness"]
                coarse = native.classify_mixed(handle, point, 1)
                assert coarse["state"] == "unresolved" and not coarse["has_boundary_witness"]
            else:
                assert result["witness_first"] == result["witness_last"] == point
        loaded = native.loads_mixed(before)
        p = (0., 0., 0.) if excluded == 0 else (10., 10., 10.)
        assert native.classify_mixed(loaded["boundary_handle"], p)["state"] == "outside"
        obj.Geometry = loaded["boundary_handle"]
        check(Implicit.nativeGeometry(obj), App.Placement(), p, "outside")
        assert not native.inspect_mixed(obj.Geometry)["seam_bound_verified"]
        assert native.dumps_mixed(handle) == before
        assert native.inspect_mixed(handle)["seam_bound_verified"]
    # Last snapshot is the cut: max corner excluded, min corner retained.
    obj.Placement = App.Placement(App.Vector(17, -4, 3), App.Rotation(App.Vector(1, 2, 3), 31))
    parent = doc.addObject("App::Part", "Container")
    parent.addObject(obj)
    parent.Placement = App.Placement(App.Vector(2, 7, -3), App.Rotation(23, 0, 0))
    link = doc.addObject("App::Link", "Instance")
    link.LinkedObject = parent
    link.LinkTransform = True
    link.LinkPlacement = App.Placement(App.Vector(-6, 1, 9), App.Rotation(0, 17, 0))
    pose = link.LinkPlacement.multiply(parent.Placement.multiply(obj.Placement))
    owned = link.getSubObject(obj.Name + ".")
    check(owned, pose, (10, 10, 10), "outside")
    check(owned, pose, (0, 0, 0), "near_boundary")
    with tempfile.TemporaryDirectory(prefix="implicit-corner-query-") as directory:
        filename = os.path.join(directory, "query.FCStd")
        doc.recompute()
        doc.saveAs(filename)
        App.closeDocument(doc.Name)
        reopened = App.openDocument(filename)
        check(reopened.Instance.getSubObject("Boundary."), pose, (10, 10, 10), "outside")
        check(reopened.Instance.getSubObject("Boundary."), pose, (0, 0, 0), "near_boundary")
        App.closeDocument(reopened.Name)
    check(owned, pose, (10, 10, 10), "outside")
    print("native implicit corner classification smoke test passed", flush=True)


try:
    main()
except BaseException:
    traceback.print_exc()
    os._exit(1)
