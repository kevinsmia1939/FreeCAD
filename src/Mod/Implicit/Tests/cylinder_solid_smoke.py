# SPDX-License-Identifier: LGPL-2.1-or-later
"""Actual native cylinder solid ownership, bounded mathematical volume and refusal."""
import math
import ImplicitOCCT as native

source = native.gyroid(10, .21, (-10, -10, -10), (10, 10, 10))
record = native.dumps(source)
args = ((0, 0, 0), (0, 0, 1), (1, 0, 0), .5, (.27, .27 + 2 * math.pi), (-1.7, 1.3))
lows, highs = 0, 0
for negative in (True, False):
    geometry = native.check_cylinder_shell_geometry(source, *args, negative=negative)
    assert geometry["shell_geometry_validated"], geometry["geometry_reason"]
    result = native.build_cylinder_solid(geometry["geometry_handle"])
    assert result["solid_validated"], result["solid_reason"]
    assert result["solid_constructed"] and result["solid_closed"] and result["solid_shape_type"] == "Solid"
    assert not result["solid_generic_occt_supported"]
    assert result["volume_verified"] and result["volume_kind"] == "mathematical_material"
    assert 0 < result["volume_lower"] <= result["volume_upper"] < result["cylinder_volume"]
    assert result["volume_upper"] - result["volume_lower"] <= .01
    lows += result["volume_lower"]
    highs += result["volume_upper"]
    handle = result["solid_handle"]
    query = native.classify_cylinder_material(handle, (0, 0, -.5))
    assert query["mathematical_state"] == ("IN" if negative else "OUT")
    result["solid_validated"] = False
    result["volume_upper"] = -1
    fresh = native.inspect_cylinder_solid(handle)
    assert fresh["solid_validated"] and fresh["volume_upper"] > 0 and fresh["field_record"] == record
    failed = native.build_cylinder_solid(geometry["geometry_handle"], maximum_cells=1)
    assert not failed["solid_validated"] and not failed["solid_constructed"]
    assert not failed["volume_verified"]
    try:
        native.classify_cylinder_material(failed["solid_handle"], (0, 0, 0))
    except ValueError:
        pass
    else:
        raise AssertionError("Failed solid owner accepted")
    coarse = native.build_cylinder_solid(geometry["geometry_handle"], volume_tolerance=100)
    assert coarse["volume_verified"] and not coarse["solid_validated"] and not coarse["solid_constructed"]
    volume = native.bound_cylinder_material_volume(handle, volume_tolerance=.02)
    assert volume["volume_verified"] and volume["volume_upper"] - volume["volume_lower"] <= .02
assert lows <= math.pi * .25 * 3 <= highs
assert native.dumps(source) == record
try:
    native.inspect_cylinder_solid(source)
except TypeError:
    pass
else:
    raise AssertionError("Wrong solid owner accepted")
print("native implicit cylinder solid smoke test passed", flush=True)
