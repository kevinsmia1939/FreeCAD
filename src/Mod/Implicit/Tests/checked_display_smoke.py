# SPDX-License-Identifier: LGPL-2.1-or-later
"""Same-buffer proximity, binary32 upload and exact contact gates."""
import math
import os
import struct
import traceback
import FreeCAD as App
import Part
import ImplicitOCCT as native


def check(handle):
    record = native.dumps_mixed(handle)
    data = native.tessellate_mixed_checked(handle)
    proof = data["display_checks"]
    assert proof["coordinate_frame"] == "source_local_binary32"
    assert proof["boundary_proximity_resolved"] and proof["triangle_contacts_clear"]
    assert not proof["solid_validated"] and not proof["topology_validated"]
    assert 0 < proof["boundary_to_mesh_bound"] <= .1
    assert 0 < proof["mesh_to_boundary_bound"] <= .1
    assert 0 < proof["upload_coordinate_bound"] < .1 / 4096
    assert proof["pair_tests"] > 0 and proof["spatial_cells"] > 0
    assert not data["surface_coverage_verified"] and not data["solid_validated"]
    assert len(data["vertices"]) == len(data["assignment_vertices"])
    for raw, shown in zip(data["assignment_vertices"], data["vertices"]):
        assert tuple(struct.unpack("fff", struct.pack("fff", *shown))) == tuple(shown)
        assert math.dist(raw, shown) <= proof["upload_coordinate_bound"]
    assert native.dumps_mixed(handle) == record
    return data


def main():
    face = native.gyroid(10, 0, (0, 0, 0), (10, 10, 10))
    box = Part.makeBox(10, 10, 10)
    for operation in ("common", "box_minus_field"):
        source = native.mixed_box(face, box, operation, corner_policy="regularized")
        handle = source["boundary_handle"]
        checked = check(handle)
        original = native.tessellate_mixed(handle)
        assert "display_checks" not in original
        assert checked["assignment_vertices"] == original["vertices"]
        for key in ("seams", "wires", "cap_triangles", "implicit_triangles"):
            assert checked[key] == original[key]
    for args, error in (((None,), TypeError), ((handle, .1, 256, 200000, 400000, 0), ValueError),
                        ((handle, .1, 256, 200000, 400000, 14, 0), ValueError),
                        ((handle, .1, 256, 200000, 400000, 1), NotImplementedError),
                        ((handle, .1, 256, 200000, 400000, 14, 1), NotImplementedError),
                        ((handle, .1, 256, 200000, 400000, 14, 2000000, 1000000, 1), NotImplementedError)):
        try:
            native.tessellate_mixed_checked(*args)
        except error:
            pass
        else:
            raise AssertionError("invalid/unresolved display check published buffers")
    loaded = native.loads_mixed(native.dumps_mixed(handle))["boundary_handle"]
    assert not native.inspect_mixed(loaded)["seam_bound_verified"]
    check(loaded)
    assert not native.inspect_mixed(loaded)["seam_bound_verified"]
    # Non-binary32 cap coordinates must be bounded, not falsely rejected as
    # nonplanar or silently treated as exact after the viewport upload.
    field = native.gyroid(10, 1.45, (-5, -5, -5), (6, 6, 6))
    box = Part.makeBox(3.24, 3.28, 2.75, App.Vector(-.31, -.37, 1.25))
    strict = native.mixed_box(field, box)["boundary_handle"]
    assert check(strict)["corner_policy"] == "reject"
    print("native implicit checked display smoke test passed", flush=True)


try:
    main()
except BaseException:
    traceback.print_exc()
    os._exit(1)
