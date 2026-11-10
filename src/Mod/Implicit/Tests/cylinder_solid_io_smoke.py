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
    coverage = native.check_stored_cylinder_seam_coverage(handle)
    assert coverage["seam_coverage_verified"], coverage["seam_coverage_reason"]
    assert coverage["seam_coverage_bound"] <= .1
    assert not native.check_stored_cylinder_seam_coverage(handle, 1)["seam_coverage_verified"]
    cap = native.check_stored_cylinder_retained_cap(handle)
    assert cap["retained_cap_verified"], cap["retained_cap_reason"]
    assert cap["retained_cap_bound"] <= .1
    assert not native.check_stored_cylinder_retained_cap(handle, 1)["retained_cap_verified"]
    side = native.check_stored_cylinder_retained_side(handle)
    assert side["retained_side_verified"], side["retained_side_reason"]
    assert side["retained_side_bound"] <= .1
    assert not native.check_stored_cylinder_retained_side(handle, 1)["retained_side_verified"]
    geometry = native.qualify_stored_cylinder_geometry(handle)
    assert geometry["geometry_verified"], geometry["geometry_reason"]
    assert geometry["boundary_bound"] <= .1
    assert not geometry["volume_verified"] and not geometry["solid_validated"]
    assert not native.inspect_stored_cylinder_solid(handle)["geometry_verified"]
    geometry["geometry_verified"] = False
    assert native.inspect_stored_cylinder_geometry(geometry["stored_geometry_handle"])["geometry_verified"]
    failed = native.qualify_stored_cylinder_geometry(handle, 1)
    assert not failed["geometry_verified"]
    assert not native.inspect_stored_cylinder_geometry(failed["stored_geometry_handle"])["geometry_verified"]
    qualified = native.qualify_stored_cylinder_solid(geometry["stored_geometry_handle"])
    assert qualified["solid_validated"], qualified["solid_reason"]
    assert qualified["solid_constructed"] and qualified["solid_closed"]
    assert qualified["volume_verified"] and not qualified["solid_generic_occt_supported"]
    assert qualified["volume_lower"] <= solid["volume_upper"]
    assert qualified["volume_upper"] >= solid["volume_lower"]
    qualified_handle = qualified["qualified_stored_solid_handle"]
    qualified["solid_validated"] = False
    assert native.inspect_qualified_stored_cylinder_solid(qualified_handle)["solid_validated"]
    query_record = native.dumps_cylinder_solid(qualified_handle)
    root = math.asin(.21)*10/(2*math.pi)
    queries = (((0,0,-.5), "IN" if negative else "OUT"),
               ((0,0,.8), "OUT" if negative else "IN"), ((0,0,root), "ON"),
               ((0,0,-1.7), "ON" if negative else "OUT"),
               ((0,0,1.3), "OUT" if negative else "ON"), ((2,0,0), "OUT"))
    for owner in (geometry["stored_geometry_handle"], qualified_handle):
        for point, state in queries:
            report = native.classify_cylinder_material(owner, point)
            assert report["mathematical_state"] == state, (point, report)
            baseline = native.classify_cylinder_material(solid["solid_handle"], point)
            for key in ("distance_lower_bound", "distance_upper_bound", "field_value_at_domain_projection"):
                assert abs(report[key]-baseline[key]) < 1.e-10, (key, report, baseline)
        margin = native.classify_cylinder_material(owner, (0,0,root+.05))
        tolerance = (margin["distance_lower_bound"]+margin["distance_upper_bound"])/2
        assert native.classify_cylinder_material(owner, (0,0,root+.05), tolerance)["mathematical_state"] == "UNKNOWN"
        for point, tolerance in (((0,0,0), 0), ((float("nan"),0,0), 1.e-7)):
            try:
                native.classify_cylinder_material(owner, point, tolerance)
            except ValueError:
                pass
            else:
                raise AssertionError("Invalid restored material query accepted")
    assert native.dumps_cylinder_solid(qualified_handle) == query_record
    roundtrip = native.loads_cylinder_solid(native.dumps_cylinder_solid(qualified_handle))
    assert roundtrip["topology_validated"] and not roundtrip["solid_validated"]
    assert not roundtrip["geometry_verified"] and not roundtrip["volume_verified"]
    assert roundtrip["stored_volume_lower"] == qualified["volume_lower"]
    assert roundtrip["stored_volume_upper"] == qualified["volume_upper"]
    volume = native.bound_stored_cylinder_volume(qualified_handle, volume_tolerance=.02)
    assert volume["volume_verified"] and volume["volume_upper"] - volume["volume_lower"] <= .02
    refused = native.qualify_stored_cylinder_solid(geometry["stored_geometry_handle"], maximum_cells=1)
    assert not refused["solid_validated"] and not refused["solid_constructed"]
    coarse = native.qualify_stored_cylinder_solid(geometry["stored_geometry_handle"], volume_tolerance=100)
    assert coarse["volume_verified"] and not coarse["solid_validated"]
    for owner in (failed["stored_geometry_handle"], refused["qualified_stored_solid_handle"]):
        try:
            native.classify_cylinder_material(owner, (0,0,0))
        except ValueError:
            pass
        else:
            raise AssertionError("Failed restored owner accepted for material query")
        try:
            native.bound_stored_cylinder_volume(owner)
        except ValueError:
            pass
        else:
            raise AssertionError("Failed restored owner accepted")
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
