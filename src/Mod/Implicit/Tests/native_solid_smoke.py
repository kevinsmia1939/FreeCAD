# SPDX-License-Identifier: LGPL-2.1-or-later
"""Restricted implicit-aware numerical solids, never ordinary Part shapes."""
import traceback
import FreeCAD as App
import Part
import ImplicitMixed
import ImplicitOCCT as native


def check(result, count=1):
    assert result["native_solid_constructed"] and result["solid_validated"], result["reason"]
    assert result["topology_validated"] and result["geometry_accuracy_verified"]
    assert result["reason"] == "native_solids_validated"
    assert result["solid_count"] == result["region_count"] == count
    assert result["geometry"]["resolved"]
    assert result["geometry"]["boundary_bound"] <= result["tolerance"] == .1
    assert result["maximum_stored_tolerance"] <= .1
    assert "numerical" in result["validation_policy"]
    assert not result["part_compatible"] and not result["generic_brep_check_performed"]


def main():
    for crossing in (False, True):
        obj = ImplicitMixed.demo(open_contours=crossing)
        doc = obj.Document
        for operation in ("Common", "BoxMinusField"):
            obj.Operation = operation
            doc.recompute()
            boundary = obj.Geometry
            record = native.dumps_mixed(boundary)
            result = native.build_mixed_solids(boundary)
            check(result)
            assert all(result["geometry"]["cells"]), result["geometry"]
            handle = result["solid_handle"]
            saved = native.inspect_mixed_solids(handle)
            check(saved)
            for key in ("geometry", "component_domains", "shell_regions", "face_shells"):
                assert result[key] == saved[key]
            for p in ((0, 0, 2), (20, 20, 20), (-.31, -.37, 1.25)):
                query = native.classify_mixed_solids(handle, p)
                expected = native.classify_mixed(boundary, p)
                assert query.pop("solid_validated") is True
                assert expected.pop("solid_validated") is False
                assert query == expected
            assert native.dumps_mixed(boundary) == record
        App.closeDocument(doc.Name)
    check(native.inspect_mixed_solids(handle))
    restored = native.loads_mixed(record)["boundary_handle"]
    check(native.build_mixed_solids(restored))
    assert not native.inspect_mixed(restored)["seam_bound_verified"]
    field = native.gyroid(10, 1.45, (-5, -5, -5), (16, 16, 6))
    islands = native.mixed_box(field, Part.makeBox(13.24, 3.28, 2.75, App.Vector(-.31, -.37, 1.25)),
                               "box_minus_field")["boundary_handle"]
    check(native.build_mixed_solids(islands, .1, 64), 2)
    cavity = native.mixed_box(field, Part.makeBox(2, 2, 2, App.Vector(.3, .3, .3)),
                              "common")["boundary_handle"]
    result = native.build_mixed_solids(cavity)
    check(result)
    assert result["shell_count"] == 2 and result["shell_regions"] == [0, 0]
    face = result["implicit_faces"][0]
    del result
    assert native.value(face, (1, 2, 3)) == native.value(field, (1, 2, 3))
    for args in ((cavity, .01), (cavity, .1, 32, 16, 4000000, 2000000, 2000000, 1),
                 (cavity, .1, 32, 16, 4000000, 2000000, 2000000, 2000000, 1)):
        limited = native.build_mixed_solids(*args)
        assert not limited["solid_validated"] and not limited["native_solid_constructed"]
        assert "solid_handle" not in limited
    for call, args, error in (
            (native.build_mixed_solids, (None,), TypeError),
            (native.build_mixed_solids, (boundary, 0), ValueError),
            (native.build_mixed_solids, (boundary, .1, 32, 16, 0), ValueError),
            (native.inspect_mixed_solids, (boundary,), TypeError),
            (native.classify_mixed_solids, (boundary, (0, 0, 0)), TypeError),
            (native.dumps, (handle,), TypeError),
            (Part.Shape, (handle,), (TypeError, RuntimeError))):
        try:
            call(*args)
        except error:
            pass
        else:
            raise AssertionError("unsupported solid operation accepted")
    print("native implicit native solid smoke test passed")


try:
    main()
except Exception:
    traceback.print_exc()
    raise
