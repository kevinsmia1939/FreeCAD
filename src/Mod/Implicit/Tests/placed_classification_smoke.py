# SPDX-License-Identifier: LGPL-2.1-or-later
"""Representation-aware placed region classification, never solid validation."""
import math
import os
import tempfile
import traceback
import FreeCAD as App
import Implicit
import ImplicitMixed
import ImplicitOCCT as native


def check(snapshot, pose, point, state, tolerance=.1):
    placed = pose.multVec(App.Vector(point))
    query = Implicit.classifyNative(snapshot, tuple(placed), tolerance)
    assert query["state"] == state, query
    assert query["solid_validated"] is False and query["placement_resolved"]
    assert 0 <= query["placement_error_bound"] < tolerance
    if state in ("inside", "outside"):
        assert query["distance_lower_bound"] > tolerance
        # Known retained planar cap witnesses give independent physical upper
        # bounds on the true boundary distance for this fixture.
        if point == (0, 0, 2) and state == "inside":
            assert query["distance_lower_bound"] <= .31 + 1e-12
        if point == (10, 0, 2):
            assert query["distance_lower_bound"] <= 7.07 + 1e-12
    elif state == "near_boundary":
        assert query["has_boundary_witness"]
        assert query["witness_distance_upper_bound"] <= tolerance
        assert query["witness_bracket_width"] <= tolerance / 256
        for key in ("witness_first", "witness_last"):
            distance = (App.Vector(query[key]) - placed).Length
            assert distance <= query["witness_distance_upper_bound"] + 1e-12
        if point == (-.33, 0, 2):
            witness = pose.inverse().multVec(App.Vector(query["witness_first"]))
            assert (witness - App.Vector(-.31, 0, 2)).Length < 1e-10
    return query


def main():
    producer = ImplicitMixed.demo()
    doc = producer.Document
    obj = doc.addObject("Implicit::NativeFeaturePython", "Snapshot")
    obj.Geometry = producer.Geometry
    local = Implicit.nativeGeometry(obj)
    for point in ((0, 0, 2), (-.33, 0, 2), (10, 0, 2)):
        expected = native.classify_mixed(obj.Geometry, point)
        query = Implicit.classifyNative(local, point)
        assert query["state"] == expected["state"]
        assert query["distance_lower_bound"] == expected["distance_lower_bound"]
        assert query["placement_error_bound"] == 0
    obj.Placement = App.Placement(App.Vector(17, -4, 3), App.Rotation(App.Vector(1, 2, 3), 31))
    parent = doc.addObject("App::Part", "Container")
    parent.addObject(obj)
    parent.Placement = App.Placement(App.Vector(2, 7, -3), App.Rotation(23, 0, 0))
    link = doc.addObject("App::Link", "Instance")
    link.LinkedObject = parent
    link.LinkTransform = True
    link.LinkPlacement = App.Placement(App.Vector(-6, 1, 9), App.Rotation(0, 17, 0))
    nested_pose = parent.Placement.multiply(obj.Placement)
    link_pose = link.LinkPlacement.multiply(nested_pose)
    for snapshot, pose in ((obj.getSubObject(""), obj.Placement),
            (parent.getSubObject(obj.Name + "."), nested_pose),
            (link.getSubObject(obj.Name + "."), link_pose)):
        check(snapshot, pose, (0, 0, 2), "inside")
        check(snapshot, pose, (-.33, 0, 2), "near_boundary")
        check(snapshot, pose, (10, 0, 2), "outside")
        check(snapshot, pose, (1.25, 1.25, 1.25), "unresolved", .4)
    retained = link.getSubObject(obj.Name + ".")
    with tempfile.TemporaryDirectory(prefix="implicit-classification-") as directory:
        filename = os.path.join(directory, "placed.FCStd")
        name, link_name, producer_name = obj.Name, link.Name, producer.Name
        doc.saveAs(filename)
        App.closeDocument(doc.Name)
        doc = App.openDocument(filename)
        obj, link = doc.getObject(name), doc.getObject(link_name)
        producer = doc.getObject(producer_name)
        check(link.getSubObject(obj.Name + "."), link_pose, (0, 0, 2), "inside")
        producer.Operation = "BoxMinusField"
        doc.recompute()
        assert producer.isValid(), producer.BackendStatus
        obj.Geometry = producer.Geometry
        check(link.getSubObject(obj.Name + "."), link_pose, (0, 0, 2), "outside")
        check(retained, link_pose, (0, 0, 2), "inside")
    for bad in (None, obj, obj.Geometry):
        try:
            Implicit.classifyNative(bad, (0, 0, 2))
        except TypeError:
            pass
        else:
            raise AssertionError("wrong classification representation accepted")
    for point, tolerance in (((math.nan, 0, 0), .1), ((0, 0, 2), 0), ((0, 0, 2), math.inf)):
        try:
            Implicit.classifyNative(local, point, tolerance)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid classification query accepted")
    try:
        Implicit.classifyNative(obj.getSubObject("Cap1"), (0, 0, 2))
    except NotImplementedError:
        pass
    else:
        raise AssertionError("selected boundary element treated as a volume region")
    obj.Placement = App.Placement(App.Vector(1e15, -1e15, 1e15), App.Rotation())
    unresolved = Implicit.classifyNative(obj.getSubObject(""), (1e15, -1e15, 1e15 + 2))
    assert unresolved["state"] == "unresolved" and not unresolved["placement_resolved"]
    assert unresolved["placement_error_bound"] >= .1 and not unresolved["has_boundary_witness"]
    App.closeDocument(doc.Name)
    check(retained, link_pose, (0, 0, 2), "inside")
    crossing = ImplicitMixed.demo(open_contours=True)
    crossing.Placement = App.Placement(App.Vector(9, -12, 3), App.Rotation(11, 7, 19))
    root = check(crossing.getSubObject(""), crossing.Placement, (0, 0, 0), "near_boundary")
    face = native.inspect_mixed(crossing.Geometry)["implicit_face"]
    inverse = crossing.Placement.inverse()
    a, b = [tuple(inverse.multVec(App.Vector(root[key]))) for key in ("witness_first", "witness_last")]
    assert native.value(face, a) * native.value(face, b) < 0
    assert native.in_domain(face, a) and native.in_domain(face, b)
    App.closeDocument(crossing.Document.Name)
    print("native implicit placed classification smoke test passed", flush=True)


try:
    main()
except BaseException:
    traceback.print_exc()
    os._exit(1)
