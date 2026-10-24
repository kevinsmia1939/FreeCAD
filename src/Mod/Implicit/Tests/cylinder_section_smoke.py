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
boundary_args = (*args[:3], .5, (3, 3 + 2 * math.pi), (0, .5))
boundary = native.trace_gyroid_cylinder_boundary(face, *boundary_args)
assert boundary["resolved"] and boundary["boundary_incidence_verified"]
assert not boundary["topology_validated"] and not boundary["solid_validated"]
roots = boundary["boundary_roots"]
assert len(roots) == 4 and [r["height_boundary"] for r in roots] == [0, 0, 1, 1]
uses = [0] * 4
for curve, endpoints in zip(boundary["curves"], boundary["curve_boundary_roots"]):
    assert not curve["closed"]
    for point, root_id in zip((curve["points"][0], curve["points"][-1]), endpoints):
        assert 1 <= root_id <= 4
        uses[root_id - 1] += 1
        root = roots[root_id - 1]
        assert point == root["point"]
        assert point[2] == (0 if root["height_boundary"] == 0 else .5)
        assert native.value(face, root["first"]) * native.value(face, root["last"]) <= 0
        for endpoint in (root["first"], root["last"]):
            assert math.dist(point, endpoint) <= root["vertex_tolerance"]
assert uses == [1] * 4
rings = native.build_gyroid_cylinder_rings(face, *boundary_args)
assert rings["ring_edges_verified"] and rings["boundary_incidence_verified"]
assert not rings["topology_validated"] and not rings["solid_validated"]
for cap, arcs in enumerate(rings["boundary_rings"]):
    assert len(arcs) == 2 and arcs[0]["negative"] != arcs[1]["negative"]
    assert abs(sum(a["angle_range"][1] - a["angle_range"][0] for a in arcs) - 2 * math.pi) < 1e-12
    for arc in arcs:
        assert arc["edge_tolerance"] <= .1
        assert arc["reversed"] == (cap == 0)
        for name, root_id in (("first", arc["lower_root"]), ("last", arc["upper_root"])):
            root = rings["boundary_roots"][root_id - 1]
            assert math.dist(arc[name], root["point"]) <= root["vertex_tolerance"]
assert native.build_gyroid_cylinder_rings(restored, *boundary_args) == rings
failed_rings = native.build_gyroid_cylinder_rings(face, *boundary_args, maximum_cells=4)
assert not failed_rings["ring_edges_verified"] and failed_rings["boundary_rings"] == [[], []]
empty_placed = native.translated(native.gyroid(10, 10, (-10, -10, -10), (10, 10, 10)), (1000, 0, 0))
precision_limited = native.build_gyroid_cylinder_rings(
    empty_placed, (1000, 0, 0), *boundary_args[1:3], .5, boundary_args[4], (-4.2, 3.7),
    distance_tolerance=2e-9)
assert precision_limited["resolved"] and not precision_limited["ring_edges_verified"]
assert precision_limited["boundary_rings"] == [[], []]
assert native.trace_gyroid_cylinder_boundary(restored, *boundary_args) == boundary
failed = native.trace_gyroid_cylinder_boundary(face, *boundary_args, maximum_cells=4)
assert not failed["resolved"] and not failed["boundary_incidence_verified"]
assert not failed["boundary_roots"] and not failed["curve_boundary_roots"]
closed_boundary = native.trace_gyroid_cylinder_boundary(face, *periodic_args)
assert closed_boundary["resolved"] and closed_boundary["boundary_incidence_verified"]
assert not closed_boundary["boundary_roots"] and closed_boundary["curve_boundary_roots"] == [(0, 0)]
assert native.dumps(face) == record
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
