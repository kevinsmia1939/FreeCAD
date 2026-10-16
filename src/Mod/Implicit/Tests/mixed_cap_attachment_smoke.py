# SPDX-License-Identifier: LGPL-2.1-or-later
"""Stored conventional cap regions attach by common retained points, not counts."""
import traceback
import FreeCAD as App
import Part
import ImplicitMixed
import ImplicitOCCT as native


def check(handle, report):
    assert report["cap_regions_attached"], report["reason"]
    assert report["stored_graph_correspondence_resolved"] and report["region_reference_resolved"]
    assert report["reason"] == "cap_regions_attached"
    for key in ("trim_wire_attachment_validated","topology_validated","solid_validated","native_shell_constructed"):
        assert not report[key]
    caps = native.inspect_mixed(handle)["planar_caps"]
    assert len(caps) == report["reference_cap_count"] == len(report["witness_points"])
    assert set(report["reference_caps"]) == set(range(len(caps)))
    assert all(0 <= x < report["reference_shell_count"] for x in report["reference_shells"])
    assert all(0 <= x < report["reference_region_count"] for x in report["reference_regions"])
    for cap, point, clearance in zip(caps,report["witness_points"],report["boundary_clearance_bounds"]):
        assert clearance > report["required_clearance"] > 0
        vertex = Part.Vertex(App.Vector(*point))
        assert cap.distToShape(vertex)[0] < 1.e-8
        # Independent conventional edge-distance evaluation of the clearance.
        distance = min(edge.distToShape(vertex)[0] for edge in cap.Edges)
        assert distance + 1.e-8 >= clearance


def main():
    for crossing in (False,True):
        obj = ImplicitMixed.demo(open_contours=crossing)
        doc = obj.Document
        for operation in ("Common","BoxMinusField"):
            obj.Operation = operation
            doc.recompute()
            handle = obj.Geometry
            record = native.dumps_mixed(handle)
            report = native.check_mixed_cap_attachment(handle)
            check(handle,report)
            assert native.dumps_mixed(handle) == record
            restored = native.loads_mixed(record)
            check(restored["boundary_handle"],native.check_mixed_cap_attachment(restored["boundary_handle"]))
            assert not native.inspect_mixed(restored["boundary_handle"])["seam_bound_verified"]
            limited = native.check_mixed_cap_attachment(handle,32,16,4000000,1)
            assert not limited["cap_regions_attached"] and limited["reason"]
            limited = native.check_mixed_cap_attachment(handle,32,16,1)
            assert not limited["cap_regions_attached"] and not limited["region_reference_resolved"]
            print("native cap attachment",crossing,operation,report["reference_caps"],report["reference_regions"])
        App.closeDocument(doc.Name)
    check(handle,native.check_mixed_cap_attachment(handle))
    for args,error in (((None,),TypeError),((handle,3),ValueError),
                       ((handle,32,16,0),ValueError),((handle,32,16,4000000,0),ValueError)):
        try:
            native.check_mixed_cap_attachment(*args)
        except error:
            pass
        else:
            raise AssertionError("invalid cap attachment query accepted")
    print("native implicit mixed cap attachment smoke test passed")


try:
    main()
except Exception:
    traceback.print_exc()
    raise
