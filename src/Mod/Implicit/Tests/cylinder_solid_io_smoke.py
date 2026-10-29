# SPDX-License-Identifier: LGPL-2.1-or-later
"""Stored native cylinder topology must not inherit numerical certificates."""
import math
import ImplicitOCCT as native

source = native.gyroid(10, .21, (-10, -10, -10), (10, 10, 10))
args = ((0, 0, 0), (0, 0, 1), (1, 0, 0), .5,
        (.27, .27 + 2 * math.pi), (-1.7, 1.3))
for negative in (True, False):
    geometry = native.check_cylinder_shell_geometry(source, *args, negative=negative)
    solid = native.build_cylinder_solid(geometry["geometry_handle"])
    assert solid["solid_validated"], solid["solid_reason"]
    record = native.dumps_cylinder_solid(solid["solid_handle"])
    restored = native.loads_cylinder_solid(record)
    handle = restored["stored_solid_handle"]
    assert restored["topology_validated"] and restored["solid_constructed"]
    assert restored["solid_closed"] and restored["face_count"] == 3
    assert restored["negative"] == negative
    assert restored["field_record"] == native.dumps(source)
    assert restored["requires_revalidation"]
    coherence = native.check_stored_cylinder_curves(handle)
    assert coherence["curve_coherence_verified"], coherence["curve_coherence_reason"]
    assert coherence["curve_coherence_bound"] <= .1
    assert not native.check_stored_cylinder_curves(handle, 1)["curve_coherence_verified"]
    seam = native.check_stored_cylinder_primitive_seam(handle)
    assert seam["primitive_seam_verified"], seam["primitive_seam_reason"]
    assert seam["primitive_seam_bound"] <= .1
    assert not native.check_stored_cylinder_primitive_seam(handle, 1)["primitive_seam_verified"]
    masked = native.check_stored_cylinder_masked_seam(handle)
    assert masked["masked_seam_verified"], masked["masked_seam_reason"]
    assert masked["masked_seam_bound"] <= .1
    for flag in ("geometry_verified", "volume_verified", "solid_validated",
                 "solid_generic_occt_supported"):
        assert not restored[flag], flag
    assert restored["stored_volume_lower"] == solid["volume_lower"]
    assert restored["stored_volume_upper"] == solid["volume_upper"]
    restored["solid_validated"] = True
    assert not native.inspect_stored_cylinder_solid(handle)["solid_validated"]
    for query in (lambda: native.classify_cylinder_material(handle, (0, 0, 0)),
                  lambda: native.bound_cylinder_material_volume(handle),
                  lambda: native.dumps_cylinder_solid(handle)):
        try:
            query()
        except TypeError:
            pass
        else:
            raise AssertionError("Stored unverified owner accepted as qualified")
    for bad in (record[:len(record)//2], record + "garbage",
                record.replace("OCCT_IMPLICIT_CYLINDER_SOLID 1 ",
                               "OCCT_IMPLICIT_CYLINDER_SOLID 9 ", 1)):
        try:
            native.loads_cylinder_solid(bad)
        except (ValueError, RuntimeError):
            pass
        else:
            raise AssertionError("Malformed cylinder graph accepted")
print("native implicit cylinder solid IO smoke test passed", flush=True)
