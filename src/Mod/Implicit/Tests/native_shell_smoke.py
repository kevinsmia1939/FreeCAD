# SPDX-License-Identifier: LGPL-2.1-or-later
"""Genuine field-backed OCCT shells, not validated solids or Part shapes."""
import traceback
import FreeCAD as App
import Part
import ImplicitMixed
import ImplicitOCCT as native


def check(report):
    assert report["face_attachment_validated"], report["reason"]
    assert report["native_shell_constructed"] and report["topology_validated"], report["reason"]
    assert report["reason"] == "native_shells_constructed"
    for key in ("solid_validated","geometry_accuracy_verified","part_compatible","generic_brep_check_performed"):
        assert not report[key]
    assert len(report["shell_regions"]) == len(report["shell_euler"]) == report["shell_count"]
    assert len(report["face_sources"]) == len(report["face_components"]) == len(report["face_shells"]) == report["face_count"]
    assert len(report["implicit_faces"]) == report["implicit_face_count"] == len(report["component_domains"])
    assert set(report["shell_regions"]) == set(range(report["region_count"]))
    assert set(report["face_shells"]) == set(range(report["shell_count"]))
    assert sorted(c for c in report["face_components"] if c >= 0) == list(range(report["implicit_face_count"]))
    for face in report["implicit_faces"]:
        assert native.kernel_version.startswith("8.")
        assert isinstance(native.value(face,(1,2,3)),float)


def main():
    for crossing in (False,True):
        obj = ImplicitMixed.demo(open_contours=crossing)
        doc = obj.Document
        for operation in ("Common","BoxMinusField"):
            obj.Operation = operation
            doc.recompute()
            boundary = obj.Geometry
            record = native.dumps_mixed(boundary)
            result = native.build_mixed_shells(boundary)
            check(result)
            assert result["implicit_face_count"] == 1 and result["separator_count"] == 0
            handle = result["shell_handle"]
            saved = native.inspect_mixed_shells(handle)
            check(saved)
            for key in ("face_sources","face_components","face_shells","shell_regions","component_domains"):
                assert result[key] == saved[key]
            for p in ((0,0,2),(20,20,20),(-.31,-.37,1.25)):
                assert native.classify_mixed_shells(handle,p) == native.classify_mixed(boundary,p)
            assert native.dumps_mixed(boundary) == record
            print("genuine native shell",crossing,operation,result["shell_count"],result["face_count"],result["shell_euler"])
        App.closeDocument(doc.Name)
    check(native.inspect_mixed_shells(handle))
    restored = native.loads_mixed(record)
    check(native.build_mixed_shells(restored["boundary_handle"]))
    assert not native.inspect_mixed(restored["boundary_handle"])["seam_bound_verified"]
    field = native.gyroid(10,1.45,(-5,-5,-5),(16,16,6))
    box = Part.makeBox(13.24,3.28,2.75,App.Vector(-.31,-.37,1.25))
    for operation in ("common","box_minus_field"):
        data = native.mixed_box(field,box,operation)
        result = native.build_mixed_shells(data["boundary_handle"],64)
        check(result)
        assert result["implicit_face_count"] == 2 and result["separator_count"] == 1
        assert result["shell_count"] == (1 if operation == "common" else 2)
        domains = sorted(result["component_domains"])
        assert domains[0][1][0] == domains[1][0][0]
        assert 3 < domains[0][1][0] < 10
        if operation == "common":
            limited = native.build_mixed_shells(data["boundary_handle"],64,16,4000000,2000000,1)
            assert not limited["native_shell_constructed"] and "shell_handle" not in limited
    cavity = native.mixed_box(field,Part.makeBox(2,2,2,App.Vector(.3,.3,.3)),"common")
    result = native.build_mixed_shells(cavity["boundary_handle"])
    check(result)
    assert result["implicit_face_count"] == 1 and result["shell_count"] == 2 and result["region_count"] == 1
    # Lifetime of a face is independent of the shell capsule and document.
    face = result["implicit_faces"][0]
    del result
    assert native.value(face,(1,2,3)) == native.value(field,(1,2,3))
    try:
        Part.Shape(handle)
    except (TypeError,RuntimeError):
        pass
    else:
        raise AssertionError("native shell snapshot silently became a Part shape")
    for call,args,error in (
            (native.build_mixed_shells,(None,),TypeError),
            (native.build_mixed_shells,(boundary,3),ValueError),
            (native.build_mixed_shells,(boundary,32,16,4000000,2000000,0),ValueError),
            (native.inspect_mixed_shells,(boundary,),TypeError),
            (native.classify_mixed_shells,(boundary,(0,0,0)),TypeError),
            (native.dumps,(handle,),TypeError)):
        try:
            call(*args)
        except error:
            pass
        else:
            raise AssertionError("invalid native-shell operation accepted")
    print("native implicit native shell smoke test passed")


try:
    main()
except Exception:
    traceback.print_exc()
    raise
