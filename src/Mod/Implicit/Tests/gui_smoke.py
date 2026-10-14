# SPDX-License-Identifier: LGPL-2.1-or-later
"""Run with the fork GUI, optionally under Xvfb. Exits nonzero on failure."""
import json
import itertools
import os
import tempfile
import traceback

import FreeCAD as App
import FreeCADGui as Gui
import Implicit
import ImplicitGui  # noqa: F401
from pivy import coin


def named(root, name):
    search = coin.SoSearchAction()
    search.setName(coin.SbName(name))
    search.setInterest(coin.SoSearchAction.FIRST)
    search.setSearchingAll(True)
    search.apply(root)
    path = search.getPath()
    assert path is not None, "missing node: " + name
    return path.getTail()


def main():
    document = App.newDocument("ImplicitNativeGuiSmoke")
    document.UndoMode = 1
    Gui.activateWorkbench("NativeImplicitWorkbench")
    baseline = len(document.Objects)
    Gui.runCommand("Implicit_Sphere")
    assert len(document.Objects) == baseline + 1, "workbench sphere command failed"
    document.undo()
    assert len(document.Objects) == baseline, "workbench command was not undoable"
    feature = document.addObject("Implicit::Feature", "NativeField")
    view = feature.ViewObject
    assert view.TypeId == "ImplicitGui::ViewProviderShape", view.TypeId
    graph = {"schema": 1, "root": {"type": "difference",
        "left": {"type": "sphere", "center": [0, 0, 0], "radius": 4},
        "right": {"type": "sphere", "center": [2, 0, 0], "radius": 3}}}
    view.Resolution = 12
    Implicit.setFieldGraph(feature, json.dumps(graph))
    document.recompute()
    Gui.updateGui()
    assert view.TriangleCount > 0
    coordinates = named(view.RootNode, "ImplicitCoordinates")
    faces = named(view.RootNode, "ImplicitFaces")
    coordinate_id = int(coordinates.this)
    assert faces.coordIndex.getNum() == view.TriangleCount * 4
    original_size = coordinates.point.getNum()
    builds = view.CacheBuildCount
    Gui.activeDocument().activeView().viewAxonometric()
    Gui.activeDocument().activeView().fitAll()
    feature.Placement = App.Placement(App.Vector(5, 6, 7), App.Rotation(App.Vector(0, 0, 1), 30))
    document.recompute()
    Gui.updateGui()
    assert view.CacheBuildCount == builds, "camera/placement rebuilt local geometry"
    assert int(named(view.RootNode, "ImplicitCoordinates").this) == coordinate_id
    bounds_action = coin.SoGetBoundingBoxAction(coin.SbViewportRegion(640, 480))
    bounds_action.apply(view.RootNode)
    bounds = bounds_action.getBoundingBox()
    local = Implicit.tessellateAdaptive(feature, 16)
    placed = [feature.Placement.multVec(App.Vector(*point)) for point in local["vertices"]]
    # Coin may transform a cached local AABB, which conservatively encloses the
    # transformed vertices rather than giving their tight rotated bounds.
    local_limits = [(min(p[i] for p in local["vertices"]), max(p[i] for p in local["vertices"]))
                    for i in range(3)]
    corners = [feature.Placement.multVec(App.Vector(*point))
               for point in itertools.product(*local_limits)]
    for axis in range(3):
        expected_min = min(tuple(point)[axis] for point in placed)
        expected_max = max(tuple(point)[axis] for point in placed)
        corner_min = min(tuple(point)[axis] for point in corners)
        corner_max = max(tuple(point)[axis] for point in corners)
        assert corner_min - 2e-5 <= bounds.getMin().getValue()[axis] <= expected_min + 2e-5
        assert expected_max - 2e-5 <= bounds.getMax().getValue()[axis] <= corner_max + 2e-5

    for mode in ("Shaded", "Wireframe", "Flat Lines"):
        view.DisplayMode = mode
    view.SurfaceColor = (0.9, 0.3, 0.1)
    view.Resolution = 8
    assert coordinates.point.getNum() < original_size, "coordinate buffer did not shrink"
    assert faces.coordIndex.getNum() == view.TriangleCount * 4
    assert int(named(view.RootNode, "ImplicitCoordinates").this) == coordinate_id, "Coin node was replaced"
    previous = view.CacheBuildCount
    view.AdaptiveSampling = False
    assert view.CacheBuildCount > previous
    assert faces.coordIndex.getNum() == view.TriangleCount * 4

    previous = view.CacheBuildCount
    graph["root"]["right"]["radius"] = 2
    Implicit.setFieldGraph(feature, json.dumps(graph))
    document.recompute()
    assert view.CacheBuildCount > previous, "graph edit did not invalidate display"

    # A bad graph clears the display; fixing it must upload a fresh cache.
    canonical = feature.FieldGraph
    feature.FieldGraph = "invalid"
    document.recompute()
    assert view.TriangleCount == 0
    feature.FieldGraph = canonical
    document.recompute()
    assert view.TriangleCount > 0

    with tempfile.TemporaryDirectory(prefix="implicit-native-gui-") as directory:
        path = os.path.join(directory, "native.FCStd")
        document.saveAs(path)
        App.closeDocument(document.Name)
        document = App.openDocument(path)
        restored = document.getObject("NativeField")
        view = restored.ViewObject
        Gui.updateGui()
        assert view.TypeId == "ImplicitGui::ViewProviderShape"
        assert view.TriangleCount > 0, "reload did not rebuild display"
        assert view.Resolution == 8 and view.DisplayMode == "Flat Lines"
        assert not view.AdaptiveSampling
        assert abs(view.SurfaceColor[0] - 0.9) < 0.005
        assert restored.Placement.Base == App.Vector(5, 6, 7)
        faces = named(view.RootNode, "ImplicitFaces")
        assert faces.coordIndex.getNum() == view.TriangleCount * 4
        App.closeDocument(document.Name)
    print("native implicit GUI smoke test passed", flush=True)
    Gui.getMainWindow().close()


try:
    main()
except BaseException:
    traceback.print_exc()
    os._exit(1)
