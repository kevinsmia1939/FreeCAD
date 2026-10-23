# SPDX-License-Identifier: LGPL-2.1-or-later
"""Property rebuilds keep Qt alive and preserve edit/undo transaction ownership."""
import os
import time
import traceback
import tempfile
import FreeCAD as App
import FreeCADGui as Gui
import ImplicitMixed
import ImplicitSolid
import ImplicitSolidRecompute
import ImplicitOCCT as native
from PySide import QtCore


def until(predicate, seconds=90):
    deadline = time.monotonic() + seconds
    ticks = 0
    while not predicate():
        assert time.monotonic() < deadline, "Background recompute condition timed out"
        loop = QtCore.QEventLoop()
        QtCore.QTimer.singleShot(20, loop.quit)
        loop.exec()
        ticks += 1
    return ticks


def ready(obj):
    ticks = until(lambda: obj.Proxy._recompute_request is None)
    assert obj.Geometry is not None and obj.SolidValidated, obj.BackendStatus
    return ticks


def change(doc, obj, name, value):
    doc.openTransaction("Change native build setting")
    setattr(obj, name, value)
    doc.recompute()
    doc.commitTransaction()


def main():
    Gui.activateWorkbench("ImplicitModelingWorkbench")
    doc = App.newDocument("NativeRecomputeGUI")
    doc.UndoMode = 1
    field = doc.addObject("Implicit::Feature", "Gyroid")
    field.Function, field.Period = "Gyroid", 10
    field.DomainMin, field.DomainMax = (0, 0, 0), (10, 10, 10)
    box = doc.addObject("Part::Box", "Box")
    box.Length = box.Width = box.Height = 10
    doc.recompute()
    source = ImplicitMixed.create(field, box, corner_policy="Regularized")
    obj, peer = ImplicitSolid.create(source), ImplicitSolid.create(source)
    consumer = doc.addObject("App::FeaturePython", "Consumer")
    consumer.addProperty("App::PropertyLink", "Input")
    consumer.Input = obj
    consumer.addProperty("App::PropertyInteger", "ObservedSolidCount")
    consumer.setExpression("ObservedSolidCount", "Input.SolidCount")
    obj.BackgroundRecompute = peer.BackgroundRecompute = True
    doc.recompute()
    doc.commitTransaction()
    build = native.build_mixed_solids
    def forbidden(*_args):
        raise AssertionError("GUI property recompute used synchronous solid construction")
    native.build_mixed_solids = forbidden
    try:
        manager = ImplicitSolidRecompute.scheduler()
        change(doc, obj, "MaximumSegmentTests", 7999999)
        assert obj.Geometry is None and not obj.SolidValidated
        assert consumer.ObservedSolidCount == 0
        first = obj.Proxy._recompute_request
        until(lambda: first.job is not None)
        job = first.job
        change(doc, obj, "MaximumSegmentTests", 7999998)
        assert obj.Proxy._recompute_request is not first
        assert ready(obj) > 10, "Qt did not run during property rebuild"
        until(lambda: native.solid_job_status(job)["state"] == "cancelled", 10)
        assert obj.MaximumSegmentTests == 7999998
        assert consumer.ObservedSolidCount == obj.SolidCount > 0

        record = native.dumps_mixed_solids(obj.Geometry)
        doc.openTransaction("Abort pending native edit")
        obj.MaximumSegmentTests = 7999992
        doc.recompute()
        aborted = obj.Proxy._recompute_request
        assert aborted is not None and obj.Geometry is None
        doc.abortTransaction()
        assert aborted.identity not in manager.requests
        assert native.dumps_mixed_solids(obj.Geometry) == record
        assert obj.MaximumSegmentTests == 7999998

        doc.undo(); doc.recompute(); ready(obj)
        assert obj.MaximumSegmentTests == 7999999
        doc.redo(); doc.recompute(); ready(obj)
        assert obj.MaximumSegmentTests == 7999998

        # Undo while a job is live discards it and restores the old geometry.
        record = native.dumps_mixed_solids(obj.Geometry)
        change(doc, obj, "MaximumSegmentTests", 7999997)
        request = obj.Proxy._recompute_request
        until(lambda: request.job is not None)
        doc.undo()
        assert obj.Proxy._recompute_request is None
        assert native.dumps_mixed_solids(obj.Geometry) == record
        until(lambda: native.solid_job_status(request.job)["state"] == "cancelled", 10)
        doc.recompute()
        assert obj.Geometry is not None and obj.MaximumSegmentTests == 7999998

        # A completed job waits while another edit is active. Publication after
        # that edit closes must not insert the output in its undo record.
        change(doc, obj, "MaximumSegmentTests", 7999996)
        request = obj.Proxy._recompute_request
        until(lambda: request.job is not None)
        doc.openTransaction("Unrelated label edit")
        old_label = box.Label
        box.Label = "Unrelated label"
        status = obj.BackendStatus
        until(lambda: native.solid_job_status(request.job)["state"] == "ready")
        assert obj.Geometry is None and obj.BackendStatus == status
        doc.commitTransaction()
        ready(obj)
        record = native.dumps_mixed_solids(obj.Geometry)
        doc.undo()
        assert box.Label == old_label and obj.MaximumSegmentTests == 7999996
        assert native.dumps_mixed_solids(obj.Geometry) == record

        change(doc, obj, "MaximumCells", 1)
        until(lambda: obj.Proxy._recompute_request is None)
        assert obj.Geometry is None and not obj.SolidValidated
        assert "failed background recompute" in obj.BackendStatus
        change(doc, obj, "MaximumCells", 4000000)
        ready(obj)

        change(doc, obj, "MaximumSegmentTests", 7999994)
        request = obj.Proxy._recompute_request
        until(lambda: request.job is not None)
        field.Period = 9
        until(lambda: obj.Proxy._recompute_request is None)
        assert obj.Geometry is None and not obj.SolidValidated
        until(lambda: native.solid_job_status(request.job)["state"] == "cancelled", 10)
        field.Period = 10
        doc.recompute(); ready(obj)

        source.Operation = "BoxMinusField"
        try:
            obj.Proxy.execute(obj)  # Deliberately bypass source recompute.
        except ValueError as error:
            assert "recompute source" in str(error)
        else:
            raise AssertionError("A stale boundary recipe was accepted")
        assert obj.Geometry is None and obj.Proxy._recompute_request is None
        source.Operation = "Common"
        doc.recompute(); ready(obj)

        publish = obj.Proxy.publish
        def broken_publish(owner, completed):
            publish(owner, completed)
            raise ValueError("Injected publication failure")
        obj.Proxy.publish = broken_publish
        try:
            change(doc, obj, "MaximumSegmentTests", 7999993)
            until(lambda: obj.Proxy._recompute_request is None)
            assert obj.Geometry is None and not obj.SolidValidated
            assert "Injected publication failure" in obj.BackendStatus
        finally:
            obj.Proxy.publish = publish
        doc.recompute(); ready(obj)

        # Persistence keeps the setting and actual topology, without treating
        # restored output as a freshly validated result or rebuilding it.
        with tempfile.TemporaryDirectory(prefix="implicit-recompute-") as directory:
            filename = os.path.join(directory, "background.FCStd")
            doc.saveCopy(filename)
            loaded = App.openDocument(filename)
            restored = loaded.getObject(obj.Name)
            assert restored.BackgroundRecompute and restored.Geometry is not None
            assert not restored.SolidValidated
            loaded.recompute()
            assert restored.Proxy._recompute_request is None and not restored.SolidValidated
            App.closeDocument(loaded.Name)
            App.setActiveDocument(doc.Name)

        change(doc, peer, "MaximumSegmentTests", 7999999)
        request = peer.Proxy._recompute_request
        until(lambda: request.job is not None)
        doc.removeObject(peer.Name)
        assert request.identity not in manager.requests
        until(lambda: native.solid_job_status(request.job)["state"] == "cancelled", 10)

        change(doc, obj, "MaximumSegmentTests", 7999995)
        request = obj.Proxy._recompute_request
        until(lambda: request.job is not None)
        name = doc.Name
        App.closeDocument(name)
        assert request.identity not in manager.requests
        until(lambda: native.solid_job_status(request.job)["state"] == "cancelled", 10)
    finally:
        native.build_mixed_solids = build
        if "NativeRecomputeGUI" in App.listDocuments():
            App.closeDocument("NativeRecomputeGUI")
    print("native implicit property recompute GUI smoke test passed", flush=True)


try:
    main()
except BaseException:
    traceback.print_exc()
    os._exit(1)
finally:
    Gui.getMainWindow().close()
