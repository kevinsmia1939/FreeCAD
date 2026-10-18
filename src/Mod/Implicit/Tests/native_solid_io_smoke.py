# SPDX-License-Identifier: LGPL-2.1-or-later
"""Actual native solid topology I/O, without recipe rebuilding or saved proof flags."""
import os
import traceback
import FreeCAD as App
import Part
import ImplicitMixed
import ImplicitOCCT as native


def roundtrip(result):
    assert result["native_solid_constructed"] and result["solid_validated"], result["reason"]
    original = result["solid_handle"]
    record = native.dumps_mixed_solids(original)
    assert record.startswith("OCCT_IMPLICIT_SOLIDS 1 ")
    saved = native.build_mixed_solids
    def forbidden(*_args):
        raise AssertionError("Solid import attempted Python recipe rebuilding")
    native.build_mixed_solids = forbidden
    try:
        loaded = native.loads_mixed_solids(record)
    finally:
        native.build_mixed_solids = saved
    assert loaded["native_solid_constructed"]
    assert loaded["reason"] == "restored_native_solids_unverified"
    for key in ("solid_validated", "geometry_accuracy_verified", "topology_validated",
                "face_attachment_validated", "part_compatible", "generic_brep_check_performed"):
        assert not loaded[key], key
    assert not loaded["geometry"]["resolved"]
    for key in ("face_sources", "face_components", "face_shells", "component_domains",
                "shell_regions", "shell_euler", "shell_count", "solid_count", "face_count"):
        assert result[key] == loaded[key], key
    assert native.dumps_mixed_solids(loaded["solid_handle"]) == record
    assert native.dumps_mixed_solids(original) == record
    source = native.source_mixed_solids(loaded["solid_handle"])
    assert not source["seam_bound_verified"]
    for p in ((0, 0, 2), (20, 20, 20), (-.31, -.37, 1.25)):
        a = native.classify_mixed_solids(original, p)
        b = native.classify_mixed_solids(loaded["solid_handle"], p)
        assert a.pop("solid_validated") and not b.pop("solid_validated")
        assert a == b
    for original_face, face in zip(result["implicit_faces"], loaded["implicit_faces"]):
        assert native.info(original_face)["minimum"] == native.info(face)["minimum"]
        assert native.info(original_face)["maximum"] == native.info(face)["maximum"]
        assert native.value(original_face, (1, 2, 3)) == native.value(face, (1, 2, 3))
    return loaded, record


def main():
    for crossing in (False, True):
        obj = ImplicitMixed.demo(open_contours=crossing)
        doc = obj.Document
        slot = doc.addObject("Implicit::NativeFeaturePython", "NotASolidProperty")
        for operation in ("Common", "BoxMinusField"):
            obj.Operation = operation
            doc.recompute()
            result = native.build_mixed_solids(obj.Geometry)
            loaded, record = roundtrip(result)
            try:
                slot.Geometry = loaded["solid_handle"]
            except TypeError:
                pass
            else:
                raise AssertionError("A native boundary property silently accepted solid topology")
        App.closeDocument(doc.Name)
    # Owned results, faces and source snapshots survive document closure.
    handle = loaded["solid_handle"]
    assert native.inspect_mixed_solids(handle)["solid_count"] == 1
    source = native.source_mixed_solids(handle)
    fresh = native.build_mixed_solids(source["boundary_handle"])
    assert fresh["solid_validated"]  # An explicit NEW check/build, not an import flag.
    assert not native.inspect_mixed_solids(handle)["solid_validated"]
    field = native.gyroid(10, 1.45, (-5, -5, -5), (16, 16, 6))
    islands = native.mixed_box(field, Part.makeBox(13.24, 3.28, 2.75, App.Vector(-.31, -.37, 1.25)),
                               "box_minus_field")
    two, _ = roundtrip(native.build_mixed_solids(islands["boundary_handle"], .1, 64))
    assert two["solid_count"] == 2
    for call, args, error in (
            (native.loads_mixed_solids, (None,), TypeError),
            (native.loads_mixed_solids, (record[:-1],), ValueError),
            (native.loads_mixed_solids, (record + "garbage",), ValueError),
            (native.loads_mixed_solids, (record.replace("OCCT_IMPLICIT_SOLIDS 1", "OCCT_IMPLICIT_SOLIDS 2", 1),), ValueError),
            (native.dumps_mixed_solids, (source["boundary_handle"],), TypeError),
            (native.source_mixed_solids, (None,), TypeError),
            (native.dumps_mixed, (handle,), TypeError),
            (native.loads_mixed, (record,), ValueError),
            (Part.Shape, (handle,), (TypeError, RuntimeError))):
        try:
            call(*args)
        except error:
            pass
        else:
            raise AssertionError("Unsupported native solid I/O accepted")
    assert native.dumps_mixed_solids(handle) == record
    print("native implicit native solid IO smoke test passed", flush=True)


try:
    main()
except BaseException:
    traceback.print_exc()
    os._exit(1)
