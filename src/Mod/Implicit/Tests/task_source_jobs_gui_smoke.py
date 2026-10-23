# SPDX-License-Identifier: LGPL-2.1-or-later
"""Source/solid task stages retain one transaction and never trace synchronously."""
import os
import time
import traceback
import FreeCAD as App
import FreeCADGui as Gui
import ImplicitMixed
import ImplicitSolid
import ImplicitTaskBatch
import ImplicitOCCT as native
from PySide import QtCore, QtWidgets


def until(predicate, seconds=120):
    deadline = time.monotonic() + seconds
    ticks = 0
    while not predicate():
        assert time.monotonic() < deadline, "Task source condition timed out"
        loop = QtCore.QEventLoop()
        QtCore.QTimer.singleShot(10, loop.quit)
        loop.exec()
        ticks += 1
    return ticks


def finish(task):
    return until(lambda: task.batch is None)


def edit(obj):
    assert Gui.getDocument(obj.Document.Name).setEdit(obj.Name)
    return obj.ViewObject.Proxy._task


def resized(task):
    for name in ("Period", "Length", "Width", "Height"):
        task.parameters[name].setValue(5)
    task.fit_domain.setChecked(True)
    task.clicked(QtWidgets.QDialogButtonBox.Apply)
    assert task.batch is not None, task.status.text()
    assert task.batch.source_stage
    return task.batch


def main():
    Gui.activateWorkbench("ImplicitModelingWorkbench")
    doc = App.newDocument("TaskSourcesGUI")
    doc.UndoMode = 1
    field = doc.addObject("Implicit::Feature", "Gyroid")
    field.Function, field.Period = "Gyroid", 10
    field.DomainMin, field.DomainMax = (0, 0, 0), (10, 10, 10)
    box = doc.addObject("Part::Box", "Box")
    box.Length = box.Width = box.Height = 10
    doc.recompute()
    sources = [ImplicitMixed.create(field, box, corner_policy="Regularized") for _ in range(2)]
    owners = [ImplicitSolid.create(source) for source in sources]
    original_sources = [native.dumps_mixed(source.Geometry) for source in sources]
    originals = [native.dumps_mixed_solids(obj.Geometry) for obj in owners]
    mixed, raw, build = native.mixed_box, native._mixed_box, native.build_mixed_solids
    def forbidden(*_args, **_kwargs):
        raise AssertionError("GUI task used synchronous source/solid construction")
    native.mixed_box = native._mixed_box = native.build_mixed_solids = forbidden
    try:
        task = edit(owners[0])
        batch = resized(task)
        assert all(obj.Geometry is None for obj in sources + owners)
        assert doc.recompute()  # Pending tokens must suppress synchronous fallback.
        until(lambda: batch.source_stage and len(batch.inner.results) == 1)
        assert all(source.Geometry is None for source in sources), "Sources published before whole-group success"
        assert finish(task) > 10
        assert all(source.SeamBoundVerified for source in sources)
        assert all(obj.SolidValidated for obj in owners)
        assert field.Period.Value == box.Length.Value == 5
        assert task.reject()
        assert [native.dumps_mixed(source.Geometry) for source in sources] == original_sources
        assert [native.dumps_mixed_solids(obj.Geometry) for obj in owners] == originals

        task = edit(owners[0])
        batch = resized(task)
        until(lambda: batch.job is not None)
        job = batch.job
        assert task.reject() and batch.state == "cancelled"
        until(lambda: native.native_job_status(job)["state"] == "cancelled", 10)
        assert field.Period.Value == 10 and box.Length.Value == 10

        task = edit(owners[0])
        batch = resized(task)
        task.controls["MaximumGeometryDepth"].setValue(18)
        finish(task)
        assert "settings changed" in task.status.text()
        assert all(obj.Geometry is None for obj in sources + owners)
        assert task.reject()

        # A later source failure must discard the earlier successful source,
        # without publishing it or starting any solid builds.
        task = edit(owners[0])
        start = native.start_boundary_job_from_record
        submitted = []
        def failing_second(*args):
            if len(submitted) == 1:
                assert len(task.batch.inner.results) == 1
                job = native._start_boundary_job(args[0], "bad B-Rep", *args[2:])
            else:
                job = start(*args)
            submitted.append(args)
            return job
        native.start_boundary_job_from_record = failing_second
        try:
            resized(task)
            finish(task)
            assert len(submitted) == 2 and "Preview failed" in task.status.text()
            assert all(obj.Geometry is None for obj in sources + owners)
        finally:
            native.start_boundary_job_from_record = start
        assert task.reject()

        # Source editor also stages source work, then rebuilds its linked solid.
        source, owner = sources[0], owners[0]
        source.BackgroundRecompute = owner.BackgroundRecompute = True
        doc.recompute()
        untouched = native.dumps_mixed_solids(owners[1].Geometry)
        task = edit(source)
        task.operation.setCurrentText("BoxMinusField")
        task.clicked(QtWidgets.QDialogButtonBox.Apply)
        assert task.batch is not None and task.batch.source_stage
        assert not task.accept()  # OK commits only after both stages succeed.
        finish(task)
        assert task.closed and not Gui.Control.activeDialog()
        assert owner.SolidValidated and str(source.Operation) == "BoxMinusField"
        assert native.dumps_mixed_solids(owners[1].Geometry) == untouched

        task = edit(source)
        task.operation.setCurrentText("Common")
        prepare = ImplicitTaskBatch.PreparedSolidBatch
        def preflight_failure(*_args):
            raise ValueError("Injected source preflight failure")
        ImplicitTaskBatch.PreparedSolidBatch = preflight_failure
        try:
            task.clicked(QtWidgets.QDialogButtonBox.Apply)
            assert task.batch is None and "source preflight" in task.status.text()
            assert source.Geometry is None and owner.Geometry is None
        finally:
            ImplicitTaskBatch.PreparedSolidBatch = prepare
        assert task.reject()

        task = edit(source)
        task.cells.setCurrentText("4")
        task.clicked(QtWidgets.QDialogButtonBox.Apply)
        finish(task)
        assert source.Geometry is None and owner.Geometry is None
        assert "Preview failed" in task.status.text()
        task.cells.setCurrentText("512")
        task.clicked(QtWidgets.QDialogButtonBox.Apply)
        finish(task)
        assert source.Geometry is not None and owner.SolidValidated, task.status.text()
        assert task.reject()

        task = edit(source)
        task.operation.setCurrentText("Common")
        task.clicked(QtWidgets.QDialogButtonBox.Apply)
        batch = task.batch
        until(lambda: batch.job is not None)
        job = batch.job
        App.closeActiveTransaction(False, task.transaction)
        doc.openTransaction("Foreign label while task owns no transaction")
        box.Label = "Foreign label"
        foreign = App.getActiveTransaction()
        before = (source.InputFingerprint, source.NativeRevision, source.BackendStatus,
                  owner.InputFingerprint, owner.NativeRevision, owner.BackendStatus)
        finish(task)
        assert batch.state == "failed" and App.getActiveTransaction() == foreign
        assert (source.InputFingerprint, source.NativeRevision, source.BackendStatus,
                owner.InputFingerprint, owner.NativeRevision, owner.BackendStatus) == before
        assert not task.reject()  # Closing cannot abort the foreign edit.
        assert App.getActiveTransaction() == foreign
        doc.abortTransaction()
        assert task.reject()
        until(lambda: native.native_job_status(job)["state"] == "cancelled", 10)
        doc.recompute()
        until(lambda: source.Proxy._recompute_request is None and owner.Proxy._recompute_request is None)
        assert source.Geometry is not None and owner.SolidValidated

        source.MaximumCells = 256
        doc.recompute()
        ordinary = source.Proxy._recompute_request
        until(lambda: ordinary.job is not None)
        task = edit(source)
        task.operation.setCurrentText("Common" if str(source.Operation) == "BoxMinusField" else "BoxMinusField")
        task.clicked(QtWidgets.QDialogButtonBox.Apply)
        assert task.batch is not None and task.batch.source_stage, task.status.text()
        until(lambda: native.native_job_status(ordinary.job)["state"] == "cancelled", 10)
        finish(task)
        assert source.Geometry is not None and owner.SolidValidated
        assert task.reject()
        until(lambda: source.Proxy._recompute_request is None and owner.Proxy._recompute_request is None)
        assert source.Geometry is not None and owner.SolidValidated

        task = edit(source)
        task.operation.setCurrentText("Common" if str(source.Operation) == "BoxMinusField" else "BoxMinusField")
        task.clicked(QtWidgets.QDialogButtonBox.Apply)
        batch = task.batch
        until(lambda: batch.job is not None)
        job = batch.job
        App.closeDocument(doc.Name)
        assert batch.state == "cancelled" and not Gui.Control.activeDialog()
        until(lambda: native.native_job_status(job)["state"] == "cancelled", 10)
    finally:
        native.mixed_box, native._mixed_box, native.build_mixed_solids = mixed, raw, build
        if "TaskSourcesGUI" in App.listDocuments():
            App.closeDocument("TaskSourcesGUI")
    print("native implicit task source jobs GUI smoke test passed", flush=True)


try:
    main()
except BaseException:
    traceback.print_exc()
    os._exit(1)
finally:
    Gui.getMainWindow().close()
