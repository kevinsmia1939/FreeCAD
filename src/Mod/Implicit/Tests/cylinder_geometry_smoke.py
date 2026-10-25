# SPDX-License-Identifier: LGPL-2.1-or-later
"""Owned bidirectional full-cylinder boundary geometry checks and explicit limits."""
import math
import ImplicitOCCT as native

source = native.gyroid(10, .21, (-10, -10, -10), (10, 10, 10))
record = native.dumps(source)
args = ((0, 0, 0), (0, 0, 1), (1, 0, 0), .5, (.27, .27 + 2 * math.pi), (-1.7, 1.3))
for negative in (True, False):
    result = native.check_cylinder_shell_geometry(source, *args, negative=negative)
    assert result["shell_geometry_validated"], result["geometry_reason"]
    assert result["trim_tolerance_verified"] and result["shell_topology_validated"]
    assert not result["solid_validated"]
    assert result["geometry_cells"] > 1 and result["geometry_segment_tests"] > 1
    assert 0 < result["mathematical_to_native_bound"] <= .1
    assert 0 < result["native_to_mathematical_bound"] <= .1
    assert result["field_wire_bound"] <= result["boundary_bound"] <= .1
    handle = result["geometry_handle"]
    result["shell_geometry_validated"] = False
    fresh = native.inspect_cylinder_shell_geometry(handle)
    assert fresh["shell_geometry_validated"] and fresh["field_record"] == record
partial = native.check_cylinder_shell_geometry(source, *(args[:-1] + ((0, .5),)))
assert not partial["shell_geometry_validated"] and partial["boundary_bound"] == 0
assert not partial["solid_validated"]
try:
    native.inspect_cylinder_shell_geometry(source)
except TypeError:
    pass
else:
    raise AssertionError("Wrong geometry owner accepted")
assert native.dumps(source) == record
print("native implicit cylinder geometry smoke test passed", flush=True)
