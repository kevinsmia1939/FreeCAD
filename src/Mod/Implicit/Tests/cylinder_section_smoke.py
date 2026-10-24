# SPDX-License-Identifier: LGPL-2.1-or-later
"""Owned native cylindrical chart query; no BRep/solid promotion."""
import math
import ImplicitOCCT as native

face = native.gyroid(10, .21, (-10, -10, -10), (10, 10, 10))
record = native.dumps(face)
args = ((0, 0, 0), (0, 0, 1), (1, 0, 0), 2, (.27, 1.1), (-4.2, 3.7))
result = native.trace_gyroid_cylinder(face, *args)
assert result["resolved"] and result["curves"]
assert result["geometric_bound"] <= .1 and result["maximum_root_bracket"] <= .1 / 32
assert not result["topology_validated"] and not result["solid_validated"]
assert not result["point_contacts"] and not result["allow_exact_lattice_nodes"]
for curve in result["curves"]:
    for point in curve["points"]:
        assert abs(math.hypot(*point[:2]) - 2) < 1e-12
        assert abs(native.value(face, point)) < .01
assert not native.trace_gyroid_cylinder(face, *args, maximum_cells=4)["resolved"]
translated = native.translated(face, (3, -4, 2))
placed = native.trace_gyroid_cylinder(translated, (3, -4, 2), *args[1:])
assert placed["resolved"] and len(placed["curves"]) == len(result["curves"])
restored = native.loads(record)
assert native.trace_gyroid_cylinder(restored, *args) == result
assert native.dumps(face) == record
assert not result["periodic"]
periodic_args = (*args[:3], .5, (.27, .27 + 2 * math.pi), (-1.7, 1.3))
periodic = native.trace_gyroid_cylinder(face, *periodic_args, periodic=True)
assert periodic["resolved"] and periodic["periodic"]
assert len(periodic["curves"]) == 1 and periodic["curves"][0]["closed"]
points = periodic["curves"][0]["points"]
assert points[0] == points[-1]
assert not periodic["topology_validated"] and not periodic["solid_validated"]
assert native.trace_gyroid_cylinder(restored, *periodic_args, periodic=True) == periodic
assert not native.trace_gyroid_cylinder(face, *periodic_args, maximum_cells=4, periodic=True)["resolved"]
try:
    native.trace_gyroid_cylinder(face, *periodic_args, periodic=1)
except TypeError:
    pass
else:
    raise AssertionError("Non-bool periodic policy accepted")
for radius, angles in ((-1, (.27, 1.1)), (2, (0, 2 * math.pi))):
    try:
        native.trace_gyroid_cylinder(face, *args[:3], radius, angles, args[-1])
    except ValueError:
        pass
    else:
        raise AssertionError("Invalid/periodic cylinder chart accepted")
print("native implicit cylinder section smoke test passed", flush=True)
