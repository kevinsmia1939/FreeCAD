# SPDX-License-Identifier: LGPL-2.1-or-later
"""Native workbench commands. Boolean results and B-Reps are snapshots."""
import json
import FreeCAD as App
import FreeCADGui as Gui
import Implicit


def create(root, name="Field", domain=None, placement=None, resolution=24):
    document = App.ActiveDocument or App.newDocument()
    document.openTransaction("Create native implicit field")
    try:
        feature = document.addObject("Implicit::Feature", name)
        feature.ViewObject.Resolution = resolution
        if domain is not None:
            feature.DomainMin, feature.DomainMax = domain
        if placement is not None:
            feature.Placement = placement
        Implicit.setFieldGraph(feature, json.dumps({"schema": 1, "root": root}))
        document.recompute()
        if "Error" in feature.State:
            raise RuntimeError("Native implicit feature failed to recompute")
        document.commitTransaction()
        return feature
    except BaseException:
        document.abortTransaction()
        raise


def graph(feature):
    if feature.FieldGraph:
        return json.loads(feature.FieldGraph)["root"]
    if feature.Function == "Sphere":
        return {"type": "sphere", "center": list(feature.Center), "radius": feature.Radius.Value}
    return {"type": "gyroid", "period": feature.Period.Value, "iso": feature.IsoValue}


def primitive(kind):
    if kind == "sphere":
        return create({"type": "sphere", "center": [0, 0, 0], "radius": 5}, "SphereField")
    gyroid = {"type": "gyroid", "period": 10, "iso": 0.0}
    if kind == "gyroid":
        return create(gyroid, "GyroidField")
    return create({"type": "intersection",
        "left": {"type": "band", "field": gyroid, "halfWidth": 0.3},
        "right": {"type": "box", "center": [0, 0, 0], "halfSize": [8, 8, 8]}},
        "BoundedGyroidBand")


def boolean(operation):
    selection = Gui.Selection.getSelection()
    if len(selection) != 2 or any(obj.TypeId != "Implicit::Feature" for obj in selection):
        raise ValueError("Select two native implicit features")
    left, right = selection
    if any(abs(a - b) > 1e-10 for a, b in zip(left.Placement.toMatrix().A, right.Placement.toMatrix().A)):
        raise ValueError("Boolean snapshots currently require matching feature placements")
    if operation == "union":
        minimum = [min(a, b) for a, b in zip(left.DomainMin, right.DomainMin)]
        maximum = [max(a, b) for a, b in zip(left.DomainMax, right.DomainMax)]
    else:
        minimum, maximum = left.DomainMin, left.DomainMax
    if not left.InsideNegative or not right.InsideNegative:
        raise ValueError("Boolean snapshots currently require negative-inside operands")
    return create({"type": operation, "left": graph(left), "right": graph(right)},
        "Field" + operation.title(), (minimum, maximum), left.Placement)


def brep_snapshot():
    selection = Gui.Selection.getSelection()
    if len(selection) != 1 or not hasattr(selection[0], "Shape"):
        raise ValueError("Select one B-Rep object containing a single solid")
    solids = selection[0].Shape.Solids
    if len(solids) != 1:
        raise ValueError("B-Rep snapshot requires exactly one solid")
    shape = solids[0]
    bounds = shape.BoundBox
    margin = max(bounds.DiagonalLength * 0.05, 1.0)
    domain = ([bounds.XMin - margin, bounds.YMin - margin, bounds.ZMin - margin],
              [bounds.XMax + margin, bounds.YMax + margin, bounds.ZMax + margin])
    feature = create({"type": "brep", "data": shape.exportBrepToString(), "tolerance": 1e-7},
        "BRepFieldSnapshot", domain, resolution=8)
    feature.addProperty("App::PropertyString", "SourceLabel", "Provenance")
    feature.SourceLabel = selection[0].Label
    feature.setEditorMode("SourceLabel", 1)
    return feature


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
        ("Implicit_BRep", "B-Rep field snapshot", brep_snapshot),
        ("Implicit_Union", "Field union snapshot", lambda: boolean("union")),
        ("Implicit_Intersection", "Field intersection snapshot", lambda: boolean("intersection")),
        ("Implicit_Difference", "Field difference snapshot", lambda: boolean("difference")),
    ]
    for name, title, action in commands:
        Gui.addCommand(name, Command(title, action))
    return [name for name, _, _ in commands]
