# SPDX-License-Identifier: LGPL-2.1-or-later
"""Owned cylinder-side regions, detached previews and explicit solid boundary."""
import math
import FreeCAD as App
import ImplicitOCCT as native

source = native.gyroid(10, .21, (-10, -10, -10), (10, 10, 10))
record = native.dumps(source)
args = ((0, 0, 0), (0, 0, 1), (1, 0, 0), .5, (3, 3 + 2 * math.pi), (0, .5))
a = native.build_cylinder_sides(source, *args)
b = native.build_cylinder_sides(source, *args, negative=False)
for result in (a, b):
    assert result["side_topology_validated"], result["side_reason"]
    assert result["cap_topology_validated"] and result["side_boundary_verified"]
    assert not result["solid_validated"]
    assert result["field_record"] == record
    assert 0 < result["side_surface_deviation_bound"] <= .1
    assert result["side_contour_bound"] <= .1
    assert result["side_area_error_estimate"] < 1e-8
    assert result["sides"] and all(f.ShapeType == "Face" and f.isValid() for f in result["sides"])
assert abs(a["side_area"] + b["side_area"] - math.pi * .5) < 1e-6
handle = a["sides_handle"]
a["sides"][0].translate(App.Vector(100, 0, 0))
a["side_topology_validated"] = False
fresh = native.inspect_cylinder_sides(handle)
assert fresh["side_topology_validated"] and fresh["sides"][0].BoundBox.XMax < 1
assert native.dumps(source) == record
failed = native.build_cylinder_sides(source, *args, maximum_cells=4)
assert not failed["side_topology_validated"] and failed["sides"] == []
for bad in (source, b["sides"][0]):
    try:
        native.inspect_cylinder_sides(bad)
    except TypeError:
        pass
    else:
        raise AssertionError("Wrong owner type accepted")
print("native implicit cylinder sides smoke test passed", flush=True)
