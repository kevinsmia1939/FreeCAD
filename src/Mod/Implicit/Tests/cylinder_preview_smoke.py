# SPDX-License-Identifier: LGPL-2.1-or-later
"""Both material signs and reversed/translated frames retain closed previews."""
import math
import struct
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
    coarse = Implicit.cylinderPreview(obj, 2)
    assert not coarse["field_triangle_distance_verified"]
    assert coarse["field_triangle_reason"]
    assert not coarse["surface_distance_verified"]
    mesh = Implicit.cylinderPreview(obj, 6)
    assert mesh["mesh_incidence_verified"] and not mesh["surface_distance_verified"]
    assert set(mesh["native_faces"]) == {1, 2, 3}
    vertices = [App.Vector(*p) for p in mesh["points"]]
    volume = sum(vertices[a].dot(vertices[b].cross(vertices[c]))/6 for a, b, c in mesh["triangles"])
    assert volume > 0, volume
    assert mesh["root_point_bound"] <= .001 and mesh["upload_bound"] < .1
    assert mesh["field_triangle_distance_verified"], mesh["field_triangle_reason"]
    assert mesh["field_triangle_buffer"] == "binary32_upload"
    assert mesh["field_triangles_checked"] == mesh["native_faces"].count(3)
    assert 0 < mesh["field_triangle_distance_bound"] <= .1
    uploaded = [App.Vector(*(struct.unpack('f', struct.pack('f', v))[0] for v in p))
                for p in mesh["points"]]
    sampled = 0
    for index, (triangle, face) in enumerate(zip(mesh["triangles"], mesh["native_faces"])):
        if face != 3 or index % 37:
            continue
        p = vertices[triangle[0]]
        gradient = App.Vector(*native.gradient(source, (p.x, p.y, p.z)))
        expected = gradient * (1 if negative else -1)
        normal = App.Vector(*mesh["corner_normals"][3*index])
        assert normal.dot(expected)/expected.Length > .999999
        # Independent interior samples exercise the reported whole-triangle
        # bound on the actual float buffer, rather than only its root vertices.
        for weights in ((1/3, 1/3, 1/3), (.7, .2, .1)):
            point = sum((uploaded[v] * w for v, w in zip(triangle, weights)), App.Vector())
            # Keep the witness inside the masked radius if float upload moved
            # a boundary point outward. Interior samples here are strictly inside.
            lo, hi = -1.7, 1.3
            def at(height):
                return (point.x, point.y, origin[2] + axis[2] * height)
            flo = native.value(source, at(lo))
            for _ in range(60):
                mid = (lo + hi)/2
                if native.value(source, at(mid)) * flo > 0:
                    lo = mid
                else:
                    hi = mid
            distance = abs(point.z - at((lo + hi)/2)[2])
            assert distance <= mesh["field_triangle_distance_bound"], distance
        sampled += 1
    assert sampled
    assert native.dumps_cylinder_solid(obj.Geometry) == before
    App.closeDocument(doc.Name)
print("native implicit cylinder preview smoke test passed", flush=True)
