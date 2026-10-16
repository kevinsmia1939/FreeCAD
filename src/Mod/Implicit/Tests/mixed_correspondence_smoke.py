# SPDX-License-Identifier: LGPL-2.1-or-later
"""Private reference traces and stored graph bijection; NOT solid validation."""
import traceback
import FreeCAD as App
import ImplicitMixed
import ImplicitOCCT as native


def check(report):
    assert report["stored_graph_correspondence_resolved"], report
    assert report["field_box_regularity_resolved"] and report["reason"] == "matched"
    assert report["matched_edges"] > 0 and report["matched_vertices"] > 0
    assert report["matched_caps"] > 0 and report["matched_wires"] > 0
    assert 0 < report["curve_deviation_bound"] <= report["matching_tolerance"]
    assert (report["curve_deviation_bound"]+report["reference_seam_bound"]
            + report["cap_parameter_deviation_bound"]) <= .1
    assert report["minimum_tangent_alignment"] > 0
    assert not report["topology_validated"] and not report["solid_validated"]


def main():
    for crossing in (False, True):
        obj = ImplicitMixed.demo(open_contours=crossing)
        doc = obj.Document
        for operation in ("Common", "BoxMinusField"):
            obj.Operation = operation
            doc.recompute()
            handle = obj.Geometry
            record = native.dumps_mixed(handle)
            report = native.check_mixed_correspondence(handle)
            print("native stored graph correspondence", crossing, operation, report)
            check(report)
            assert native.dumps_mixed(handle) == record
            loaded = native.loads_mixed(record)
            assert not loaded["seam_bound_verified"]
            check(native.check_mixed_correspondence(loaded["boundary_handle"]))
            assert not native.inspect_mixed(loaded["boundary_handle"])["seam_bound_verified"]
            limited = native.check_mixed_correspondence(handle,4)
            assert not limited["stored_graph_correspondence_resolved"]
            assert limited["reason"] and not limited["solid_validated"]
            limited = native.check_mixed_correspondence(handle,512,1)
            if report["comparisons"] > 1:
                assert not limited["stored_graph_correspondence_resolved"]
            else:
                check(limited)  # one edge really needs just one candidate comparison
        App.closeDocument(doc.Name)
    check(native.check_mixed_correspondence(handle))
    for args, error in (((None,), TypeError), ((handle,3), ValueError),
                        ((handle,512,0), ValueError)):
        try:
            native.check_mixed_correspondence(*args)
        except error:
            pass
        else:
            raise AssertionError("invalid correspondence query accepted")
    print("native implicit mixed stored correspondence smoke test passed")


try:
    main()
except Exception:
    traceback.print_exc()
    raise
