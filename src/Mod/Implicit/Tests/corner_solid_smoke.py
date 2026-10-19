# SPDX-License-Identifier: LGPL-2.1-or-later
"""Qualified corner native solids and actual topology persistence, not Part shapes."""
import os
import tempfile
import traceback
import FreeCAD as App
import Implicit
import Part
import ImplicitOCCT as native


def check(report, validated):
    assert report["native_solid_constructed"], report
    assert report["solid_validated"] == validated
    assert report["topology_validated"] == report["geometry_accuracy_verified"] == validated
    assert report["corner_policy"] == "regularized"
    assert (report["solid_count"], report["shell_count"], report["face_count"],
            report["implicit_face_count"], report["region_count"]) == (1, 1, 13, 1, 1)
    assert report["shell_euler"] == [-2] and report["shell_regions"] == [0]
    assert not report["part_compatible"] and not report["generic_brep_check_performed"]
    assert report["maximum_stored_tolerance"] <= .1
    if validated:
        assert report["geometry"]["resolved"]
        assert report["geometry"]["boundary_bound"] <= .1
        assert report["geometry"]["regularized_empty_cells"] > 0
    else:
        assert not report["geometry"]["resolved"]
    face = report["implicit_faces"][0]
    assert not native.in_domain(face, (0, 0, 0))
    assert not native.in_domain(face, (10, 10, 10))
    assert native.in_domain(face, (10, 0, 0))


def main():
    field = native.gyroid(10, 0, (0, 0, 0), (10, 10, 10))
    for operation in ("common", "box_minus_field"):
        boundary = native.mixed_box(field, Part.makeBox(10, 10, 10), operation,
                                    corner_policy="regularized")["boundary_handle"]
        before = native.dumps_mixed(boundary)
        result = native.build_mixed_solids(boundary)
        check(result, True)
        handle = result["solid_handle"]
        record = native.dumps_mixed_solids(handle)
        assert record.startswith("OCCT_IMPLICIT_SOLIDS 2 ")
        loaded = native.loads_mixed_solids(record)
        check(loaded, False)
        assert native.dumps_mixed_solids(loaded["solid_handle"]) == record
        source = native.source_mixed_solids(loaded["solid_handle"])
        assert source["surface_domain_exclusion_count"] == 2 and not source["seam_bound_verified"]
        check(native.build_mixed_solids(source["boundary_handle"]), True)
        assert not native.inspect_mixed_solids(loaded["solid_handle"])["solid_validated"]
        assert native.dumps_mixed(boundary) == before
        for point in ((0, 0, 0), (10, 10, 10), (5, 5, 5), (20, 20, 20)):
            a = native.classify_mixed_solids(handle, point)
            b = native.classify_mixed_solids(loaded["solid_handle"], point)
            assert a.pop("solid_validated") and not b.pop("solid_validated")
            assert a == b
        with tempfile.TemporaryDirectory(prefix="implicit-corner-solid-") as directory:
            doc = App.newDocument("CornerSolid")
            doc.UndoMode = 1
            obj = doc.addObject("Implicit::NativeSolidFeaturePython", "Result")
            obj.Geometry = handle
            geometry = Implicit.nativeGeometry(obj)
            for kind, count in (("Solid", 1), ("Shell", 1), ("Face", 13), ("Edge", 30), ("Vertex", 19)):
                assert geometry.countSubElements(kind) == count
                assert obj.getSubObject(kind + "1") is not None
            doc.openTransaction("Clear")
            obj.Geometry = None
            doc.commitTransaction()
            doc.undo()
            check(native.inspect_mixed_solids(obj.Geometry), True)
            doc.redo()
            assert obj.Geometry is None
            doc.undo()
            path = os.path.join(directory, "solid.FCStd")
            doc.recompute(); doc.saveAs(path)
            App.closeDocument(doc.Name)
            doc = App.openDocument(path)
            obj = doc.getObject("Result")
            check(native.inspect_mixed_solids(obj.Geometry), False)
            assert native.dumps_mixed_solids(obj.Geometry) == record
            owned = obj.Geometry
            whole = obj.getSubObject("")
            query = Implicit.classifyNative(whole, (0, 0, 0))
            assert not query["solid_validated"]
            App.closeDocument(doc.Name)
            check(native.inspect_mixed_solids(owned), False)
        assert not native.build_mixed_solids(boundary, .01)["native_solid_constructed"]
    big = native.gyroid(20, 0, (-20, -20, 20), (0, 0, 40))
    boundary = native.mixed_box(big, Part.makeBox(20, 20, 20, App.Vector(-20, -20, 20)),
                                "common", corner_policy="regularized")["boundary_handle"]
    assert not native.build_mixed_solids(boundary)["native_solid_constructed"]
    deeper = native.build_mixed_solids(boundary, .1, 32, 16, 4000000, 2000000, 2000000,
                                      2000000, 8000000, 18)
    assert deeper["solid_validated"] and deeper["geometry"]["boundary_bound"] <= .1
    print("native implicit corner solid smoke test passed", flush=True)


try:
    main()
except BaseException:
    traceback.print_exc()
    os._exit(1)
