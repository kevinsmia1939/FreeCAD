# SPDX-License-Identifier: LGPL-2.1-or-later
"""Mesh-independent box-stratified field regularity, not trim/solid validation."""
import math
import traceback
import FreeCAD as App
import ImplicitMixed
import ImplicitOCCT as native


def check(report):
    assert report["field_box_regularity_resolved"]
    assert not report["trim_correspondence_validated"]
    assert not report["topology_validated"] and not report["solid_validated"]
    assert report["unresolved_dimension"] == -1 and report["hessian_bound"] > 0
    assert len(report["strata"]) == 4
    assert all(s["complete"] and s["visited"] > 0 for s in report["strata"])
    assert report["strata"][0]["excluded"] == 8
    assert report["strata"][3]["minimum_projected_gradient"] > 0
    assert report["strata"][2]["minimum_projected_gradient"] > 0


def main():
    for crossing in (False, True):
        obj = ImplicitMixed.demo(open_contours=crossing)
        doc = obj.Document
        for operation in ("Common", "BoxMinusField"):
            obj.Operation = operation
            doc.recompute()
            handle = obj.Geometry
            record = native.dumps_mixed(handle)
            report = native.check_mixed_regularity(handle)
            print("native stratified regularity", crossing, operation, report)
            check(report)
            face = native.inspect_mixed(handle)["implicit_face"]
            assert native.check_box_regularity(face) == report
            assert native.dumps_mixed(handle) == record
            limited = native.check_mixed_regularity(handle, 14, 1)
            assert not limited["field_box_regularity_resolved"]
            assert not limited["solid_validated"]
        App.closeDocument(doc.Name)
    check(native.check_mixed_regularity(handle))
    restored = native.loads_mixed(record)
    assert not restored["seam_bound_verified"]
    check(native.check_mixed_regularity(restored["boundary_handle"]))
    k = 2 * math.pi / 10
    x, y = .4/k, .6/k
    z = math.atan2(math.cos(.4), math.sin(.6))/k
    iso = math.sin(.4)*math.cos(.6)+math.hypot(math.sin(.6), math.cos(.4))
    for level, low, high, dimension in (
            (1.5, (.7,.8,.9), (1.8,1.9,2), 3),
            (1, (-.5,2,1.8), (.5,3,2.5), 2),
            (iso, (x,y,z-.05), (x+.05,y+.05,z+.05), 1),
            (0, (0,0,0), (.2,.3,.4), 0)):
        face = native.gyroid(10, level, low, high, .001)
        report = native.check_box_regularity(face)
        assert not report["field_box_regularity_resolved"]
        assert report["unresolved_dimension"] == dimension
        assert all(report["strata"][d]["complete"] for d in range(dimension+1, 4))
    for call, args, error in (
            (native.check_mixed_regularity, (None,), TypeError),
            (native.check_mixed_regularity, (handle,0), ValueError),
            (native.check_mixed_regularity, (handle,14,0), ValueError),
            (native.check_box_regularity, (native.sphere((0,0,0),1),), NotImplementedError),
            (native.check_box_regularity, (native.translated(face,(1,0,0)),), NotImplementedError)):
        try:
            call(*args)
        except error:
            pass
        else:
            raise AssertionError("unsupported regularity query accepted")
    print("native implicit mixed stratified regularity smoke test passed")


try:
    main()
except Exception:
    traceback.print_exc()
    raise
