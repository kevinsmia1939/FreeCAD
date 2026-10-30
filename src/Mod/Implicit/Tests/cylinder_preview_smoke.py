# SPDX-License-Identifier: LGPL-2.1-or-later
"""Both material signs and reversed/translated frames retain closed previews."""
import math
import struct
import FreeCAD as App
import Implicit
import ImplicitOCCT as native

def triangle_distance(point, a, b, c):
    """Independent point-to-triangle distance, including the three boundaries."""
    ab, ac = b-a, c-a
    normal = ab.cross(ac)
    projected = point - normal * ((point-a).dot(normal)/normal.dot(normal))
    v = projected-a
    aa, bb, cc = ab.dot(ab), ab.dot(ac), ac.dot(ac)
    denominator = aa*cc-bb*bb
    u = (cc*v.dot(ab)-bb*v.dot(ac))/denominator
    w = (aa*v.dot(ac)-bb*v.dot(ab))/denominator
    if u >= 0 and w >= 0 and u+w <= 1:
        return (point-projected).Length
    distances = []
    for first, last in ((a,b), (b,c), (c,a)):
        edge = last-first
        t = max(0, min(1, (point-first).dot(edge)/edge.dot(edge)))
        distances.append((point-first-edge*t).Length)
    return min(distances)

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
    assert mesh["cap_disk_distance_verified"], mesh["cap_disk_reason"]
    assert 0 < mesh["cap_disk_distance_bound"] <= .1
    assert coarse["cap_disk_distance_verified"], coarse["cap_disk_reason"]
    assert mesh["cap_disk_distance_bound"] < coarse["cap_disk_distance_bound"]
    cap_triangles = [tuple(uploaded[i] for i in tri)
                     for tri, face in zip(mesh["triangles"], mesh["native_faces"]) if face == 1]
    # The actual retained cap is the opposite end of the qualified axial sheet.
    cap_z = sum(p.z for p in cap_triangles[0])/3
    cap_height = min((-1.7, 1.3), key=lambda h: abs(origin[2]+axis[2]*h-cap_z))
    cap_z = origin[2]+axis[2]*cap_height
    for radius in (0, .25, .5):
        for i in range(29):
            angle = 2*math.pi*(i+.37)/29
            point = App.Vector(origin[0]+radius*math.cos(angle),
                               origin[1]+radius*math.sin(angle), cap_z)
            distance = min(triangle_distance(point, *tri) for tri in cap_triangles)
            assert distance <= mesh["cap_disk_distance_bound"], distance
    for tri in cap_triangles:
        point = sum(tri, App.Vector())/3
        radial_excess = max(0, math.hypot(point.x-origin[0], point.y-origin[1])-.5)
        assert math.hypot(radial_excess, point.z-cap_z) <= mesh["cap_disk_distance_bound"]
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
