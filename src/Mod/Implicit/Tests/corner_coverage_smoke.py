# SPDX-License-Identifier: LGPL-2.1-or-later
"""Regularized clipped proximity, independent of native solid/contact proofs."""
import os
import traceback
import FreeCAD as App
import Part
import ImplicitOCCT as native


def check(report):
    assert report["boundary_proximity_resolved"], report
    assert 0 < report["boundary_to_mesh_bound"] <= .1
    assert 0 < report["mesh_to_boundary_bound"] <= .1
    assert report["regularized_field_cells"] > 0
    assert report["regularized_cap_cells"] > 0
    assert not report["topology_validated"] and not report["solid_validated"]
    assert not report["contact_audit_performed"]


def main():
    doc = App.newDocument("CornerCoverage")
    for period, low in ((10., (0., 0., 0.)), (5., (5., -5., 10.))):
        high = tuple(v + period for v in low)
        field = native.gyroid(period, 0, low, high)
        box = Part.makeBox(period, period, period, App.Vector(*low))
        for operation in ("common", "box_minus_field"):
            source = native.mixed_box(field, box, operation, corner_policy="regularized")
            handle = source["boundary_handle"]
            record = native.dumps_mixed(handle)
            report = native.check_mixed_coverage(handle)
            print("corner clipped proximity", period, low, operation, report, flush=True)
            check(report)
            assert native.dumps_mixed(handle) == record
            assert native.inspect_mixed(handle)["seam_bound_verified"]
            assert not native.tessellate_mixed(handle)["surface_coverage_verified"]
            if period == 10.:
                for args in ((handle, .1, 256, 1), (handle, .1, 256, 14, 1),
                             (handle, .1, 256, 14, 2000000, 1)):
                    assert not native.check_mixed_coverage(*args)["boundary_proximity_resolved"]
    # No document lifetime dependency or numerical retracing of stored topology.
    App.closeDocument(doc.Name)
    loaded = native.loads_mixed(record)["boundary_handle"]
    assert not native.inspect_mixed(loaded)["seam_bound_verified"]
    check(native.check_mixed_coverage(loaded))
    assert native.dumps_mixed(loaded) == record
    assert not native.inspect_mixed(loaded)["seam_bound_verified"]
    check(native.check_mixed_coverage(handle))
    print("native implicit corner clipped coverage smoke test passed", flush=True)


try:
    main()
except BaseException:
    traceback.print_exc()
    os._exit(1)
