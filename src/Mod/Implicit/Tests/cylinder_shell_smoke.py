# SPDX-License-Identifier: LGPL-2.1-or-later
"""Owned native cylinder shell topology, periodic seams and explicit limits."""
import math
import FreeCAD as App
import ImplicitOCCT as native

source = native.gyroid(10, .21, (-10, -10, -10), (10, 10, 10))
record = native.dumps(source)
args = ((0, 0, 0), (0, 0, 1), (1, 0, 0), .5, (.27, .27 + 2 * math.pi), (-1.7, 1.3))
for negative in (True, False):
    result = native.build_cylinder_shell(source, *args, negative=negative)
    assert result["shell_topology_validated"], result["shell_reason"]
    assert result["shell_closed"] and result["implicit_faces_attached"]
    assert not result["shell_geometry_validated"] and not result["solid_validated"]
    assert (result["shell_vertices"], result["shell_edges"], result["shell_faces"], result["shell_euler"]) == (3, 4, 3, 2)
    handle = result["shell_handle"]
    result["shell_topology_validated"] = False
    result["sides"][0].translate(App.Vector(100, 0, 0))
    fresh = native.inspect_cylinder_shell(handle)
    assert fresh["shell_topology_validated"] and fresh["sides"][0].BoundBox.XMax < 1
    assert fresh["field_record"] == record
partial = native.build_cylinder_shell(source, *(args[:-1] + ((0, .5),)))
assert not partial["shell_topology_validated"] and not partial["shell_closed"]
assert partial["shell_faces"] == 0 and not partial["solid_validated"]
try:
    native.inspect_cylinder_shell(source)
except TypeError:
    pass
else:
    raise AssertionError("Wrong shell owner accepted")
assert native.dumps(source) == record
print("native implicit cylinder shell smoke test passed", flush=True)
