# SPDX-License-Identifier: LGPL-2.1-or-later
"""Native workbench commands with persistent live document dependencies."""
import json
import itertools
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


def probe_ray(feature, world_origin, world_direction, forward_only=False):
    """First sampled field hit; no display triangles or persistent subelements."""
    if feature.TypeId != "Implicit::Feature":
        raise ValueError("Select one native implicit feature")
    placement = feature.getGlobalPlacement()
    inverse = placement.inverse()
    origin = inverse.multVec(App.Vector(*world_origin))
    direction = inverse.Rotation.multVec(App.Vector(*world_direction))
    if direction.Length == 0:
        raise ValueError("Probe direction must be nonzero")
    direction.normalize()
    low, high = Implicit.bounds(feature)
    distances = [(App.Vector(*corner) - origin).dot(direction)
                 for corner in itertools.product(*zip(low, high))]
    minimum, maximum = min(distances), max(distances)
    if forward_only:
        minimum = max(0, minimum)
    if minimum > maximum:
        return None
    hits = Implicit.intersectRay(feature, tuple(origin), tuple(direction), minimum, maximum)
    if not hits:
        return None
    hit = dict(hits[0])
    hit["world_point"] = tuple(placement.multVec(App.Vector(*hit["point"])))
    return hit


def probe_view(feature, view, position):
    """Build the actual orthographic or perspective ray for a viewport pixel."""
    point = view.getPoint(*position)
    camera = view.getCameraNode()
    perspective = str(camera.getTypeId().getName()) == "PerspectiveCamera"
    if perspective:
        origin = App.Vector(*camera.position.getValue())
        direction = point - origin
    else:
        origin, direction = point, view.getViewDirection()
    return probe_ray(feature, tuple(origin), tuple(direction), perspective)


_active_probe = None
_probe_target = None


def cancel_probe():
    global _active_probe, _probe_target
    _probe_target = None
    if _active_probe is not None:
        view, handle = _active_probe
        _active_probe = None
        try:
            view.removeEventCallback("SoMouseButtonEvent", handle)
        except RuntimeError:
            pass  # The originating view may already have been closed.


class _ProbeObserver:
    def slotDeletedDocument(self, document):
        if _probe_target is not None and _probe_target[0] == document.Name:
            cancel_probe()

    def slotDeletedObject(self, obj):
        if _probe_target is not None and (obj.Document.Name, obj.Name) == _probe_target:
            cancel_probe()


_probe_observer = _ProbeObserver()
App.addDocumentObserver(_probe_observer)


def start_probe():
    """One-shot click query on the selected field; right-click cancels."""
    cancel_probe()
    selected = Gui.Selection.getSelection()
    if len(selected) != 1 or selected[0].TypeId != "Implicit::Feature":
        raise ValueError("Select one native implicit feature, then start the surface probe")
    doc_name, obj_name = selected[0].Document.Name, selected[0].Name
    if selected[0].Document != App.ActiveDocument:
        raise ValueError("The selected field must belong to the active document")
    view = Gui.activeDocument().activeView()

    def click(event):
        if event["State"] != "DOWN":
            return
        button = event["Button"]
        if button not in ("BUTTON1", "BUTTON2"):
            return
        cancel_probe()
        if button == "BUTTON2":
            return
        try:
            document = App.getDocument(doc_name)
            feature = document.getObject(obj_name)
            if feature is None:
                raise ValueError("The probed field was deleted")
            hit = probe_view(feature, view, event["Position"])
            if hit is None:
                App.Console.PrintMessage("Implicit probe: no sampled field hit\n")
            else:
                App.Console.PrintMessage("Implicit probe " + obj_name + ": " + repr(hit) + "\n")
        except Exception as error:
            App.Console.PrintError("Implicit probe: " + str(error) + "\n")

    global _active_probe, _probe_target
    _active_probe = (view, view.addEventCallback("SoMouseButtonEvent", click))
    _probe_target = (doc_name, obj_name)
    App.Console.PrintMessage("Implicit probe: left-click to query the selected field; right-click cancels.\n")


def inspect_selected():
    selected = Gui.Selection.getSelection()
    if len(selected) != 1 or selected[0].TypeId != "Implicit::Feature":
        raise ValueError("Select one native implicit feature")
    report = Implicit.inspectTessellation(selected[0])
    App.Console.PrintMessage("Implicit sampled mesh quality (resolution 24): " + repr(report) + "\n")


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
    import ImplicitNative
    import ImplicitSection
    commands = [
        ("Implicit_Sphere", "Implicit sphere", lambda: primitive("sphere")),
        ("Implicit_Gyroid", "Implicit gyroid", lambda: primitive("gyroid")),
        ("Implicit_Band", "Bounded gyroid band", lambda: primitive("band")),
        ("Implicit_BRep", "Live B-Rep field", brep_link),
        ("Implicit_Union", "Linked field union", lambda: boolean("union")),
        ("Implicit_Intersection", "Linked field intersection", lambda: boolean("intersection")),
        ("Implicit_Difference", "Linked field difference", lambda: boolean("difference")),
        ("Implicit_Probe", "Probe selected implicit surface", start_probe),
        ("Implicit_Inspect", "Inspect implicit mesh quality", inspect_selected),
        ("Implicit_OCCTGyroidSection", "OCCT gyroid-plane section (experimental)", ImplicitSection.create),
    ]
    for operation in ("Sphere", "Trim", "Common", "Fuse", "Cut"):
        commands.append(("Implicit_OCCT" + operation,
                         "OCCT sphere" + ("" if operation == "Sphere" else " " + operation.lower())
                         + " (experimental boundary)",
                         lambda op=operation: ImplicitNative.create(op)))
    try:
        import ImplicitOCCT  # noqa: F401; never loads the private extension into OCCT 7.
    except ImportError:
        pass
    else:
        import ImplicitMixed
        commands.append(("Implicit_OCCTInProcessSphere", "OCCT in-process sphere (experimental)",
                         lambda: ImplicitNative.create("Sphere", backend="InProcess")))
        commands.append(("Implicit_OCCTMixedDemo", "Native gyroid/box demo (caps/seams only)",
                         ImplicitMixed.demo))
        for operation in ("Common", "BoxMinusField"):
            commands.append(("Implicit_OCCTMixed" + operation,
                             "Native gyroid/box " + operation + " (experimental boundary)",
                             lambda op=operation: ImplicitMixed.selected(op)))
    for name, title, action in commands:
        Gui.addCommand(name, Command(title, action))
    return [name for name, _, _ in commands]
