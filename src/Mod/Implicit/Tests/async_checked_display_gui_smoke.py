# SPDX-License-Identifier: LGPL-2.1-or-later
"""Checked display stays responsive and rejects superseded view results."""
import os
import time
import traceback
import FreeCAD as App
import FreeCADGui as Gui
import ImplicitMixed
import ImplicitSolid
from ImplicitSolidBatch import SolidBatch
import ImplicitSurfaceJobs
import ImplicitOCCT as native
from PySide import QtCore


def pulse():
    loop = QtCore.QEventLoop()
    QtCore.QTimer.singleShot(20, loop.quit)
    loop.exec()


def until(predicate, seconds=90):
    deadline = time.monotonic() + seconds
    ticks = 0
    while not predicate():
        assert time.monotonic() < deadline, "GUI display condition timed out"
        pulse()
        ticks += 1
    return ticks


def ready(obj):
    ticks = until(lambda: not obj.ViewObject.Proxy._display_pending)
    assert obj.ViewObject.DisplayProximityChecked, obj.ViewObject.SurfacePreviewStatus
    assert obj.ViewObject.Proxy._mesh and "NativeFace1" in obj.ViewObject.Proxy._elements
    return ticks


def main():
    Gui.activateWorkbench("ImplicitModelingWorkbench")
    doc = App.newDocument("AsyncCheckedDisplay")
    doc.UndoMode = 1
    document_name = doc.Name
    field = doc.addObject("Implicit::Feature", "Gyroid")
    field.Function, field.Period, field.IsoValue = "Gyroid", 10, 0
    field.DomainMin, field.DomainMax = (0, 0, 0), (10, 10, 10)
    box = doc.addObject("Part::Box", "Box")
    box.Length = box.Width = box.Height = 10
    doc.recompute()
    source = ImplicitMixed.create(field, box, corner_policy="Regularized")
    first, second = ImplicitSolid.create(source), ImplicitSolid.create(source)
    record = native.dumps_mixed_solids(first.Geometry)
    sync, start = native.tessellate_mixed_checked, native.start_surface_job
    calls = []
    def forbidden(*_args):
        raise AssertionError("GUI invoked synchronous checked extraction")
    def observed(*args):
        job = start(*args)
        calls.append(args[1:])
        return job
    native.tessellate_mixed_checked, native.start_surface_job = forbidden, observed
    try:
        view = first.ViewObject.Proxy
        first.ViewObject.CheckSurfaceDisplay = True
        assert view._display_pending and not first.ViewObject.DisplayProximityChecked
        first.ViewObject.DisplayProximityChecked = True
        assert not first.ViewObject.DisplayProximityChecked
        assert ready(first) > 10, "Qt did not run while checked extraction was pending"
        old_generation, old_key, old_mesh = view._display_generation, view._preview_key, view._mesh
        # Repeated edits before a timer tick must submit only the last descriptor.
        before = len(calls)
        first.ViewObject.SurfaceTolerance = .099999
        first.ViewObject.SurfaceTolerance = .099998
        first.ViewObject.SurfaceMaximumCells = 128
        first.ViewObject.SurfaceTolerance = .1
        second.ViewObject.CheckSurfaceDisplay = True
        assert view._display_pending and view._mesh is None
        view._checked_job_ready(old_generation, old_key, old_mesh)
        view._checked_job_ready(old_generation, view._surface_key(), old_mesh)
        assert view._mesh is None and not first.ViewObject.DisplayProximityChecked
        ready(first); ready(second)
        assert len(calls) == before + 2
        assert all(settings[0] == .1 for settings in calls[before:])
        assert native.dumps_mixed_solids(first.Geometry) == record

        # An unrelated checked view must yield its native slot to solid work,
        # retaining the latest descriptor for automatic retry afterwards.
        manager = ImplicitSurfaceJobs.scheduler()
        second_view = second.ViewObject.Proxy
        second.ViewObject.SurfaceMaximumCells = 128
        until(lambda: manager.requests[id(second_view)].job is not None)
        interrupted = manager.requests[id(second_view)].job
        transaction = App.setActiveTransaction("Solid preview has priority", True)
        batch = SolidBatch([first], transaction)
        until(lambda: batch.step() != "pending")
        assert batch.state == "ready", batch.error
        assert native.native_job_status(interrupted)["state"] == "cancelled"
        doc.recompute()
        App.closeActiveTransaction(False, transaction)
        ready(first); ready(second)

        first.ViewObject.SurfaceTolerance = .099999
        manager = ImplicitSurfaceJobs.scheduler()
        until(lambda: manager.requests[id(view)].job is not None)
        job = manager.requests[id(view)].job
        until(lambda: native.native_job_status(job)["phase"] == "coverage")
        first.ViewObject.ShowImplicitSurface = False
        assert not view._display_pending and view._mesh is None
        assert not first.ViewObject.DisplayProximityChecked
        until(lambda: native.native_job_status(job)["state"] == "cancelled", 10)
        first.ViewObject.SurfaceTolerance = .1
        first.ViewObject.ShowImplicitSurface = True
        ready(first)

        # Dirty live input properties invalidate a pending check even before
        # source or result recompute has changed their stored geometry records.
        first.ViewObject.SurfaceTolerance = .099999
        until(lambda: manager.requests[id(view)].job is not None)
        dirty_job = manager.requests[id(view)].job
        field.Period = 9
        until(lambda: not view._display_pending)
        until(lambda: native.native_job_status(dirty_job)["state"] == "cancelled", 10)
        assert not first.ViewObject.DisplayProximityChecked
        assert "inputs changed" in first.ViewObject.SurfacePreviewStatus
        field.Period = 10
        doc.recompute()
        first.ViewObject.SurfaceTolerance = .1
        ready(first)

        second_view = second.ViewObject.Proxy
        second.ViewObject.SurfaceMaximumCells = 64
        until(lambda: manager.requests[id(second_view)].job is not None)
        job = manager.requests[id(second_view)].job
        doc.removeObject(second.Name)
        assert id(second_view) not in manager.requests
        until(lambda: native.native_job_status(job)["state"] == "cancelled", 10)

        first.ViewObject.SurfaceMaximumCells = 64
        until(lambda: manager.requests[id(view)].job is not None)
        job = manager.requests[id(view)].job
        App.closeDocument(doc.Name)
        assert id(view) not in manager.requests and not view._display_pending
        until(lambda: native.native_job_status(job)["state"] == "cancelled", 10)
    finally:
        native.tessellate_mixed_checked, native.start_surface_job = sync, start
        if document_name in App.listDocuments():
            App.closeDocument(document_name)
    print("native implicit async checked display GUI smoke test passed", flush=True)


try:
    main()
except BaseException:
    traceback.print_exc()
    os._exit(1)
finally:
    Gui.getMainWindow().close()
