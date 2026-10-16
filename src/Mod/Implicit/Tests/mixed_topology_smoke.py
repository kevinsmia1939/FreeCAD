# SPDX-License-Identifier: LGPL-2.1-or-later
"""Whole-box numerical homotopy and transient reference, NOT native-solid validity."""
import traceback
import FreeCAD as App
import ImplicitMixed
import ImplicitOCCT as native


def check(report, expected_euler=None):
    assert report["whole_box_homotopy_resolved"], report["reason"]
    assert report["reference_manifold"]
    assert not report["stored_trim_correspondence_validated"]
    assert not report["topology_validated"] and not report["solid_validated"]
    assert not report["geometry_accuracy_verified"]
    assert report["minimum_homotopy_derivative"] > 0
    if expected_euler is not None:
        assert report["reference_component_euler"] == expected_euler
    assert report["reference_boundary_loops"]
    vertices, triangles = report["reference_vertices"], report["reference_triangles"]
    edges = {}
    for a, b, c in triangles:
        assert len({a, b, c}) == 3
        assert all(0 <= i < len(vertices) for i in (a, b, c))
        for u, v in ((a,b), (b,c), (c,a)):
            edges.setdefault(tuple(sorted((u,v))), []).append((u,v))
    assert len(vertices)-len(edges)+len(triangles) == sum(report["reference_component_euler"])
    assert all(len(uses) == 1 or (len(uses) == 2 and uses[0] == uses[1][::-1])
               for uses in edges.values())
    boundary = {uses[0] for uses in edges.values() if len(uses) == 1}
    for path in report["reference_boundary_loops"]:
        assert path[0] == path[-1]
        for edge in zip(path, path[1:]):
            boundary.remove(edge)
    assert not boundary
    assert all(s["visited"] > 0 for s in report["strata"])


def main():
    for crossing in (False, True):
        obj = ImplicitMixed.demo(open_contours=crossing)
        doc = obj.Document
        for operation in ("Common", "BoxMinusField"):
            obj.Operation = operation
            doc.recompute()
            handle = obj.Geometry
            record = native.dumps_mixed(handle)
            report = native.check_mixed_topology(handle)
            check(report, None if crossing else [1])
            face = native.inspect_mixed(handle)["implicit_face"]
            assert native.check_box_topology(face) == report
            assert native.dumps_mixed(handle) == record
            restored = native.loads_mixed(record)
            check(native.check_mixed_topology(restored["boundary_handle"]))
            assert not native.inspect_mixed(restored["boundary_handle"])["seam_bound_verified"]
            limited = native.check_mixed_topology(handle,32,16,1)
            assert not limited["whole_box_homotopy_resolved"]
            print("native whole box homotopy", crossing, operation,
                  len(report["reference_vertices"]), len(report["reference_triangles"]),
                  report["reference_component_euler"],len(report["reference_boundary_loops"]))
            if crossing and operation == "Common":
                fine = native.check_mixed_topology(handle,64)
                check(fine, report["reference_component_euler"])
                assert len(fine["reference_boundary_loops"]) == len(report["reference_boundary_loops"])
        App.closeDocument(doc.Name)
    check(native.check_mixed_topology(handle))
    hidden = native.gyroid(10, 1.4999, (.3,.3,.3), (2.3,2.3,2.3))
    missing = native.check_box_topology(hidden,4)
    assert not missing["whole_box_homotopy_resolved"]
    assert not missing["reference_manifold"]
    closed = native.gyroid(10,1.45,(.3,.3,.3),(2.3,2.3,2.3))
    sphere = native.check_box_topology(closed)
    assert sphere["whole_box_homotopy_resolved"] and sphere["reference_manifold"]
    assert sphere["reference_component_euler"] == [2]
    assert not sphere["reference_boundary_loops"]
    for call, args, error in (
            (native.check_mixed_topology,(None,),TypeError),
            (native.check_box_topology,(None,),TypeError),
            (native.check_mixed_topology,(handle,3),ValueError),
            (native.check_mixed_topology,(handle,32,16,0),ValueError),
            (native.check_box_topology,(native.sphere((0,0,0),1),),NotImplementedError),
            (native.check_box_topology,(native.translated(closed,(1,0,0)),),NotImplementedError)):
        try:
            call(*args)
        except error:
            pass
        else:
            raise AssertionError("unsupported topology query accepted")
    print("native implicit mixed whole box topology smoke test passed")


try:
    main()
except Exception:
    traceback.print_exc()
    raise
