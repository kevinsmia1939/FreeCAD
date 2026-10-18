# SPDX-License-Identifier: LGPL-2.1-or-later
"""Exact default corner identities and local material, not a completed trim workflow."""
import math
import os
import traceback
import FreeCAD as App
import Implicit
import ImplicitOCCT as native
import Part


def main():
    doc = App.newDocument("DefaultCornerGyroid")
    obj = doc.addObject("Implicit::Feature", "Gyroid")
    obj.Function, obj.Period, obj.IsoValue = "Gyroid", 10, 0
    obj.DomainMin, obj.DomainMax = (0, 0, 0), (10, 10, 10)
    doc.recompute()
    face = native.gyroid(obj.Period, obj.IsoValue, tuple(obj.DomainMin), tuple(obj.DomainMax))
    record = native.dumps(face)
    model = native.check_box_corners(face)
    assert model["corner_germs_resolved"]
    assert model["exact_zero_count"] == 8 and model["split_count"] == 6
    assert not model["solid_validated"] and not model["topology_validated"]
    for corner in model["corners"]:
        index = corner["index"]
        assert corner["exact_zero"] and 0 < corner["radius"] <= .1
        assert corner["kind"] == ("positive_cone" if index == 0 else "negative_cone" if index == 7 else "split_cone")
        for operation in ("common", "box_minus_field"):
            result = native.classify_box_corner(face, index, corner["anchor"], operation)
            assert result["resolved"] and result["on_field"] and result["closed_retained"]
            assert result["regularized_retained"] is (index != (0 if operation == "common" else 7))
            assert not result["solid_validated"]
            point = tuple(corner["anchor"][axis] + (-1 if index & (1 << axis) else 1)
                          * corner["radius"] / 4 for axis in range(3))
            query = native.classify_box_corner(face, index, point, operation)
            assert query["resolved"] and not query["on_field"]
            negative = index.bit_count() >= 2
            assert query["closed_retained"] is (negative if operation == "common" else not negative)
            outside = native.classify_box_corner(face, index,
                (corner["maximum"][0] + corner["radius"], *corner["anchor"][1:]), operation)
            assert not outside["resolved"] and outside["reason"] == "outside_corner_neighborhood"
    # Unknown near-zeros do not become exact lattice identities through rounding.
    near = native.gyroid(10, 0, (math.nextafter(0., 1.), 0, 0), (10, 10, 10))
    unknown = native.check_box_corners(near)
    assert not unknown["corner_germs_resolved"] and not unknown["corners"][0]["exact_zero"]
    assert not native.check_box_corners(face, 1e-20)["corner_germs_resolved"]
    # This prerequisite does not relax old transversality/trim checks or forge a solid.
    regularity = native.check_box_regularity(face)
    assert not regularity["field_box_regularity_resolved"]
    for operation in ("common", "box_minus_field"):
        try:
            native.mixed_box(face, Part.makeBox(10, 10, 10), operation)
        except NotImplementedError as error:
            assert "corner" in str(error).lower()
        else:
            raise AssertionError("local corner model silently enabled unsupported whole trimming")
    for args in ((face, -1, (0, 0, 0)), (face, 8, (0, 0, 0)),
                 (face, 0, (math.inf, 0, 0)), (face, 0, (0, 0, 0), "fuse")):
        try:
            native.classify_box_corner(*args)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid local corner query accepted")
    assert native.dumps(face) == record
    loaded = native.loads(record)
    assert native.check_box_corners(loaded) == model
    App.closeDocument(obj.Document.Name)
    # Owned mathematical face, no dependency on the closed document or its mesh.
    assert native.classify_box_corner(face, 0, (0, 0, 0))["regularized_retained"] is False
    print("native implicit corner germ smoke test passed", flush=True)


try:
    main()
except BaseException:
    traceback.print_exc()
    os._exit(1)
