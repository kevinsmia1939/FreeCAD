# SPDX-License-Identifier: LGPL-2.1-or-later
"""Actual native cylinder-restricted implicit faces, ownership and refusal gates."""
import math
import FreeCAD as App
import ImplicitOCCT as native

source = native.gyroid(10, .21, (-10, -10, -10), (10, 10, 10))
record = native.dumps(source)
args = ((0, 0, 0), (0, 0, 1), (1, 0, 0), .5, (.27, .27 + 2 * math.pi), (-1.7, 1.3))
for negative in (True, False):
    result = native.build_cylinder_implicit_faces(source, *args, negative=negative)
    assert result["implicit_faces_attached"], result["attachment_reason"]
    assert result["mathematical_correspondence_verified"] and result["projected_proxy_topology_validated"]
    assert not result["solid_validated"] and result["axial_derivative_lower_bound"] > 0
    assert len(result["implicit_faces"]) == 1
    face = result["implicit_faces"][0]
    info = native.info(face)
    assert info["is_implicit"] and info["cylinder_restricted"] and not info["has_parametric_surface"]
    assert native.in_domain(face, (0, 0, 0))
    assert not native.in_domain(face, (.6, 0, 0))
    result["sides"][0].translate(App.Vector(100, 0, 0))
    result["implicit_faces_attached"] = False
    fresh = native.inspect_cylinder_implicit_faces(result["faces_handle"])
    assert fresh["implicit_faces_attached"] and fresh["sides"][0].BoundBox.XMax < 1
    assert fresh["field_record"] == record
partial_args = args[:-1] + ((0, .5),)
partial = native.build_cylinder_implicit_faces(source, *partial_args)
assert not partial["implicit_faces_attached"] and partial["implicit_faces"] == []
assert not partial["mathematical_correspondence_verified"]
try:
    native.inspect_cylinder_implicit_faces(source)
except TypeError:
    pass
else:
    raise AssertionError("Wrong owner accepted")
assert native.dumps(source) == record
print("native implicit cylinder implicit faces smoke test passed", flush=True)
