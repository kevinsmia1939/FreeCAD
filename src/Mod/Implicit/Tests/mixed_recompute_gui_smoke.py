# SPDX-License-Identifier: LGPL-2.1-or-later
"""Source tracing hands off to fresh solid jobs without blocking GUI recompute."""
import os
import time
import tempfile
import traceback
import FreeCAD as App
import FreeCADGui as Gui
import ImplicitMixed
import ImplicitMixedRecompute
import ImplicitSolid
import ImplicitOCCT as native
from PySide import QtCore


def until(predicate, seconds=90):
    deadline = time.monotonic() + seconds
    ticks = 0
    while not predicate():
        assert time.monotonic() < deadline, "Source pipeline condition timed out"
        loop = QtCore.QEventLoop()
        QtCore.QTimer.singleShot(10, loop.quit)
        loop.exec()
        ticks += 1
    return ticks


def finish(source, owners):
    ticks = until(lambda: all(item.Proxy._recompute_request is None for item in [source] + owners))
    assert source.Geometry is not None, source.BackendStatus
    for obj in owners:
        assert obj.Geometry is not None and obj.SolidValidated, obj.BackendStatus
        assert native.dumps_mixed(native.source_mixed_solids(obj.Geometry)["boundary_handle"]) == native.dumps_mixed(source.Geometry)
    return ticks


def main():
    Gui.activateWorkbench("ImplicitModelingWorkbench")
    doc = App.newDocument("MixedRecomputeGUI")
    doc.UndoMode = 1
    field = doc.addObject("Implicit::Feature", "Gyroid")
    field.Function, field.Period = "Gyroid", 10
    field.DomainMin, field.DomainMax = (0, 0, 0), (10, 10, 10)
    box = doc.addObject("Part::Box", "Box")
    box.Length = box.Width = box.Height = 10
    doc.recompute()
    source = ImplicitMixed.create(field, box, corner_policy="Regularized")
    extra = ImplicitMixed.create(field, box, corner_policy="Regularized")
    owners = [ImplicitSolid.create(source), ImplicitSolid.create(source)]
    for item in [source, extra] + owners:
        item.BackgroundRecompute = True
    doc.recompute()
    doc.commitTransaction()
    mixed, raw, solid, start = native.mixed_box, native._mixed_box, native.build_mixed_solids, native.start_boundary_job_from_record
    calls = []
    def forbidden(*_args, **_kwargs):
        raise AssertionError("GUI pipeline invoked synchronous source/solid construction")
    def observed(*args, **kwargs):
        job = start(*args, **kwargs)
        calls.append(args[2:])
        return job
    native.mixed_box = native._mixed_box = native.build_mixed_solids = forbidden
    native.start_boundary_job_from_record = observed
    try:
        doc.openTransaction("Complement source in background")
        source.Operation = "BoxMinusField"
        assert doc.recompute()
        doc.commitTransaction()
        assert source.Geometry is None and source.Proxy._recompute_request is not None
        assert all(obj.Geometry is None and not obj.SolidValidated for obj in owners)
        assert all("Pending native boundary" in obj.BackendStatus for obj in owners)
        assert finish(source, owners) > 10
        assert source.SeamBoundVerified and len(calls) == 1
        doc.undo(); doc.recompute(); finish(source, owners)
        assert str(source.Operation) == "Common"
        doc.redo(); doc.recompute(); finish(source, owners)
        assert str(source.Operation) == "BoxMinusField"

        before = len(calls)
        for cells in (256, 128, 512):
            source.MaximumCells = cells
            doc.recompute()
        finish(source, owners)
        assert len(calls) == before + 1 and calls[-1][2] == 512

        # Direct source repair has no document recompute pass to invalidate
        # consumers; submitting the source job must clear them immediately.
        source.Proxy.rebuild(source)
        assert source.Geometry is None
        assert all(obj.Geometry is None and not obj.SolidValidated for obj in owners)
        finish(source, owners)

        field.InsideNegative = False
        try:
            source.Proxy.rebuild(source)
        except ValueError:
            pass
        else:
            raise AssertionError("Unsupported source definition was accepted")
        assert source.Geometry is None
        assert all(obj.Geometry is None and not obj.SolidValidated
                   and "Source boundary unavailable" in obj.BackendStatus for obj in owners)
        field.InsideNegative = True
        doc.recompute(); finish(source, owners)

        record = native.dumps_mixed(source.Geometry)
        doc.openTransaction("Abort source preview")
        source.Operation = "Common"
        doc.recompute()
        aborted = source.Proxy._recompute_request
        doc.abortTransaction()
        assert aborted.identity not in ImplicitMixedRecompute.scheduler().requests
        assert native.dumps_mixed(source.Geometry) == record
        doc.recompute(); finish(source, owners)

        # A foreign transaction must not receive pending output/status changes.
        source.MaximumCells = 256
        doc.recompute()
        request = source.Proxy._recompute_request
        until(lambda: request.job is not None)
        doc.openTransaction("Unrelated source label")
        old_label = box.Label
        box.Label = "Unrelated box label"
        status = source.BackendStatus
        until(lambda: native.native_job_status(request.job)["state"] == "ready")
        assert source.Geometry is None and source.BackendStatus == status
        doc.commitTransaction()
        finish(source, owners)
        record = native.dumps_mixed(source.Geometry)
        doc.undo()
        assert box.Label == old_label and native.dumps_mixed(source.Geometry) == record

        source.MaximumCells = 512
        doc.recompute()
        request = source.Proxy._recompute_request
        until(lambda: request.job is not None)
        field.Period = 9  # Dirty math must reject the pending result before recompute.
        until(lambda: source.Proxy._recompute_request is None)
        assert source.Geometry is None and not source.SeamBoundVerified
        assert all(obj.Geometry is None and not obj.SolidValidated for obj in owners)
        field.Period = 10
        doc.recompute(); finish(source, owners)

        source.MaximumCells = 4
        doc.recompute()
        until(lambda: source.Proxy._recompute_request is None)
        assert source.Geometry is None and "failed background boundary" in source.BackendStatus
        assert all("Source boundary unavailable" in obj.BackendStatus for obj in owners)
        source.MaximumCells = 512
        doc.recompute(); finish(source, owners)

        publish = source.Proxy.publish
        def broken_publish(*args):
            publish(*args)
            raise ValueError("Injected boundary publication failure")
        source.Proxy.publish = broken_publish
        try:
            source.MaximumCells = 256
            doc.recompute()
            until(lambda: source.Proxy._recompute_request is None)
            assert source.Geometry is None and not source.SeamBoundVerified
            assert source.Proxy._boundary is None and source.Proxy._mesh is None
            assert all(obj.Geometry is None and not obj.SolidValidated for obj in owners)
            assert "Injected boundary publication failure" in source.BackendStatus
        finally:
            source.Proxy.publish = publish
        doc.recompute(); finish(source, owners)

        with tempfile.TemporaryDirectory(prefix="implicit-source-recompute-") as directory:
            filename = os.path.join(directory, "source.FCStd")
            doc.saveCopy(filename)
            restored_doc = App.openDocument(filename)
            restored_source = restored_doc.getObject(source.Name)
            restored_owners = [restored_doc.getObject(obj.Name) for obj in owners]
            assert restored_source.BackgroundRecompute and not restored_source.SeamBoundVerified
            before = len(calls)
            restored_doc.recompute()
            assert restored_source.Geometry is not None and restored_source.Proxy._recompute_request is None
            assert all(obj.Geometry is not None and not obj.SolidValidated and obj.BackgroundRecompute
                       for obj in restored_owners)
            assert len(calls) == before
            App.closeDocument(restored_doc.Name)
            App.setActiveDocument(doc.Name)

        source.MaximumCells = 512
        doc.recompute()
        request = source.Proxy._recompute_request
        until(lambda: request.job is not None)
        for obj in owners:
            doc.removeObject(obj.Name)
        doc.removeObject(source.Name)
        assert request.identity not in ImplicitMixedRecompute.scheduler().requests
        until(lambda: native.native_job_status(request.job)["state"] == "cancelled", 10)

        extra.Operation = "BoxMinusField"
        doc.recompute()
        request = extra.Proxy._recompute_request
        until(lambda: request.job is not None)
        App.closeDocument(doc.Name)
        assert request.identity not in ImplicitMixedRecompute.scheduler().requests
        until(lambda: native.native_job_status(request.job)["state"] == "cancelled", 10)
    finally:
        native.mixed_box, native._mixed_box, native.build_mixed_solids, native.start_boundary_job_from_record = mixed, raw, solid, start
        if "MixedRecomputeGUI" in App.listDocuments():
            App.closeDocument("MixedRecomputeGUI")
    print("native implicit source recompute GUI smoke test passed", flush=True)


try:
    main()
except BaseException:
    traceback.print_exc()
    os._exit(1)
finally:
    Gui.getMainWindow().close()
