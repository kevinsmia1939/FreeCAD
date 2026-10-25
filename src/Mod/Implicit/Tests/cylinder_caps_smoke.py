# SPDX-License-Identifier: LGPL-2.1-or-later
"""Actual planar cap regions, owned topology, detached previews and failure gates."""
import math
import FreeCAD as App
import ImplicitOCCT as native

source = native.gyroid(10, .21, (-10, -10, -10), (10, 10, 10))
record = native.dumps(source)
args = ((0, 0, 0), (0, 0, 1), (1, 0, 0), .5, (3, 3 + 2 * math.pi), (0, .5))
negative = native.build_cylinder_caps(source, *args)
positive = native.build_cylinder_caps(source, *args, negative=False)
for report in (negative, positive):
    assert report["cap_topology_validated"] and report["contour_bound_verified"], report["reason"]
    assert not report["solid_validated"] and report["contour_bound"] <= .1
    assert report["field_record"] == record
    assert report["input_settings"][6] == .1 and report["input_settings"][10] == 2000000
    assert max(report["area_error_estimates"]) <= 1e-8
    for cap, faces in enumerate(report["caps"]):
        assert len(faces) == 1 and faces[0].ShapeType == "Face" and faces[0].isValid()
        assert len(faces[0].Wires) == 1
        assert abs(faces[0].normalAt(0, 0).z - (-1 if cap == 0 else 1)) < 1e-12
for cap in range(2):
    assert abs(negative["cap_areas"][cap] + positive["cap_areas"][cap] - math.pi * .25) < 1e-6
handle = negative["caps_handle"]
negative["caps"][0][0].translate(App.Vector(100, 0, 0))
negative["cap_topology_validated"] = False
fresh = native.inspect_cylinder_caps(handle)
assert fresh["cap_topology_validated"] and fresh["caps"][0][0].BoundBox.XMax < 1
assert fresh["field_record"] == record and native.dumps(source) == record

island = native.gyroid(10, 1.3, (-10, -10, -10), (10, 10, 10))
island_args = ((2.5, 1.25, 0), (0, 0, 1), (1, 0, 0), 1.5, args[4], (0, .02))
holes = native.build_cylinder_caps(island, *island_args)
islands = native.build_cylinder_caps(island, *island_args, negative=False)
assert holes["cap_topology_validated"] and islands["cap_topology_validated"]
for cap in range(2):
    assert len(holes["caps"][cap][0].Wires) == 2 and len(islands["caps"][cap][0].Wires) == 1
    assert abs(holes["cap_areas"][cap] + islands["cap_areas"][cap] - math.pi * 2.25) < 1e-5

for limits in ({"maximum_cells": 4}, {"maximum_nesting_tests": 1}):
    failed = native.build_cylinder_caps(source, *args, **limits)
    assert not failed["cap_topology_validated"] and failed["caps"] == [[], []]
    assert failed["field_edge_counts"] == (0, 0)
try:
    native.inspect_cylinder_caps(source)
except TypeError:
    pass
else:
    raise AssertionError("Primitive face was accepted as a cap-region owner")
for limits in ({"negative": 1}, {"maximum_nesting_tests": 0}, {"maximum_nesting_tests": True}):
    try:
        native.build_cylinder_caps(source, *args, **limits)
    except (TypeError, ValueError):
        pass
    else:
        raise AssertionError("Invalid material/resource policy accepted")
print("native implicit cylinder caps smoke test passed", flush=True)
