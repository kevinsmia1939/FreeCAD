# SPDX-License-Identifier: LGPL-2.1-or-later
"""Draft's actual snapper and Line command consume native semantic picks."""
import os
import time
import tempfile
import traceback
import FreeCAD as App
import FreeCADGui as Gui
import Implicit
import ImplicitMixed
import ImplicitSolid
import Part
from PySide import QtCore


def until(predicate, seconds=90):
    deadline = time.monotonic() + seconds
    while not predicate():
        assert time.monotonic() < deadline, "Draft snap condition timed out"
        loop = QtCore.QEventLoop()
        QtCore.QTimer.singleShot(20, loop.quit)
        loop.exec()


def pixel_for(view, obj, kind):
    geometry = Implicit.nativeGeometry(obj)
    for index in range(1, geometry.countSubElements(kind) + 1):
        name = kind + str(index)
        selected = obj.getSubObject(name)
        points, lines = selected.getLines(.1)
        point = points[0] if kind == "Vertex" else (points[lines[0][0]] + points[lines[0][1]]) * .5
        x, y = view.getPointOnScreen(point)
        for dx, dy in ((0, 0), (1, 0), (-1, 0), (0, 1), (0, -1)):
            pixel = (int(x) + dx, int(y) + dy)
            infos = view.getObjectsInfo(pixel) or []
            for hit, info in enumerate(infos):
                if info.get("Object") == obj.Name and info.get("Component") == name:
                    return pixel, hit, info, selected
    raise AssertionError("No actual native " + kind + " viewport pick")


def main():
    import lazy_loader.lazy_loader  # Fail before workbench activation can show a modal error.
    import SketcherGui
    import TechDrawGui
    Gui.activateWorkbench("ImplicitModelingWorkbench")
    source = ImplicitMixed.demo(open_contours=True)
    doc = source.Document
    doc.UndoMode = 1
    solid = ImplicitSolid.create(source)
    for obj in doc.Objects:
        obj.ViewObject.Visibility = obj == solid
    solid.ViewObject.ShowImplicitSurface = False
    Gui.activateWorkbench("DraftWorkbench")
    assert Gui.activeWorkbench().name() == "DraftWorkbench"
    assert "Draft_Line" in Gui.listCommands() and hasattr(Gui, "Snapper")
    from draftguitools import gui_lines, gui_tool_utils
    from draftutils import params
    import WorkingPlane
    view = Gui.activeDocument().activeView()
    view.viewAxonometric(); view.fitAll(); Gui.updateGui()
    snapper = Gui.Snapper
    snapper.active_snaps = ["Lock", "Endpoint"]
    pixel, hit, info, vertex = pixel_for(view, solid, "Vertex")
    expected = vertex.getPoints(.1)[0][0]
    original_get_shape = Part.getShape
    def forbidden(*args, **kwargs):
        raise AssertionError("Draft sent native implicit geometry through Part.getShape")
    Part.getShape = forbidden
    try:
        snapper.snapObjectIndex = hit
        actual = snapper.snap(pixel, active=True, noTracker=True)
        assert (actual - expected).Length < 1e-10
        assert snapper.cursorMode == "endpoint"
        edge_pixel, edge_hit, edge_info, edge = pixel_for(view, solid, "Edge")
        snapper.active_snaps = ["Lock", "Midpoint"]
        snapper.snapObjectIndex = edge_hit
        midpoint = snapper.snap(edge_pixel, active=True, noTracker=True)
        expected_midpoint = App.Vector(*Implicit.snapNative(edge, "Midpoint", (0, 0, 0))[0])
        assert (midpoint - expected_midpoint).Length < 1e-10
        assert snapper.cursorMode == "midpoint"
        snapper.active_snaps = ["Lock", "Near"]
        snapper.snapObjectIndex = edge_hit
        near = snapper.snap(edge_pixel, active=True, noTracker=True)
        expected_near = App.Vector(*Implicit.snapNative(edge, "Near",
            (edge_info["x"], edge_info["y"], edge_info["z"]))[0])
        assert (near - expected_near).Length < 1e-10
        assert snapper.cursorMode == "passive"
        # Unsupported surface/center snapping stays empty. No display-triangle
        # endpoint or UV-based working-plane alignment is fabricated.
        snapper.active_snaps = ["Lock", "Endpoint", "Midpoint", "Near", "Center"]
        assert snapper.snapToNative(solid, "NativeFace1", App.Vector()) == []
        empty = doc.addObject("Implicit::NativeFeature", "Unavailable")
        assert snapper.snapToNative(empty, "Vertex1", App.Vector()) == []
        doc.removeObject(empty.Name)
        Gui.Selection.clearSelection(); Gui.Selection.addSelection(solid, "Vertex1")
        assert gui_tool_utils.set_working_plane_to_selected_object() is None
        Gui.Selection.clearSelection()
        # Working-plane projection stays Draft's existing optional behavior.
        snapper.active_snaps = ["Lock", "Endpoint", "WorkingPlane"]
        selected = solid.getSubObject("Vertex1")
        p = selected.getPoints(.1)[0][0]
        candidates = snapper.snapToNative(solid, "Vertex1", p)
        assert candidates and candidates[0][0] == p
        assert candidates[0][2] == snapper.toWP(p)
    finally:
        Part.getShape = original_get_shape

    # The registered Draft line command consumes two native snapped endpoints.
    params.set_param("UsePartPrimitives", False)
    command = gui_lines.Line()
    command.Activated()
    Gui.draftToolBar.continueMode = False
    snapper.active_snaps = ["Lock", "Endpoint"]
    first = None
    for index in range(1, Implicit.nativeGeometry(solid).countSubElements("Vertex") + 1):
        name = "Vertex" + str(index)
        target = solid.getSubObject(name).getPoints(.1)[0][0]
        if first is not None and (target - first).Length < 1:
            continue
        x, y = view.getPointOnScreen(target)
        pixel = (int(x), int(y))
        infos = view.getObjectsInfo(pixel) or []
        match = next((i for i, info in enumerate(infos)
                      if info.get("Object") == solid.Name and info.get("Component") == name), None)
        if match is None:
            continue
        snapper.snapObjectIndex = match
        event = {"Position": pixel, "CtrlDown": True, "ShiftDown": False, "AltDown": False}
        command.action(dict(event, Type="SoLocation2Event"))
        assert (command.point - target).Length < 1e-10
        command.action(dict(event, Type="SoMouseButtonEvent", State="DOWN", Button="BUTTON1"))
        if first is None:
            first = target
        else:
            last = target
            break
    else:
        raise AssertionError("Could not complete Draft Line with native viewport endpoints")
    until(lambda: any(hasattr(obj, "Points") and len(obj.Points) == 2 for obj in doc.Objects))
    line = next(obj for obj in doc.Objects if hasattr(obj, "Points") and len(obj.Points) == 2)
    doc.recompute()
    endpoints = [vertex.Point for vertex in line.Shape.Vertexes]
    assert all(min((p - expected).Length for p in endpoints) < 1e-9 for expected in (first, last))
    assert "Shape" not in solid.PropertiesList
    old_geometry = Implicit.nativeGeometry(solid)
    old_name = ";" + old_geometry.getElementName("Vertex1", 1) + ".Vertex1"
    source.Operation = "BoxMinusField"
    doc.recompute()
    assert solid.SolidValidated
    assert snapper.snapToNative(solid, old_name, first) == []
    # Ordinary Part vertex snapping still goes through the existing dispatcher.
    box = doc.addObject("Part::Box", "Conventional")
    doc.recompute()
    snapper.snapInfo = {"Object": box.Name, "Component": "Vertex1", "x": 0., "y": 0., "z": 0.}
    ordinary = snapper.snapToObject(None, True, False, None, App.Vector())
    assert (ordinary - box.Shape.Vertexes[0].Point).Length < 1e-10
    with tempfile.TemporaryDirectory(prefix="implicit-draft-snap-") as directory:
        filename = os.path.join(directory, "draft.FCStd")
        line_name = line.Name
        doc.saveAs(filename)
        App.closeDocument(doc.Name)
        doc = App.openDocument(filename)
        doc.recompute()
        assert doc.getObject(line_name).Shape.isValid()
    App.closeDocument(doc.Name)
    print("native implicit Draft snapping GUI smoke test passed", flush=True)


try:
    main()
except BaseException:
    traceback.print_exc()
    os._exit(1)
finally:
    Gui.getMainWindow().close()
