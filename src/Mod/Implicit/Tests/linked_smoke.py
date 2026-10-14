# SPDX-License-Identifier: LGPL-2.1-or-later
"""Native linked operations: recompute, placements, signs and persistence."""
import math
import os
import tempfile
import traceback
import FreeCAD as App
import Implicit


def value(feature, point):
    # Rigid transforms introduce roundoff at analytical sample positions.
    return round(Implicit.evaluate(feature, *point), 12)


def main():
    doc = App.newDocument("LinkedFields")
    doc.UndoMode = 1
    left = doc.addObject("Implicit::Feature", "Left")
    left.Function = "Sphere"
    left.Radius = 2
    left.Center = (1, 0, 0)
    left.Placement = App.Placement(App.Vector(3, 4, 0), App.Rotation(App.Vector(0, 0, 1), 90))
    right = doc.addObject("Implicit::Feature", "Right")
    right.Function = "Sphere"
    right.Radius = 1
    right.Placement.Base = (3, 5, 0)
    result = doc.addObject("Implicit::Feature", "Result")
    result.Operation = "Difference"
    result.Left, result.Right = left, right
    result.Placement.Base = (1, 1, 0)
    doc.recompute()
    assert result.isValid(), result.State
    bounds = Implicit.bounds(result)
    assert all(bounds[0][axis] < bounds[1][axis] for axis in range(3))
    assert value(result, (3, 5, 0)) == 1
    assert value(result, (3, 6.5, 0)) == -0.5
    gradient = Implicit.gradient(result, 3, 6.5, 0)
    assert math.isclose(gradient[1], 1, abs_tol=1e-12), gradient
    assert abs(gradient[0]) < 1e-12
    # Shared dependencies stay as links, not duplicated JSON trees.
    assert not result.FieldGraph and result in left.InList and result in right.InList
    revision = result.CacheRevision
    right.Radius = 1.75
    doc.recompute()
    assert result.CacheRevision > revision
    assert value(result, (3, 6.5, 0)) == 0.25
    right.Placement.Base = (7, 5, 0)
    doc.recompute()
    assert value(result, (3, 5, 0)) == -2
    # Result Placement is an additional transform of its assembled local field.
    assert result.Placement.multVec(App.Vector(3, 5, 0)) == App.Vector(4, 6, 0)
    result.Placement.Base = (0, 0, 0)
    doc.recompute()
    assert value(result, (3, 5, 0)) == -2
    result.Operation = "Union"
    doc.recompute()
    assert value(result, (7, 5, 0)) == -1.75
    result.Operation = "Intersection"
    doc.recompute()
    assert value(result, (3, 5, 0)) == 2.25
    # Convert a positive-inside primitive to the canonical set before composition.
    right.InsideNegative = False
    result.Operation = "Difference"
    doc.recompute()
    assert value(result, (3, 5, 0)) == 2.25
    result.InsideNegative = False
    doc.recompute()
    assert value(result, (3, 5, 0)) == -2.25
    assert Implicit.classify(result, 3, 5, 0) == "outside"
    result.InsideNegative = True
    right.InsideNegative = True
    result.Operation = "Band"
    result.Amount = 0.25
    doc.recompute()
    assert value(result, (3, 5, 0)) == 1.75
    result.Operation = "Offset"
    doc.recompute()
    assert value(result, (3, 5, 0)) == -2.25
    # Explicit domain override remains available for expanded offsets.
    result.AutoDomain = False
    result.DomainMin, result.DomainMax = (-12, -12, -12), (12, 12, 12)
    doc.recompute()
    assert Implicit.bounds(result) == ((-12.0, -12.0, -12.0), (12.0, 12.0, 12.0))
    mesh = Implicit.tessellate(result, 12)
    assert mesh["triangles"]
    doc.openTransaction("Change source")
    left.Radius = 3
    doc.recompute()
    assert value(result, (3, 5, 0)) == -3.25
    doc.commitTransaction()
    doc.undo()
    doc.recompute()
    assert value(result, (3, 5, 0)) == -2.25
    with tempfile.TemporaryDirectory(prefix="implicit-linked-") as directory:
        path = os.path.join(directory, "linked.FCStd")
        doc.saveAs(path)
        App.closeDocument(doc.Name)
        doc = App.openDocument(path)
        doc.recompute()
        result = doc.getObject("Result")
        left = doc.getObject("Left")
        assert result.Left == left and result.Right == doc.getObject("Right")
        assert value(result, (3, 5, 0)) == -2.25
        left.Radius = 4
        doc.recompute()
        assert value(result, (3, 5, 0)) == -4.25
    # A deleted input must not leave a usable stale compiled result.
    doc.removeObject("Left")
    doc.recompute()
    assert not result.isValid(), result.State
    try:
        value(result, (0, 0, 0))
    except RuntimeError:
        pass
    else:
        raise AssertionError("deleted source left stale geometry")
    replacement = doc.addObject("Implicit::Feature", "Replacement")
    replacement.Function = "Sphere"
    replacement.Radius = 1
    result.Left = replacement
    doc.recompute()
    assert result.isValid(), result.State
    assert value(result, (0, 0, 0)) == -1.25
    # Querying malformed dependency graphs must terminate with an exception.
    result.Left = result
    try:
        value(result, (0, 0, 0))
    except RuntimeError as error:
        assert "cyclic" in str(error)
    else:
        raise AssertionError("self-link accepted")
    result.Left = replacement
    doc.recompute()
    replacement.Radius = -1
    doc.recompute()
    assert not result.isValid(), result.State
    assert result.StatusMessage
    try:
        Implicit.tessellate(result, 8)
    except RuntimeError:
        pass
    else:
        raise AssertionError("failed source left a usable mesh")
    replacement.Radius = 2
    doc.recompute()
    assert result.isValid(), result.State
    App.closeDocument(doc.Name)
    print("native implicit linked smoke test passed")


try:
    main()
except BaseException:
    traceback.print_exc()
    raise
