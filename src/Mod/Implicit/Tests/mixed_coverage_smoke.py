# SPDX-License-Identifier: LGPL-2.1-or-later
"""Whole-domain clipped-boundary proximity, NOT topology/solid validation."""
import traceback
import FreeCAD as App
import ImplicitMixed
import ImplicitOCCT as native


def check(report):
    assert report["boundary_proximity_resolved"]
    assert 0 < report["boundary_to_mesh_bound"] <= .1
    assert 0 < report["mesh_to_boundary_bound"] <= .1
    assert report["spatial_cells"] > 0 and report["triangle_patches"] > 0
    assert not report["topology_validated"] and not report["solid_validated"]
    assert not report["contact_audit_performed"]


def main():
    for crossing in (False, True):
        obj = ImplicitMixed.demo(open_contours=crossing)
        doc = obj.Document
        for operation in ("Common", "BoxMinusField"):
            obj.Operation = operation
            doc.recompute()
            handle = obj.Geometry
            record = native.dumps_mixed(handle)
            report = native.check_mixed_coverage(handle)
            print("native clipped proximity", crossing, operation, report)
            check(report)
            assert native.dumps_mixed(handle) == record
            for args in ((handle, .1, 256, 1), (handle, .1, 256, 14, 1),
                         (handle, .1, 256, 14, 2000000, 1)):
                limited = native.check_mixed_coverage(*args)
                assert not limited["boundary_proximity_resolved"] and not limited["solid_validated"]
        App.closeDocument(doc.Name)
    restored = native.loads_mixed(record)
    assert not restored["seam_bound_verified"]
    check(native.check_mixed_coverage(restored["boundary_handle"]))
    check(native.check_mixed_coverage(handle))  # owned lifetime after document closure
    for args, error in (((None,), TypeError), ((handle, .1, 256, 0), ValueError),
                        ((handle, .1, 256, 14, 0), ValueError)):
        try:
            native.check_mixed_coverage(*args)
        except error:
            pass
        else:
            raise AssertionError("invalid coverage query accepted")
    print("native implicit mixed clipped coverage smoke test passed")


try:
    main()
except Exception:
    traceback.print_exc()
    raise
