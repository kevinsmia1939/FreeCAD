# SPDX-License-Identifier: LGPL-2.1-or-later
"""Native workbench commands with persistent live document dependencies."""
import json
import FreeCAD as App
import FreeCADGui as Gui
import Implicit


def create(root, name="Field", domain=None, placement=None, resolution=24, function=None):
    document = App.ActiveDocument or App.newDocument()
    document.openTransaction("Create native implicit field")
    try:
        feature = document.addObject("Implicit::Feature", name)
        feature.ViewObject.Resolution = resolution
        if domain is not None:
            feature.DomainMin, feature.DomainMax = tuple(domain[0]), tuple(domain[1])
        if placement is not None:
            feature.Placement = placement
        if function is not None:
            feature.Function = function
            if function == "Sphere":
                feature.Radius = 5
        else:
            Implicit.setFieldGraph(feature, json.dumps({"schema": 1, "root": root}))
        document.recompute()
        if not feature.isValid():
            raise RuntimeError("Native implicit feature failed to recompute")
        document.commitTransaction()
        return feature
    except BaseException:
        document.abortTransaction()
        raise


def primitive(kind):
    if kind == "sphere":
        return create(None, "SphereField", function="Sphere")
    gyroid = {"type": "gyroid", "period": 10, "iso": 0.0}
    if kind == "gyroid":
        return create(None, "GyroidField", function="Gyroid")
    return create({"type": "intersection",
        "left": {"type": "band", "field": gyroid, "halfWidth": 0.3},
        "right": {"type": "box", "center": [0, 0, 0], "halfSize": [8, 8, 8]}},
        "BoundedGyroidBand")


def boolean(operation):
    selection = Gui.Selection.getSelection()
    if len(selection) != 2 or any(
            obj.TypeId != "Implicit::Feature" and not obj.isDerivedFrom("Part::Feature")
            for obj in selection):
        raise ValueError("Select two native implicit features or single-solid Part features")
    left, right = selection
    document = left.Document
    if right.Document != document:
        raise ValueError("Operands must belong to the same document")
    document.openTransaction("Create linked implicit " + operation)
    try:
        feature = document.addObject("Implicit::Feature", "Field" + operation.title())
        feature.Operation = operation.title()
        feature.Tolerance = 1e-7
        feature.Left, feature.Right = left, right
        document.recompute()
        if not feature.isValid():
            raise RuntimeError("Linked field operation failed")
        document.commitTransaction()
        return feature
    except BaseException:
        document.abortTransaction()
        raise


def brep_link():
    selection = Gui.Selection.getSelection()
    if len(selection) != 1 or not hasattr(selection[0], "Shape"):
        raise ValueError("Select one B-Rep object containing a single solid")
    solids = selection[0].Shape.Solids
    if len(solids) != 1 or selection[0].Shape.ShapeType != "Solid":
        raise ValueError("B-Rep field requires a single solid, not a compound")
    source = selection[0]
    shape = source.Shape.copy()
    shape.Placement = App.Placement()
    bounds = shape.BoundBox
    margin = max(bounds.DiagonalLength * 0.05, 1.0)
    domain = ((bounds.XMin - margin, bounds.YMin - margin, bounds.ZMin - margin),
              (bounds.XMax + margin, bounds.YMax + margin, bounds.ZMax + margin))
    document = source.Document
    document.openTransaction("Create linked B-Rep field")
    try:
        feature = document.addObject("Implicit::Feature", "BRepField")
        feature.Operation = "BRep"
        feature.Left = source
        feature.Tolerance = 1e-7
        # Source global placement is already included by the native evaluator.
        feature.DomainMin, feature.DomainMax = domain
        feature.ViewObject.Resolution = 8
        document.recompute()
        if not feature.isValid():
            raise RuntimeError("Live B-Rep field failed to recompute")
        document.commitTransaction()
        return feature
    except BaseException:
        document.abortTransaction()
        raise


class Command:
    def __init__(self, title, action):
        self.title, self.action = title, action

    def GetResources(self):
        return {"MenuText": self.title, "ToolTip": self.title, "Pixmap": ""}

    def IsActive(self):
        return True

    def Activated(self):
        try:
            self.action()
        except Exception as error:
            App.Console.PrintError(str(error) + "\n")


def register():
    commands = [
        ("Implicit_Sphere", "Implicit sphere", lambda: primitive("sphere")),
        ("Implicit_Gyroid", "Implicit gyroid", lambda: primitive("gyroid")),
        ("Implicit_Band", "Bounded gyroid band", lambda: primitive("band")),
        ("Implicit_BRep", "Live B-Rep field", brep_link),
        ("Implicit_Union", "Linked field union", lambda: boolean("union")),
        ("Implicit_Intersection", "Linked field intersection", lambda: boolean("intersection")),
        ("Implicit_Difference", "Linked field difference", lambda: boolean("difference")),
    ]
    for name, title, action in commands:
        Gui.addCommand(name, Command(title, action))
    return [name for name, _, _ in commands]
