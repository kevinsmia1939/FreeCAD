# SPDX-License-Identifier: LGPL-2.1-or-later
"""Both material signs and reversed/translated frames retain closed previews."""
import math
import FreeCAD as App
import Implicit
import ImplicitOCCT as native

for negative in (False, True):
    origin = (1.2, -.4, 2.1) if negative else (0, 0, 0)
    axis = (0, 0, -1) if negative else (0, 0, 1)
    source = native.gyroid(10, .21, (-10, -10, -10), (10, 10, 10))
    if negative:
        source = native.translated(source, origin)
    geometry = native.check_cylinder_shell_geometry(
        source, origin, axis, (1, 0, 0), .5, (.27, .27 + 2*math.pi), (-1.7, 1.3), negative=negative)
    assert geometry["shell_geometry_validated"], geometry["geometry_reason"]
    initial = native.build_cylinder_solid(geometry["geometry_handle"])
    raw = native.loads_cylinder_solid(native.dumps_cylinder_solid(initial["solid_handle"]))
    restored = native.qualify_stored_cylinder_geometry(raw["stored_solid_handle"])
    solid = native.qualify_stored_cylinder_solid(restored["stored_geometry_handle"])
    assert solid["solid_validated"], solid["solid_reason"]
    doc = App.newDocument("PreviewSigns")
    obj = doc.addObject("Implicit::NativeCylinderFeature", "Cylinder")
    obj.Geometry = solid["qualified_stored_solid_handle"]
    before = native.dumps_cylinder_solid(obj.Geometry)
    mesh = Implicit.cylinderPreview(obj, 6)
    assert mesh["mesh_incidence_verified"] and not mesh["surface_distance_verified"]
    assert set(mesh["native_faces"]) == {1, 2, 3}
    vertices = [App.Vector(*p) for p in mesh["points"]]
    volume = sum(vertices[a].dot(vertices[b].cross(vertices[c]))/6 for a, b, c in mesh["triangles"])
    assert volume > 0, volume
    assert mesh["root_point_bound"] <= .001 and mesh["upload_bound"] < .1
    sampled = 0
    for index, (triangle, face) in enumerate(zip(mesh["triangles"], mesh["native_faces"])):
        if face != 3 or index % 37:
            continue
        p = vertices[triangle[0]]
        gradient = App.Vector(*native.gradient(source, (p.x, p.y, p.z)))
        expected = gradient * (1 if negative else -1)
        normal = App.Vector(*mesh["corner_normals"][3*index])
        assert normal.dot(expected)/expected.Length > .999999
        sampled += 1
    assert sampled
    assert native.dumps_cylinder_solid(obj.Geometry) == before
    App.closeDocument(doc.Name)
print("native implicit cylinder preview smoke test passed", flush=True)
