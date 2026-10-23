# SPDX-License-Identifier: LGPL-2.1-or-later
"""Actual solid component rendering/picking, live edits and FCStd restoration."""
import os
import tempfile
import traceback
import time
from PySide import QtCore
import FreeCAD as App
import FreeCADGui as Gui
import Implicit
import ImplicitSolid
import ImplicitOCCT as native
import Part
from pivy import coin


def pixel_pick(obj, point):
    camera = coin.SoOrthographicCamera()
    camera.position = tuple(point + App.Vector(1, 2, 3).normalize() * 5)
    camera.pointAt(coin.SbVec3f(*point), coin.SbVec3f(0, 1, 0))
    camera.height = 2
    camera.nearDistance, camera.farDistance = .1, 10
    scene = coin.SoSeparator()
    scene.addChild(camera)
    scene.addChild(obj.ViewObject.RootNode)
    action = coin.SoRayPickAction(coin.SbViewportRegion(512, 512))
    action.setPickAll(True)
    action.setPoint(coin.SbVec2s(256, 256))
    action.apply(scene)
    return [obj.ViewObject.getElementPicked(hit) for hit in action.getPickedPointList()]


def wait_display(obj):
    deadline = time.monotonic() + 90
    while obj.ViewObject.Proxy._display_pending:
        assert time.monotonic() < deadline, obj.ViewObject.SurfacePreviewStatus
        loop = QtCore.QEventLoop()
        QtCore.QTimer.singleShot(20, loop.quit)
        loop.exec()


def check(obj):
    wait_display(obj)
    view = obj.ViewObject.Proxy
    assert view._mesh, obj.ViewObject.SurfacePreviewStatus
    report = obj.Proxy._solid
    groups = ImplicitSolid.component_triangles(view._mesh, report["component_domains"])
    assert len(groups) == obj.NativeFaceCount
    for index, triangles in enumerate(groups, 1):
        name = "NativeFace" + str(index)
        node = view._elements[name]
        assert node.coordIndex.getNum() == 4 * len(triangles)
        triangle = triangles[len(triangles) // 2]
        p, q, r = (App.Vector(*view._mesh["vertices"][i]) for i in triangle)
        center, normal = (p + q + r) / 3, (q - p).cross(r - p).normalize()
        pose = obj.getGlobalPlacement()
        center, normal = pose.multVec(center), pose.Rotation.multVec(normal)
        action = coin.SoRayPickAction(coin.SbViewportRegion(512, 512))
        action.setPickAll(True)
        action.setRay(coin.SbVec3f(*(center + normal * .01)), coin.SbVec3f(*(-normal)), 0., .02)
        action.apply(obj.ViewObject.RootNode)
        names = [obj.ViewObject.getElementPicked(hit) for hit in action.getPickedPointList()]
        assert name in names, (name, names)
    geometry = Implicit.nativeGeometry(obj)
    for kind in ("Edge", "Vertex"):
        points, lines = geometry.getLinesFromSubElement(kind, 1)
        point = points[0] if kind == "Vertex" else (points[lines[0][0]] + points[lines[0][1]]) * .5
        names = pixel_pick(obj, obj.getGlobalPlacement().multVec(point))
        assert kind + "1" in names, names
    for kind in ("Solid", "Shell", "Face", "NativeFace", "Cap", "Seam", "Edge", "Vertex"):
        for index in range(1, geometry.countSubElements(kind) + 1):
            name = kind + str(index)
            node = view._elements[name]
            mapped = ";" + geometry.getElementName(name, 1) + "." + name
            path = coin.SoPath()
            obj.ViewObject.getDetailPath(mapped, path)
            assert path.getLength() and path.getTail() == node, name
    for name in ("Solid1", "Shell1", "NativeFace1", "Edge1", "Vertex1"):
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(obj, name)
        selection = Gui.Selection.getSelectionEx()
        assert selection and selection[0].SubElementNames == (name,)
        assert len(selection[0].SubObjects) == 1
    return view._mesh


def main():
    Gui.activateWorkbench("ImplicitModelingWorkbench")
    assert "Implicit_NativeSolid" in Gui.listCommands()
    Gui.runCommand("Implicit_NativeSolidDemo")
    obj = App.ActiveDocument.Objects[-1]
    doc = obj.Document
    mesh = check(obj)
    Gui.Selection.clearSelection()
    Gui.activeDocument().activeView().viewAxonometric()
    Gui.updateGui()
    Gui.activeDocument().activeView().fitAll()
    Gui.updateGui()
    Gui.activeDocument().activeView().saveImage("/tmp/implicit-live-solid-demo.png", 1000, 700, "Current")
    build, tessellate = native.build_mixed_solids, native.tessellate_mixed
    def forbidden(*_args):
        raise AssertionError("unchanged view/restore rebuilt numerical solids or mesh")
    native.build_mixed_solids = native.tessellate_mixed = forbidden
    try:
        Gui.activeDocument().activeView().viewFront()
        Gui.updateGui()
        obj.ViewObject.ShowVertices = False
        assert "Vertex1" not in obj.ViewObject.Proxy._elements
        obj.ViewObject.ShowVertices = True
        assert obj.ViewObject.Proxy._mesh is mesh
        obj.ViewObject.ShowBoundaryEdges = False
        assert "Edge1" not in obj.ViewObject.Proxy._elements
        obj.ViewObject.ShowBoundaryEdges = True
        obj.ViewObject.ShowImplicitSurface = False
        assert "NativeFace1" not in obj.ViewObject.Proxy._elements
        obj.ViewObject.ShowImplicitSurface = True
        assert obj.ViewObject.Proxy._mesh is mesh
        check(obj)
    finally:
        native.build_mixed_solids, native.tessellate_mixed = build, tessellate
    obj.ViewObject.SurfaceMaximumCells = 7
    wait_display(obj)
    assert obj.ViewObject.Proxy._mesh is None
    assert "NativeFace1" not in obj.ViewObject.Proxy._elements
    assert "failed" in obj.ViewObject.SurfacePreviewStatus
    assert obj.Geometry is not None and obj.SolidValidated
    obj.ViewObject.SurfaceMaximumCells = 256
    check(obj)
    obj.FollowSourcePlacement = False
    obj.Placement = App.Placement(App.Vector(2, -3, 4), App.Rotation(13, 21, 9))
    doc.recompute()
    check(obj)
    instance = doc.addObject("App::Link", "SolidInstance")
    instance.LinkedObject = obj
    instance.LinkTransform = True
    instance.LinkPlacement = App.Placement(App.Vector(-4, 7, 5), App.Rotation(37, 11, 0))
    doc.recompute()
    Gui.updateGui()
    geometry = Implicit.nativeGeometry(obj)
    vertex = geometry.getLinesFromSubElement("Vertex", 1)[0][0]
    pose = instance.LinkPlacement.multiply(obj.Placement)
    assert "Vertex1" in pixel_pick(instance, pose.multVec(vertex))
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(instance, "Vertex1")
    point = Gui.Selection.getSelectionEx()[0].SubObjects[0].getPoints(.1)[0][0]
    assert (point - pose.multVec(vertex)).Length < 1e-10
    unrelated = obj.Source.Box
    Gui.Selection.addSelection(unrelated)
    obj.Source.Operation = "BoxMinusField"
    doc.recompute()
    assert [entry.Object for entry in Gui.Selection.getSelectionEx()] == [unrelated]
    check(obj)
    with tempfile.TemporaryDirectory(prefix="implicit-live-solid-gui-") as directory:
        filename, name = os.path.join(directory, "solid.FCStd"), obj.Name
        doc.saveAs(filename)
        App.closeDocument(doc.Name)
        native.build_mixed_solids = forbidden
        try:
            doc = App.openDocument(filename)
            Gui.updateGui()
            obj = doc.getObject(name)
            assert not obj.SolidValidated and obj.Geometry is not None
            check(obj)
        finally:
            native.build_mixed_solids = build
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(obj.Source)
    count = len(doc.Objects)
    Gui.runCommand("Implicit_NativeSolid")
    assert Gui.Control.activeDialog() and len(doc.Objects) == count
    # Creation now stages settings; cancelling must not add a result.
    from PySide import QtWidgets
    buttons = [box for box in Gui.getMainWindow().findChildren(QtWidgets.QDialogButtonBox)
               if box.isVisible() and box.button(QtWidgets.QDialogButtonBox.Cancel) is not None]
    assert len(buttons) == 1
    buttons[0].button(QtWidgets.QDialogButtonBox.Cancel).click()
    assert not Gui.Control.activeDialog() and len(doc.Objects) == count
    # Exercise the actual two-component result, not one aggregate source face.
    App.closeDocument(doc.Name)
    doc = App.newDocument("SolidComponentsGUI")
    source = doc.addObject("Implicit::NativeFeaturePython", "Source")
    field = native.gyroid(10, 1.45, (-5, -5, -5), (16, 16, 6))
    source.Geometry = native.mixed_box(field,
        Part.makeBox(13.24, 3.28, 2.75, App.Vector(-.31, -.37, 1.25)),
        "common")["boundary_handle"]
    obj = ImplicitSolid.create(source, topology_resolution=64)
    assert obj.NativeFaceCount == 2
    check(obj)
    screenshot = "/tmp/implicit-live-solid-components.png"
    Gui.activeDocument().activeView().viewAxonometric()
    Gui.activeDocument().activeView().fitAll()
    Gui.updateGui()
    Gui.activeDocument().activeView().saveImage(screenshot, 1000, 700, "Current")
    original_source = source.Geometry
    full_field = native.gyroid(10, 2, (-5, -5, -5), (16, 16, 6))
    for operation in ("common", "box_minus_field"):
        source.Geometry = native.mixed_box(full_field,
            Part.makeBox(3, 3, 3, App.Vector(-.31, -.37, 1.25)), operation)["boundary_handle"]
        obj.TopologyResolution = 4
        doc.recompute()
        assert obj.SolidValidated and obj.NativeFaceCount == 0
        assert obj.ViewObject.Proxy._mesh is None
        assert "NativeFace1" not in obj.ViewObject.Proxy._elements
        assert ("Solid1" in obj.ViewObject.Proxy._elements) is (operation == "common")
        if operation == "box_minus_field":
            assert not obj.ViewObject.Proxy._elements
    source.Geometry = original_source
    obj.TopologyResolution = 64
    doc.recompute()
    check(obj)
    # Clear geometry through a handled failed recompute, leaving no stale nodes.
    obj.MaximumGeometryCells = 1
    try:
        obj.Proxy.execute(obj)
    except ValueError:
        pass
    else:
        raise AssertionError("geometry budget unexpectedly succeeded")
    assert obj.Geometry is None and not obj.ViewObject.Proxy._elements
    assert obj.ViewObject.Proxy._mesh is None
    App.closeDocument(doc.Name)
    print("native implicit live solid GUI smoke test passed", flush=True)


try:
    main()
except BaseException:
    traceback.print_exc()
    # Fail immediately instead of opening a modal save prompt for the temporary
    # dirty document when the final main-window close follows an assertion.
    os._exit(1)
finally:
    Gui.getMainWindow().close()
