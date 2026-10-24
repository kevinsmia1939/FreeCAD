# SPDX-License-Identifier: LGPL-2.1-or-later
"""Owned native picks expose stored vertices and finite-edge snap locations."""
import math
import traceback
import FreeCAD as App
import Implicit
import ImplicitMixed
import ImplicitSolid


def query(geometry, mode, cursor=(0, 0, 0)):
    return [App.Vector(*point) for point in Implicit.snapNative(geometry, mode, tuple(cursor))]


def rejects(call):
    try:
        call()
    except (ValueError, TypeError, RuntimeError):
        return
    raise AssertionError("Unsupported native snap query succeeded")


def main():
    source = ImplicitMixed.demo(open_contours=True)
    doc = source.Document
    solid = ImplicitSolid.create(source)
    for obj in (source, solid):
        proof = "SolidValidated" if obj is solid else "SeamBoundVerified"
        before = obj.NativeRevision, obj.InputFingerprint, obj.BackendStatus, getattr(obj, proof)
        vertex = obj.getSubObject("Vertex1")
        expected = vertex.getPoints(.1)[0][0]
        assert query(vertex, "Endpoint") == [expected]
        assert query(vertex, "Near") == query(vertex, "Midpoint") == []
        geometry = Implicit.nativeGeometry(obj)
        straight = curved = False
        for index in range(1, geometry.countSubElements("Edge") + 1):
            edge = obj.getSubObject("Edge" + str(index))
            points, lines = edge.getLines(.1)
            endpoints = query(edge, "Endpoint")
            assert len(endpoints) in (1, 2)
            assert all(min((endpoint - point).Length for point in (points[0], points[-1])) < 1e-10
                       for endpoint in endpoints)
            midpoint = query(edge, "Midpoint")[0]
            assert (query(edge, "Near", midpoint)[0] - midpoint).Length < 1e-10
            if len(points) == 2:
                straight = True
                assert (midpoint - (points[0] + points[1]) * .5).Length < 1e-12
                outside = points[0] - (points[1] - points[0]) * 10
                assert (query(edge, "Near", outside)[0] - points[0]).Length < 1e-10
            else:
                curved = True
                total = sum((points[j] - points[i]).Length for i, j in lines)
                prefix = 0
                found = False
                for i, j in lines:
                    a, b = points[i], points[j]
                    if abs((midpoint - a).Length + (b - midpoint).Length - (b - a).Length) < 1e-10:
                        assert abs(prefix + (midpoint - a).Length - total / 2) < 1e-9
                        found = True
                        break
                    prefix += (b - a).Length
                assert found
        assert straight and curved
        for name in ("NativeFace1", "Cap1"):
            selected = obj.getSubObject(name)
            assert all(query(selected, mode) == [] for mode in ("Endpoint", "Midpoint"))
        rejects(lambda: Implicit.snapNative(geometry, "Endpoint", (0, 0, 0)))
        rejects(lambda: Implicit.snapNative(vertex, "Center", (0, 0, 0)))
        for tolerance in (0, -1, math.inf, math.nan):
            rejects(lambda: Implicit.snapNative(vertex, "Endpoint", (0, 0, 0), tolerance))
        rejects(lambda: Implicit.snapNative(vertex, "Near", (math.nan, 0, 0)))
        assert (obj.NativeRevision, obj.InputFingerprint, obj.BackendStatus, getattr(obj, proof)) == before

    # A picked container/link path already carries the complete rigid placement.
    # Queries apply it once, and retained selected snapshots own their geometry.
    parent = doc.addObject("App::Part", "Container")
    parent.Placement = App.Placement(App.Vector(11, -2, 7), App.Rotation(31, 7, 13))
    link = doc.addObject("App::Link", "Instance")
    link.setLink(solid); link.LinkTransform = True
    link.LinkPlacement = App.Placement(App.Vector(3, 5, -1), App.Rotation(12, 23, 17))
    parent.addObject(link)
    doc.recompute()
    selected = parent.getSubObject(link.Name + ".Vertex1")
    local = solid.getSubObject("Vertex1").getPoints(.1)[0][0]
    pose = parent.Placement.multiply(link.LinkPlacement).multiply(solid.Placement)
    assert (query(selected, "Endpoint")[0] - pose.multVec(local)).Length < 1e-10
    local_edge = solid.getSubObject("Edge1")
    placed_edge = parent.getSubObject(link.Name + ".Edge1")
    midpoint = pose.multVec(query(local_edge, "Midpoint")[0])
    assert (query(placed_edge, "Midpoint")[0] - midpoint).Length < 1e-10
    assert (query(placed_edge, "Near", midpoint)[0] - midpoint).Length < 1e-10
    retained = query(selected, "Endpoint")
    link.LinkPlacement.Base = (1e15, 0, 0)
    doc.recompute()
    huge = parent.getSubObject(link.Name + ".Vertex1")
    rejects(lambda: query(huge, "Endpoint"))
    assert query(selected, "Endpoint") == retained
    App.closeDocument(doc.Name)
    assert query(selected, "Endpoint") == retained
    print("native implicit snapping smoke test passed", flush=True)


try:
    main()
except BaseException:
    traceback.print_exc()
    raise
