# SPDX-License-Identifier: LGPL-2.1-or-later
"""Actual corner-aware native shells; NOT geometric/solid qualification."""
import os
import tempfile
import traceback
import FreeCAD as App
import Part
import ImplicitOCCT as native


def check(report):
    assert report["face_attachment_validated"], report
    assert report["native_shell_constructed"] and report["topology_validated"], report
    assert report["corner_policy"] == "regularized" and report["reference_resolution"] == 31
    assert (report["shell_count"], report["face_count"], report["implicit_face_count"],
            report["region_count"], report["separator_count"]) == (1, 13, 1, 1, 0)
    assert report["shell_euler"] == [-2] and report["shell_regions"] == [0]
    assert set(report["face_shells"]) == {0}
    assert report["face_components"] == [-1] * 12 + [0]
    assert report["component_domains"] == [((0., 0., 0.), (10., 10., 10.))]
    for flag in ("solid_validated", "geometry_accuracy_verified", "part_compatible",
                 "generic_brep_check_performed"):
        assert not report[flag]
    face = report["implicit_faces"][0]
    for c in range(8):
        point = tuple(10. if c & (1 << axis) else 0. for axis in range(3))
        assert native.in_domain(face, point) == (c not in (0, 7))
    assert native.in_domain(face, (5, 5, 5))
    placed = native.translated(face, (2, 3, 4))
    assert not native.in_domain(placed, (2, 3, 4))
    assert not native.in_domain(placed, (12, 13, 14))
    assert native.in_domain(placed, (12, 3, 4))


def main():
    field = native.gyroid(10, 0, (0, 0, 0), (10, 10, 10))
    for operation in ("common", "box_minus_field"):
        source = native.mixed_box(field, Part.makeBox(10, 10, 10), operation,
                                  corner_policy="regularized")
        handle = source["boundary_handle"]
        record = native.dumps_mixed(handle)
        report = native.build_mixed_shells(handle)
        check(report)
        owned = report["shell_handle"]
        check(native.inspect_mixed_shells(owned))
        for point in ((0, 0, 0), (10, 10, 10), (5, 5, 5), (20, 20, 20)):
            assert native.classify_mixed_shells(owned, point) == native.classify_mixed(handle, point)
        assert native.dumps_mixed(handle) == record
        assert native.inspect_mixed(handle)["seam_bound_verified"]
        limited = native.build_mixed_shells(handle, 32, 16, 1)
        assert not limited["native_shell_constructed"] and "shell_handle" not in limited
        assert limited["corner_policy"] == "regularized" and limited["reason"]
    loaded = native.loads_mixed(record)["boundary_handle"]
    check(native.build_mixed_shells(loaded))
    assert not native.inspect_mixed(loaded)["seam_bound_verified"]
    with tempfile.TemporaryDirectory(prefix="implicit-corner-shell-") as directory:
        doc = App.newDocument("CornerShellSource")
        obj = doc.addObject("Implicit::NativeFeaturePython", "Boundary")
        obj.Geometry = loaded
        path = os.path.join(directory, "boundary.FCStd")
        doc.recompute()
        doc.saveAs(path)
        App.closeDocument(doc.Name)
        doc = App.openDocument(path)
        rebuilt = native.build_mixed_shells(doc.getObject("Boundary").Geometry)
        App.closeDocument(doc.Name)
        check(rebuilt)
        check(native.inspect_mixed_shells(rebuilt["shell_handle"]))
    check(native.inspect_mixed_shells(owned))
    print("native implicit corner shell smoke test passed", flush=True)


try:
    main()
except BaseException:
    traceback.print_exc()
    os._exit(1)
