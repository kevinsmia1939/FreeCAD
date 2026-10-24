# SPDX-License-Identifier: LGPL-2.1-or-later
"""Native mathematical face feet and bounded conventional-cap projections."""
import math
import traceback
import FreeCAD as App
import Implicit
import ImplicitMixed
import ImplicitSolid
import ImplicitOCCT as native
import Part


def near(geometry, seed):
    return [App.Vector(*point) for point in Implicit.snapNative(geometry, "Near", tuple(seed))]


def main():
    doc = App.newDocument("NativeFaceSnaps")
    field = doc.addObject("Implicit::Feature", "Gyroid")
    field.Function, field.Period = "Gyroid", 10
    field.DomainMin, field.DomainMax = (0, 0, 0), (10, 10, 10)
    box = doc.addObject("Part::Box", "Box")
    box.Length = box.Width = box.Height = 10
    doc.recompute()
    source = ImplicitMixed.create(field, box, corner_policy="Regularized")
    solid = ImplicitSolid.create(source)
    root = App.Vector(2.5, 2.5, 2.5)
    normal = App.Vector(-1, -1, -1).normalize()
    seed = root + normal * .05
    for obj in (source, solid):
        revision, fingerprint = obj.NativeRevision, obj.InputFingerprint
        geometry = obj.getSubObject("NativeFace1")
        points = near(geometry, seed)
        assert len(points) == 1
        point = points[0]
        assert (point - root).Length < .1 / 1024
        k = 2 * math.pi / 10
        x, y, z = (k * coordinate for coordinate in point)
        value = math.sin(x) * math.cos(y) + math.sin(y) * math.cos(z) + math.sin(z) * math.cos(x)
        assert abs(value) < 1e-5
        assert near(geometry, App.Vector()) == []  # Removed corner/domain boundary.
        assert near(geometry, App.Vector(50, 50, 50)) == []  # No jump to a remote sheet.
        assert obj.NativeRevision == revision and obj.InputFingerprint == fingerprint
    # Cap projection is constrained to its actual stored trim, including holes.
    data = native.inspect_mixed(source.Geometry)
    for index, cap in enumerate(data["planar_caps"], 1):
        selected = source.getSubObject("Cap" + str(index))
        vertices, triangles = cap.tessellate(.1)
        triangle = triangles[len(triangles) // 2]
        interior = sum((vertices[i] for i in triangle), App.Vector()) / 3
        normal = cap.normalAt(0, 0)
        cursor = interior + normal * .05
        projected = near(selected, cursor)
        assert len(projected) == 1
        assert (projected[0] - interior).Length < 1e-7
        outside = interior + App.Vector(30, -20, 10)
        candidate = near(selected, outside)[0]
        distance = Part.Vertex(outside).distToShape(cap)[0]
        assert abs((outside - candidate).Length - distance) < 1e-6
        assert Part.Vertex(candidate).distToShape(cap)[0] < 1e-7
    source.Operation = "BoxMinusField"
    doc.recompute()
    assert solid.SolidValidated
    for obj in (source, solid):
        assert (near(obj.getSubObject("NativeFace1"), seed)[0] - root).Length < .1 / 1024
    source.Operation = "Common"
    doc.recompute()
    hole_source = ImplicitMixed.demo()
    hole_data = native.inspect_mixed(hole_source.Geometry)
    hole_center = App.Vector(1.25, 1.25, 1.25)
    found_hole = False
    for index, cap in enumerate(hole_data["planar_caps"], 1):
        if len(cap.Wires) < 2 or cap.BoundBox.ZLength > 1e-8:
            continue
        distance = Part.Vertex(hole_center).distToShape(cap)[0]
        if distance <= .01:
            continue
        candidate = near(hole_source.getSubObject("Cap" + str(index)), hole_center)[0]
        assert abs((candidate - hole_center).Length - distance) < 1e-6
        assert Part.Vertex(candidate).distToShape(cap)[0] < 1e-7
        found_hole = True
    assert found_hole
    App.closeDocument(hole_source.Document.Name)
    App.setActiveDocument(doc.Name)
    parent = doc.addObject("App::Part", "Parent")
    parent.Placement = App.Placement(App.Vector(7, -4, 3), App.Rotation(31, 17, 11))
    instance = doc.addObject("App::Link", "Instance"); instance.setLink(solid)
    instance.LinkTransform = True
    instance.LinkPlacement = App.Placement(App.Vector(2, 3, -1), App.Rotation(13, 23, 7))
    parent.addObject(instance)
    doc.recompute()
    pose = parent.Placement.multiply(instance.LinkPlacement).multiply(solid.Placement)
    selected = parent.getSubObject(instance.Name + ".NativeFace1")
    expected = pose.multVec(root)
    world_seed = pose.multVec(seed)
    assert (near(selected, world_seed)[0] - expected).Length < .1 / 1024
    App.closeDocument(doc.Name)
    assert (near(selected, world_seed)[0] - expected).Length < .1 / 1024
    print("native implicit face snapping smoke test passed", flush=True)


try:
    main()
except BaseException:
    traceback.print_exc()
    raise
