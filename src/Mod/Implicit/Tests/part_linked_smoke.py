# SPDX-License-Identifier: LGPL-2.1-or-later
"""Requires built Part and the OCCT extension, not the system FreeCAD."""
import math
import os
import tempfile
import traceback
import FreeCAD as App
import Part  # noqa: F401
import Implicit


def main():
    doc = App.newDocument("PartLinkedFields")
    box = doc.addObject("Part::Box", "Box")
    box.Length, box.Width, box.Height = 4, 6, 8
    box.Placement = App.Placement(App.Vector(10, 0, 0), App.Rotation(App.Vector(0, 0, 1), 90))
    brep = doc.addObject("Implicit::Feature", "BRepField")
    brep.Operation = "BRep"
    brep.Left = box
    brep.Tolerance = 1e-7
    brep.DomainMin, brep.DomainMax = (-10, -5, -5), (15, 15, 15)
    sphere = doc.addObject("Implicit::Feature", "Sphere")
    sphere.Function = "Sphere"
    sphere.Center = (8, 2, 4)
    sphere.Radius = 2
    mixed = doc.addObject("Implicit::Feature", "Mixed")
    mixed.Operation = "Intersection"
    mixed.Left, mixed.Right = brep, sphere
    doc.recompute()
    for obj in (box, brep, mixed):
        assert obj.isValid(), (obj.Name, obj.State)
    assert math.isclose(Implicit.evaluate(brep, 8, 2, 4), -2, abs_tol=1e-6)
    assert Implicit.classify(mixed, 8, 2, 4) == "inside"
    assert Implicit.classify(mixed, 8, 2, 7) == "outside"
    # Native representation dispatch also accepts a Part object directly.
    mixed.Left = box
    doc.recompute()
    assert Implicit.classify(mixed, 8, 2, 4) == "inside"
    mixed.Left = brep
    doc.recompute()
    before = mixed.CacheRevision
    bounds_before = Implicit.bounds(brep)
    box.Length = 1
    doc.recompute()
    assert mixed.CacheRevision > before
    assert Implicit.bounds(brep) != bounds_before, "live BRep domain did not follow source edit"
    assert math.isclose(Implicit.evaluate(brep, 8, 2, 4), 1, abs_tol=1e-6)
    assert Implicit.classify(mixed, 8, 2, 4) == "outside"
    box.Length = 4
    box.Placement.Base = (20, 0, 0)
    doc.recompute()
    assert Implicit.classify(brep, 18, 2, 4) == "inside"
    assert Implicit.classify(brep, 8, 2, 4) == "outside"
    # Result placement is an additional transform, not double source placement.
    brep.Placement.Base = (10, 0, 0)
    doc.recompute()
    assert math.isclose(Implicit.evaluate(brep, 18, 2, 4), -2, abs_tol=1e-6)
    brep.Placement.Base = (0, 0, 0)
    doc.recompute()
    # Move the sphere to intersect the live source in document coordinates.
    sphere.Center = (18, 2, 4)
    doc.recompute()
    assert Implicit.classify(mixed, 18, 2, 4) == "inside"
    mixed.AutoDomain = False
    mixed.DomainMin, mixed.DomainMax = (15, -1, 1), (21, 5, 7)
    doc.recompute()
    mesh = Implicit.tessellate(mixed, 8)
    assert mesh["triangles"]
    with tempfile.TemporaryDirectory(prefix="implicit-part-linked-") as directory:
        path = os.path.join(directory, "mixed.FCStd")
        doc.saveAs(path)
        App.closeDocument(doc.Name)
        doc = App.openDocument(path)
        doc.recompute()
        box, brep, mixed = (doc.getObject(name) for name in ("Box", "BRepField", "Mixed"))
        assert brep.Left == box and mixed.Left == brep
        assert not brep.FieldGraph
        assert Implicit.classify(mixed, 18, 2, 4) == "inside"
        box.Length = 1
        doc.recompute()
        assert Implicit.classify(mixed, 18, 2, 4) == "outside"
    invalid = doc.addObject("Part::Feature", "NotSolid")
    invalid.Shape = Part.makePlane(2, 2)
    brep.Left = invalid
    doc.recompute()
    assert not brep.isValid() and not mixed.isValid()
    assert brep.StatusMessage and mixed.StatusMessage
    brep.Left = box
    doc.recompute()
    assert brep.isValid() and mixed.isValid()
    doc.removeObject("Box")
    doc.recompute()
    assert not brep.isValid() and not mixed.isValid()
    App.closeDocument(doc.Name)
    print("native implicit Part linked smoke test passed")


try:
    main()
except BaseException:
    traceback.print_exc()
    raise
