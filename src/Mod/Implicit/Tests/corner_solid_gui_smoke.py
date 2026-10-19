# SPDX-License-Identifier: LGPL-2.1-or-later
"""Opt-in corner-aware live solid rendering/picking, no default command change."""
import os
import tempfile
import traceback
import FreeCAD as App
import FreeCADGui as Gui
import ImplicitMixed
import ImplicitSolid
import ImplicitOCCT as native
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


def check(obj):
    Gui.updateGui()
    view = obj.ViewObject.Proxy
    mesh = view._mesh
    assert mesh, obj.ViewObject.SurfacePreviewStatus
    assert mesh["corner_policy"] == "regularized" and mesh["fixed_corner_count"] == 8
    assert mesh["mesh_closed"] and not mesh["surface_coverage_verified"]
    assert "NOT validated" in obj.ViewObject.SurfacePreviewStatus
    assert view._elements["NativeFace1"].coordIndex.getNum() > 0
    triangle = mesh["implicit_triangles"][len(mesh["implicit_triangles"]) // 2]
    points = [App.Vector(*mesh["vertices"][i]) for i in triangle]
    assert "NativeFace1" in pixel_pick(obj, sum(points, App.Vector()) / 3)
    geometry = view._geometry
    vertices, _ = geometry.getLinesFromSubElement("Vertex", 1)
    assert "Vertex1" in pixel_pick(obj, vertices[0])
    for name in ("Solid1", "Shell1", "NativeFace1", "Edge1", "Vertex1"):
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(obj, name)
        selected = Gui.Selection.getSelectionEx()
        assert selected and selected[0].SubElementNames == (name,)
        assert len(selected[0].SubObjects) == 1


def main():
    Gui.activateWorkbench("ImplicitModelingWorkbench")
    doc = App.newDocument("CornerSolidGUI")
    doc.UndoMode = 1
    field = doc.addObject("Implicit::Feature", "Gyroid")
    field.Function, field.Period, field.IsoValue = "Gyroid", 10, 0
    field.DomainMin, field.DomainMax = (0, 0, 0), (10, 10, 10)
    box = doc.addObject("Part::Box", "Box")
    box.Length = box.Width = box.Height = 10
    doc.recompute()
    source = ImplicitMixed.create(field, box, corner_policy="Regularized")
    obj = ImplicitSolid.create(source)
    field.ViewObject.Visibility = box.ViewObject.Visibility = source.ViewObject.Visibility = False
    check(obj)
    Gui.activeDocument().activeView().viewAxonometric()
    Gui.activeDocument().activeView().fitAll()
    Gui.updateGui()
    Gui.activeDocument().activeView().saveImage("/tmp/implicit-corner-native-solid.png", 1000, 700, "Current")
    doc.openTransaction("Complement")
    source.Operation = "BoxMinusField"
    doc.recompute()
    doc.commitTransaction()
    assert obj.Proxy._solid["solid_validated"]
    check(obj)
    doc.undo(); doc.recompute(); check(obj)
    doc.redo(); doc.recompute(); check(obj)
    Gui.Selection.clearSelection()
    record = native.dumps_mixed_solids(obj.Geometry)
    obj_name, source_name = obj.Name, source.Name
    with tempfile.TemporaryDirectory(prefix="implicit-corner-gui-") as directory:
        path = os.path.join(directory, "solid.FCStd")
        doc.saveAs(path)
        build = native.build_mixed_solids
        def forbidden(*_args):
            raise AssertionError("Unchanged GUI restore attempted native solid reconstruction")
        native.build_mixed_solids = forbidden
        try:
            App.closeDocument(doc.Name)
            doc = App.openDocument(path)
            doc.recompute()
            obj = doc.getObject(obj_name)
            assert str(doc.getObject(source_name).CornerPolicy) == "Regularized"
            assert native.dumps_mixed_solids(obj.Geometry) == record
            assert not obj.Proxy._solid["solid_validated"]
            check(obj)
        finally:
            native.build_mixed_solids = build
        App.closeDocument(doc.Name)
    print("native implicit corner solid GUI smoke test passed", flush=True)


try:
    main()
except BaseException:
    traceback.print_exc()
    os._exit(1)
finally:
    Gui.getMainWindow().close()
