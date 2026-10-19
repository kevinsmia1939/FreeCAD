# SPDX-License-Identifier: LGPL-2.1-or-later
"""Corner-aware transient mesh constraints/candidates, not coverage certification."""
import os
import traceback
import FreeCAD as App
import Part
import ImplicitOCCT as native


def check(data, surface):
    assert data["corner_policy"] == "regularized" and data["fixed_corner_count"] == 8
    assert len(data["seams"]) == 18 and len(data["wires"]) == 1
    assert data["native_surface_meshed"] == surface
    assert not data["solid_validated"] and not data["surface_coverage_verified"]
    indices = set(data["wires"][0])
    corners = {i for i in indices if all(x in (0., 10.) for x in data["vertices"][i])}
    assert len(corners) == 6
    if surface:
        assert data["mesh_closed"] and data["cells"] % 2 == 1
        assert data["field_distance_bound"] <= .1
        used = {i for triangle in data["implicit_triangles"] for i in triangle}
        assert corners <= used
        for i in used:
            assert tuple(data["vertices"][i]) not in ((0., 0., 0.), (10., 10., 10.))


def main():
    field = native.gyroid(10, 0, (0, 0, 0), (10, 10, 10))
    for operation in ("common", "box_minus_field"):
        source = native.mixed_box(field, Part.makeBox(10, 10, 10), operation,
                                  corner_policy="regularized")
        handle = source["boundary_handle"]
        record = native.dumps_mixed(handle)
        check(native.prepare_mixed_mesh(handle), False)
        check(native.tessellate_mixed(handle), True)
        audit = native.audit_mixed_mesh(handle)
        assert audit["state"] == "clear", audit
        assert native.dumps_mixed(handle) == record
        assert native.inspect_mixed(handle)["seam_bound_verified"]
    loaded = native.loads_mixed(record)["boundary_handle"]
    check(native.prepare_mixed_mesh(loaded), False)
    assert not native.prepare_mixed_mesh(loaded)["seam_bound_verified"]
    assert not native.inspect_mixed(loaded)["seam_bound_verified"]
    print("native implicit corner mesh smoke test passed", flush=True)


try:
    main()
except BaseException:
    traceback.print_exc()
    os._exit(1)
