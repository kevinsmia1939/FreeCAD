# SPDX-License-Identifier: LGPL-2.1-or-later
"""Closed linear-region references are not native CAD shells or solids."""
import math
import traceback
import FreeCAD as App
import ImplicitMixed
import ImplicitOCCT as native


def check(report):
    assert report["whole_box_homotopy_resolved"], report["reason"]
    assert report["surface_reference_manifold"]
    assert report["closed_reference_manifold"], report["reason"]
    for key in ("stored_trim_correspondence_validated", "native_shell_constructed",
                "topology_validated", "solid_validated", "geometry_accuracy_verified"):
        assert not report[key]
    vertices, triangles = report["reference_vertices"], report["reference_triangles"]
    labels, sides = report["reference_triangle_components"], report["reference_triangle_sides"]
    euler, volumes = report["reference_component_euler"], report["reference_component_signed_volumes"]
    assert len(triangles) == len(labels) == len(sides)
    assert len(euler) == len(volumes)
    regions, region_volumes = report["reference_component_regions"], report["reference_region_volumes"]
    assert len(regions) == len(euler)
    assert len(region_volumes) == report["reference_region_count"]
    assert set(regions) == set(range(len(region_volumes)))
    for r,volume in enumerate(region_volumes):
        assert volume > 0
        assert math.isclose(math.fsum(volumes[c] for c in range(len(euler)) if regions[c] == r),
                            volume, rel_tol=1.e-10,abs_tol=1.e-9)
    component_vertices = [set() for _ in euler]
    component_edges = [set() for _ in euler]
    component_triangles = [0 for _ in euler]
    products = [[] for _ in euler]
    edges = {}
    implicit_count = report["reference_implicit_triangle_count"]
    for i, (a, b, c) in enumerate(triangles):
        assert len({a,b,c}) == 3 and all(0 <= n < len(vertices) for n in (a,b,c))
        label = labels[i]
        assert 0 <= label < len(euler)
        component_vertices[label].update((a,b,c))
        component_triangles[label] += 1
        for u,v in ((a,b),(b,c),(c,a)):
            key = tuple(sorted((u,v)))
            edges.setdefault(key,[]).append((u,v,label))
            component_edges[label].add(key)
        a,b,c = vertices[a],vertices[b],vertices[c]
        products[label].append((a[0]*(b[1]*c[2]-b[2]*c[1])
                              +a[1]*(b[2]*c[0]-b[0]*c[2])
                              +a[2]*(b[0]*c[1]-b[1]*c[0]))/6)
        assert sides[i] == -1 if i < implicit_count else 0 <= sides[i] < 6
        if i >= implicit_count:
            axis,sign = sides[i]//2, 1 if sides[i]%2 else -1
            ab,ac = [b[j]-a[j] for j in range(3)],[c[j]-a[j] for j in range(3)]
            assert sign*(ab[(axis+1)%3]*ac[(axis+2)%3]-ab[(axis+2)%3]*ac[(axis+1)%3]) > 0
    assert all(len(uses) == 2 and uses[0][:2] == uses[1][:2][::-1]
               and uses[0][2] == uses[1][2] for uses in edges.values())
    for i in range(len(euler)):
        assert len(component_vertices[i])-len(component_edges[i])+component_triangles[i] == euler[i]
        assert math.isclose(math.fsum(products[i]),volumes[i],rel_tol=1.e-10,abs_tol=1.e-9)
    return math.fsum(volumes)


def main():
    for crossing in (False,True):
        obj = ImplicitMixed.demo(open_contours=crossing)
        doc = obj.Document
        total = 0
        for operation in ("Common","BoxMinusField"):
            obj.Operation = operation
            doc.recompute()
            handle = obj.Geometry
            record = native.dumps_mixed(handle)
            report = native.check_mixed_region_topology(handle)
            total += check(report)
            face = native.inspect_mixed(handle)["implicit_face"]
            assert native.check_box_region_topology(face) == report
            surface = native.check_box_topology(face)
            assert report["reference_vertices"][:report["reference_implicit_vertex_count"]] == surface["reference_vertices"]
            assert report["reference_triangles"][:report["reference_implicit_triangle_count"]] == surface["reference_triangles"]
            assert native.dumps_mixed(handle) == record
            restored = native.loads_mixed(record)
            check(native.check_mixed_region_topology(restored["boundary_handle"]))
            assert not native.inspect_mixed(restored["boundary_handle"])["seam_bound_verified"]
            limited = native.check_mixed_region_topology(handle,32,16,1)
            assert not limited["closed_reference_manifold"]
            assert not limited["native_shell_constructed"]
            print("native closed region reference",crossing,operation,
                  report["reference_component_euler"],report["reference_component_signed_volumes"])
        assert math.isclose(total,obj.Box.Shape.Volume,rel_tol=1.e-11,abs_tol=1.e-9)
        App.closeDocument(doc.Name)
    check(native.check_mixed_region_topology(handle))
    cavity = native.gyroid(10,1.45,(.3,.3,.3),(2.3,2.3,2.3))
    report = native.check_box_region_topology(cavity)
    check(report)
    assert report["reference_component_euler"] == [2,2]
    assert report["reference_region_count"] == 1
    assert report["reference_component_regions"] == [0,0]
    assert sum(v < 0 for v in report["reference_component_signed_volumes"]) == 1
    multiple = native.gyroid(10,1.45,(.3,.3,.3),(12.3,2.3,2.3))
    report = native.check_box_region_topology(multiple,64)
    check(report)
    assert report["reference_component_euler"] == [2,2,2]
    assert report["reference_region_count"] == 1
    assert sum(v < 0 for v in report["reference_component_signed_volumes"]) == 2
    for call,args,error in (
            (native.check_mixed_region_topology,(None,),TypeError),
            (native.check_box_region_topology,(None,),TypeError),
            (native.check_mixed_region_topology,(handle,3),ValueError),
            (native.check_mixed_region_topology,(handle,32,16,0),ValueError),
            (native.check_box_region_topology,(native.sphere((0,0,0),1),),NotImplementedError),
            (native.check_box_region_topology,(native.translated(cavity,(1,0,0)),),NotImplementedError)):
        try:
            call(*args)
        except error:
            pass
        else:
            raise AssertionError("invalid closed reference query accepted")
    print("native implicit mixed closed region topology smoke test passed")


try:
    main()
except Exception:
    traceback.print_exc()
    raise
