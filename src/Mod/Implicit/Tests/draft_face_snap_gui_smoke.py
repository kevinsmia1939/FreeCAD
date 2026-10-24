# SPDX-License-Identifier: LGPL-2.1-or-later
"""Actual Draft surface picks project to native fields and bounded cap faces."""
import math
import os
import time
import traceback
import FreeCAD as App
import FreeCADGui as Gui
import ImplicitMixed
import ImplicitSolid
import ImplicitOCCT as native
import Part
from PySide import QtCore


def until(predicate, seconds=90):
    deadline = time.monotonic() + seconds
    while not predicate():
        assert time.monotonic() < deadline, "Face snap GUI condition timed out"
        loop = QtCore.QEventLoop()
        QtCore.QTimer.singleShot(20, loop.quit)
        loop.exec()


def value(point):
    x, y, z = (2 * math.pi * coordinate / 10 for coordinate in point)
    return math.sin(x) * math.cos(y) + math.sin(y) * math.cos(z) + math.sin(z) * math.cos(x)


def main():
    import lazy_loader.lazy_loader
    import SketcherGui
    import TechDrawGui
    Gui.activateWorkbench("ImplicitModelingWorkbench")
    doc = App.newDocument("DraftFaceSnaps")
    field = doc.addObject("Implicit::Feature", "Gyroid")
    field.Function, field.Period = "Gyroid", 10
    field.DomainMin, field.DomainMax = (0, 0, 0), (10, 10, 10)
    box = doc.addObject("Part::Box", "Box")
    box.Length = box.Width = box.Height = 10
    doc.recompute()
    source = ImplicitMixed.create(field, box, corner_policy="Regularized")
    solid = ImplicitSolid.create(source)
    for obj in doc.Objects:
        obj.ViewObject.Visibility = obj is solid
    until(lambda: not solid.ViewObject.Proxy._display_pending)
    Gui.activateWorkbench("DraftWorkbench")
    snapper = Gui.Snapper
    snapper.active_snaps = ["Lock", "Near"]
    view = Gui.activeDocument().activeView()
    view.viewAxonometric(); view.fitAll(); Gui.updateGui()
    mesh = solid.ViewObject.Proxy._mesh
    triangles = mesh["implicit_triangles"]
    original = Part.getShape
    def forbidden(*args, **kwargs):
        raise AssertionError("Draft used Part conversion for native face snapping")
    Part.getShape = forbidden
    try:
        found = False
        for triangle in triangles[::max(1, len(triangles) // 300)]:
            center = sum((App.Vector(*mesh["vertices"][i]) for i in triangle), App.Vector()) / 3
            pixel = tuple(int(v) for v in view.getPointOnScreen(center))
            for hit, info in enumerate(view.getObjectsInfo(pixel) or []):
                if info.get("Object") != solid.Name or not info.get("Component", "").startswith("NativeFace"):
                    continue
                cursor = App.Vector(info["x"], info["y"], info["z"])
                if min(cursor) < .2 or max(cursor) > 9.8 or abs(value(cursor)) < 1e-5:
                    continue
                snapper.snapObjectIndex = hit
                candidate = snapper.snap(pixel, active=True, noTracker=True)
                if snapper.cursorMode != "passive":
                    continue
                assert abs(value(candidate)) < 1e-5, (cursor, candidate, value(candidate))
                assert (candidate - cursor).Length > 1e-7
                assert (candidate - cursor).Length < .4
                found = True
                break
            if found:
                break
        assert found, "No projected mathematical-face viewport snap"
        caps = native.inspect_mixed(source.Geometry)["planar_caps"]
        found = False
        for cap in caps:
            vertices, cells = cap.tessellate(.1)
            for triangle in cells[::max(1, len(cells) // 20)]:
                center = sum((vertices[i] for i in triangle), App.Vector()) / 3
                pixel = tuple(int(v) for v in view.getPointOnScreen(center))
                for hit, info in enumerate(view.getObjectsInfo(pixel) or []):
                    component = info.get("Component", "")
                    if info.get("Object") != solid.Name or not component.startswith("Cap"):
                        continue
                    snapper.snapObjectIndex = hit
                    candidate = snapper.snap(pixel, active=True, noTracker=True)
                    assert snapper.cursorMode == "passive"
                    reference = caps[int(component[3:]) - 1]
                    assert Part.Vertex(candidate).distToShape(reference)[0] < 1e-7
                    found = True
                    break
                if found: break
            if found: break
        assert found, "No bounded-cap viewport snap"
    finally:
        Part.getShape = original
    assert solid.SolidValidated and "Shape" not in solid.PropertiesList
    App.closeDocument(doc.Name)
    print("native implicit Draft face snapping GUI smoke test passed", flush=True)


try:
    main()
except BaseException:
    traceback.print_exc()
    os._exit(1)
finally:
    Gui.getMainWindow().close()
