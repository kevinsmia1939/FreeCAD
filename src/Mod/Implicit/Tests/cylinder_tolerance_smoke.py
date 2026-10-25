# SPDX-License-Identifier: LGPL-2.1-or-later
"""Combined trim allowance, source tolerance isolation and owned audit reports."""
import math
import ImplicitOCCT as native

source = native.gyroid(10, .21, (-10, -10, -10), (10, 10, 10))
record = native.dumps(source)
args = ((0, 0, 0), (0, 0, 1), (1, 0, 0), .5, (.27, .27 + 2 * math.pi), (-1.7, 1.3))
for negative in (True, False):
    result = native.check_cylinder_shell_tolerance(source, *args, distance_tolerance=.05, negative=negative)
    assert result["trim_tolerance_verified"], result["trim_tolerance_reason"]
    assert result["shell_topology_validated"] and not result["shell_geometry_validated"]
    assert not result["solid_validated"]
    assert result["field_wire_bound"] == result["side_contour_bound"] + result["side_surface_deviation_bound"]
    assert 0 < result["field_wire_bound"] <= .05
    assert result["maximum_face_tolerance"] == .05
    assert result["maximum_edge_tolerance"] <= .05 and result["maximum_vertex_tolerance"] <= .05
    assert native.info(result["implicit_faces"][0])["tolerance"] == .05
    result["trim_tolerance_verified"] = False
    fresh = native.inspect_cylinder_shell_tolerance(result["tolerance_handle"])
    assert fresh["trim_tolerance_verified"] and fresh["field_record"] == record
assert native.info(source)["tolerance"] == .1 and native.dumps(source) == record
failed = native.check_cylinder_shell_tolerance(source, *args, maximum_cells=4)
assert not failed["trim_tolerance_verified"] and not failed["solid_validated"]
try:
    native.inspect_cylinder_shell_tolerance(source)
except TypeError:
    pass
else:
    raise AssertionError("Wrong tolerance owner accepted")
print("native implicit cylinder tolerance smoke test passed", flush=True)
