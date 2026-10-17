# SPDX-License-Identifier: LGPL-2.1-or-later
"""Dual cap/root identities attach complete directed native trim boundaries."""
import traceback
import FreeCAD as App
import Part
import ImplicitMixed
import ImplicitOCCT as native


def check(report, seams, wires, components):
    assert report["trim_wires_attached"], report["reason"]
    assert report["cap_regions_attached"] and report["complement_cap_regions_attached"]
    assert report["reason"] == "trim_wires_attached"
    for key in ("implicit_face_attachment_validated","topology_validated",
                "native_shell_constructed","solid_validated"):
        assert not report[key]
    assert report["reference_arc_count"] == seams
    assert set(report["seam_reference_arcs"]) == set(range(seams))
    assert len(report["seam_reference_arcs"]) == seams
    assert report["reference_wire_count"] == wires
    assert set(report["wire_reference_loops"]) == set(range(wires))
    assert len(report["wire_reference_loops"]) == wires
    assert report["reference_surface_component_count"] == components
    assert len(report["wire_surface_components"]) == wires
    assert set(report["wire_surface_components"]) == set(range(components))
    assert report["comparisons"] > 0 and report["curve_samples"] > 0


def main():
    for crossing in (False,True):
        obj = ImplicitMixed.demo(open_contours=crossing)
        doc = obj.Document
        for operation in ("Common","BoxMinusField"):
            obj.Operation = operation
            doc.recompute()
            handle = obj.Geometry
            record = native.dumps_mixed(handle)
            seams,wires = obj.SeamCount, 3 if crossing else 1
            report = native.check_mixed_trim_attachment(handle)
            check(report,seams,wires,1)
            assert native.dumps_mixed(handle) == record
            print("native dual cap trim attachment",crossing,operation,
                  report["seam_reference_arcs"],report["wire_reference_loops"],report["wire_surface_components"])
        App.closeDocument(doc.Name)
    check(native.check_mixed_trim_attachment(handle),seams,wires,1)
    restored = native.loads_mixed(record)
    check(native.check_mixed_trim_attachment(restored["boundary_handle"]),seams,wires,1)
    assert not native.inspect_mixed(restored["boundary_handle"])["seam_bound_verified"]
    field = native.gyroid(10,1.45,(-5,-5,-5),(16,16,6))
    box = Part.makeBox(13.24,3.28,2.75,App.Vector(-.31,-.37,1.25))
    multiple = native.mixed_box(field,box,"common")
    check(native.check_mixed_trim_attachment(multiple["boundary_handle"],64),2,2,2)
    for args in ((handle,32,16,4000000,1),(handle,32,16,1)):
        limited = native.check_mixed_trim_attachment(*args)
        assert not limited["trim_wires_attached"] and limited["reason"]
        assert not limited["solid_validated"]
    for args,error in (((None,),TypeError),((field,),TypeError),((handle,3),ValueError),
                       ((handle,32,16,0),ValueError),((handle,32,16,4000000,0),ValueError)):
        try:
            native.check_mixed_trim_attachment(*args)
        except error:
            pass
        else:
            raise AssertionError("invalid trim attachment query accepted")
    print("native implicit mixed trim attachment smoke test passed")


try:
    main()
except Exception:
    traceback.print_exc()
    raise
