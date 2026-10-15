# SPDX-License-Identifier: LGPL-2.1-or-later
"""Background display jobs: responsiveness, coalescing, stale results and lifetime."""
import math
import os
import tempfile
import traceback

import FreeCAD as App
import FreeCADGui as Gui
import Implicit
import ImplicitGui  # noqa: F401
from PySide6 import QtCore
from pivy import coin


def wait_until(predicate, timeout=60000):
    if predicate():
        return
    loop = QtCore.QEventLoop()
    poll = QtCore.QTimer()
    poll.setInterval(5)
    poll.timeout.connect(lambda: loop.quit() if predicate() else None)
    deadline = QtCore.QTimer()
    deadline.setSingleShot(True)
    deadline.timeout.connect(loop.quit)
    poll.start()
    deadline.start(timeout)
    loop.exec()
    poll.stop()
    deadline.stop()
    assert predicate(), "background GUI operation timed out"


def idle(view):
    wait_until(lambda: not view.Meshing)


def ready(view):
    idle(view)
    assert view.MeshStatus == "Ready", view.MeshStatus
    assert view.DisplayedRequestId == view.MeshRequestId
    assert view.TriangleCount > 0


def coordinates(view):
    search = coin.SoSearchAction()
    search.setName(coin.SbName("ImplicitCoordinates"))
    search.setSearchingAll(True)
    search.apply(view.RootNode)
    assert search.getPath() is not None
    return search.getPath().getTail()


def sphere_points(feature, radius):
    view = feature.ViewObject
    ready(view)
    node = coordinates(view)
    assert node.point.getNum() > 0
    for point in node.point.getValues():
        x, y, z = point.getValue()
        distance = math.sqrt((x-feature.Center.x)**2 + (y-feature.Center.y)**2 + (z-feature.Center.z)**2)
        assert abs(distance-radius) < 2e-5, (distance, radius)


def heavy(feature):
    feature.Function = "Gyroid"
    feature.Period = 3
    feature.IsoValue = 0.17
    feature.DomainMin, feature.DomainMax = (-6, -6, -6), (6, 6, 6)
    feature.ViewObject.Resolution = 64
    feature.Document.recompute()


def main():
    doc = App.newDocument("AsyncImplicitGui")
    doc.UndoMode = 0
    field = doc.addObject("Implicit::Feature", "Field")
    field.Function = "Sphere"
    field.Radius = 3
    field.DomainMin, field.DomainMax = (-6, -6, -6), (6, 6, 6)
    view = field.ViewObject
    view.Resolution = 8
    doc.recompute()
    assert not view.BackgroundMeshing
    uploads = view.CacheBuildCount
    node_id = int(coordinates(view).this)
    view.BackgroundMeshing = True
    ready(view)
    assert view.MeshJobCount == 0 and view.CacheBuildCount == uploads, "ignored existing mesh cache"

    heavy(field)
    assert view.Meshing, "background request did not return before GUI delivery"
    beats = [0]
    heartbeat = QtCore.QTimer()
    heartbeat.setInterval(1)
    def tick():
        if view.Meshing:
            beats[0] += 1
    heartbeat.timeout.connect(tick)
    heartbeat.start()
    ready(view)
    heartbeat.stop()
    assert beats[0] > 0, "GUI timer did not run during extraction"
    assert int(coordinates(view).this) == node_id, "replaced retained Coin node"
    jobs, requests = view.MeshJobCount, view.MeshRequestId
    uploads = view.CacheBuildCount
    heavy(field)
    for index in range(20):
        field.IsoValue = 0.2 + index * 0.001
        doc.recompute()
    field.Function = "Sphere"
    field.Center = (1, 0, 0)
    field.Radius = 2
    view.Resolution = 16
    doc.recompute()
    ready(view)
    assert view.MeshRequestId > requests + 20
    assert view.MeshJobCount < jobs + 20, "rapid edits were not coalesced"
    assert view.CacheBuildCount > uploads
    sphere_points(field, 2)
    assert view.TriangleCount == len(Implicit.tessellateAdaptive(field, 16)["triangles"])
    field.Tolerance = 1e-6
    doc.recompute()
    ready(view)
    field.Tolerance = -1
    doc.recompute()
    idle(view)
    assert view.MeshStatus.startswith("Error:") and view.TriangleCount == 0
    field.Tolerance = 1e-9
    doc.recompute()
    ready(view)
    field.Center = (100, 0, 0)
    doc.recompute()
    idle(view)
    assert view.MeshStatus == "Ready" and view.TriangleCount == 0
    assert view.DisplayedRequestId == view.MeshRequestId
    assert coordinates(view).point.getNum() == 0
    field.Center = (1, 0, 0)
    doc.recompute()
    sphere_points(field, 2)
    view.Resolution = 12  # adaptive rounding should reuse the effective-16 cache
    ready(view)

    # A completed background result populates the native cache, too.
    uploads = view.CacheBuildCount
    view.BackgroundMeshing = False
    assert view.CacheBuildCount == uploads, "synchronous fallback rebuilt a completed mesh"
    view.BackgroundMeshing = True
    ready(view)
    view.AdaptiveSampling = False
    ready(view)
    assert view.TriangleCount == len(Implicit.tessellate(field, 12)["triangles"])
    view.AdaptiveSampling = True
    ready(view)
    uploads = view.CacheBuildCount
    jobs = view.MeshJobCount
    field.Placement.Base = (5, 6, 7)
    doc.recompute()
    Gui.activeDocument().activeView().viewAxonometric()
    Gui.activeDocument().activeView().fitAll()
    Gui.updateGui()
    assert view.CacheBuildCount == uploads and view.MeshJobCount == jobs

    heavy(field)
    view.CancelMeshing = True
    idle(view)
    assert not view.CancelMeshing and view.MeshStatus == "Cancelled"
    assert view.DisplayedRequestId == 0 and view.TriangleCount == 0
    assert field.isValid(), "display cancellation invalidated mathematical geometry"
    view.Resolution = 16
    ready(view)

    # Obsolete results must not resurrect geometry after an invalid definition.
    heavy(field)
    field.FieldGraph = "invalid"
    doc.recompute()
    idle(view)
    assert view.MeshStatus.startswith("Error:") and view.TriangleCount == 0
    assert view.DisplayedRequestId == 0
    field.FieldGraph = ""
    field.Function = "Sphere"
    field.Radius = 3
    doc.recompute()
    ready(view)
    sphere_points(field, 3)

    # Switching modes while a job is outstanding suppresses late uploads.
    heavy(field)
    field.Function = "Sphere"
    field.Radius = 4
    doc.recompute()
    view.BackgroundMeshing = False
    idle(view)
    sphere_points(field, 4)
    view.BackgroundMeshing = True
    view.Visibility = False
    jobs = view.MeshJobCount
    field.Radius = 2
    doc.recompute()
    idle(view)
    assert view.MeshStatus == "Hidden" and view.MeshJobCount == jobs
    assert view.TriangleCount == 0
    view.Visibility = True
    sphere_points(field, 2)

    if os.environ.get("IMPLICIT_TEST_PART_BRIDGE") == "1":
        import Part  # noqa: F401
        import PartGui  # noqa: F401
        box = doc.addObject("Part::Box", "Box")
        box.Length, box.Width, box.Height = 4, 4, 4
        brep = doc.addObject("Implicit::Feature", "LiveBRep")
        brep.Operation, brep.Left = "BRep", box
        brep.ViewObject.Resolution = 8
        brep.ViewObject.BackgroundMeshing = True
        doc.recompute()
        box.Length = 3
        doc.recompute()
        ready(brep.ViewObject)
        points = coordinates(brep.ViewObject).point.getValues()
        assert all(-1e-4 <= p.getValue()[0] <= 3.0001 for p in points)
        doc.removeObject("Box")
        doc.recompute()
        idle(brep.ViewObject)
        assert brep.ViewObject.MeshStatus.startswith("Error:")
        assert brep.ViewObject.TriangleCount == 0
        doc.removeObject("LiveBRep")

    # Destroying a provider must not wait for or receive a finished-job callback.
    doomed = doc.addObject("Implicit::Feature", "Doomed")
    doomed.ViewObject.BackgroundMeshing = True
    heavy(doomed)
    doc.removeObject("Doomed")
    field.Radius = 2.5
    view.Resolution = 16
    doc.recompute()
    sphere_points(field, 2.5)  # same bounded pool drains the cancelled deleted job
    assert doc.getObject("Doomed") is None

    with tempfile.TemporaryDirectory(prefix="implicit-async-") as directory:
        path = os.path.join(directory, "async.FCStd")
        field.Radius = 3.5
        doc.recompute()
        doc.saveAs(path)
        App.closeDocument(doc.Name)  # also cancel an outstanding job during close
        doc = App.openDocument(path)
        field = doc.getObject("Field")
        view = field.ViewObject
        assert view.BackgroundMeshing and view.Resolution == 16
        sphere_points(field, 3.5)
        assert field.Placement.Base == App.Vector(5, 6, 7)
        App.closeDocument(doc.Name)
    print("native implicit async GUI smoke test passed", flush=True)
    Gui.getMainWindow().close()


try:
    main()
except BaseException:
    traceback.print_exc()
    os._exit(1)
