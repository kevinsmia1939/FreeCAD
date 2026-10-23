# SPDX-License-Identifier: LGPL-2.1-or-later
"""GUI creation defaults to background source/solid edits without changing factories."""
import os
import time
import tempfile
import traceback
import FreeCAD as App
import FreeCADGui as Gui
import ImplicitMixed
import ImplicitMixedCreate
import ImplicitSolid
import ImplicitOCCT as native
from PySide import QtCore


def until(predicate, seconds=120):
    deadline = time.monotonic() + seconds
    ticks = 0
    while not predicate():
        assert time.monotonic() < deadline, "GUI creation condition timed out"
        loop = QtCore.QEventLoop()
        QtCore.QTimer.singleShot(10, loop.quit)
        loop.exec()
        ticks += 1
    return ticks


def select_operands(field, box):
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(field)
    Gui.Selection.addSelection(box)


def main():
    Gui.activateWorkbench("ImplicitModelingWorkbench")
    doc = App.newDocument("CreationDefaultsGUI")
    doc.UndoMode = 1
    field = doc.addObject("Implicit::Feature", "Gyroid")
    field.Function, field.Period = "Gyroid", 10
    field.DomainMin, field.DomainMax = (0, 0, 0), (10, 10, 10)
    box = doc.addObject("Part::Box", "Box")
    box.Length = box.Width = box.Height = 10
    doc.recompute()
    doc.commitTransaction()
    mixed, raw, build = native.mixed_box, native._mixed_box, native.build_mixed_solids
    def forbidden(*_args, **_kwargs):
        raise AssertionError("GUI default creation or recompute used synchronous construction")
    native.mixed_box = native._mixed_box = native.build_mixed_solids = forbidden
    try:
        select_operands(field, box)
        task = ImplicitMixed.selected()
        assert task.form.objectName() == "ImplicitBoundaryCreation" and len(doc.Objects) == 2
        assert App.getActiveTransaction() is None
        assert not task.accept() and task.job is not None
        cancelled = task.job
        assert task.reject()
        until(lambda: native.native_job_status(cancelled)["state"] == "cancelled", 10)
        assert len(doc.Objects) == 2 and field.ViewObject.Visibility and box.ViewObject.Visibility

        select_operands(field, box)
        task = ImplicitMixed.selected()
        task.accept()
        stale = task.job
        task.tolerance.setValue(.099999)
        until(lambda: task.job is None)
        assert len(doc.Objects) == 2 and "settings changed" in task.status.text()
        until(lambda: native.native_job_status(stale)["state"] == "cancelled", 10)
        task.tolerance.setValue(.1)
        task.accept()
        dirty = task.job
        field.Period = 9
        until(lambda: task.job is None)
        assert len(doc.Objects) == 2 and task.result is None
        until(lambda: native.native_job_status(dirty)["state"] == "cancelled", 10)
        field.Period = 10
        doc.recompute()
        task.accept()
        foreign_job = task.job
        doc.openTransaction("Foreign creation-time label edit")
        box.Label = "Foreign box label"
        foreign = App.getActiveTransaction()
        until(lambda: task.job is None)
        assert App.getActiveTransaction() == foreign and len(doc.Objects) == 2
        assert task.reject() and App.getActiveTransaction() == foreign
        until(lambda: native.native_job_status(foreign_job)["state"] == "cancelled", 10)
        doc.abortTransaction()

        # Actual workbench command opens the same staged creation path.
        opened = []
        open_task = ImplicitMixedCreate.open_task
        def observed(*args):
            current = open_task(*args)
            opened.append(current)
            return current
        ImplicitMixedCreate.open_task = observed
        try:
            select_operands(field, box)
            Gui.runCommand("Implicit_OCCTMixedCommon")
        finally:
            ImplicitMixedCreate.open_task = open_task
        task = opened[0]
        assert task.policy.currentText() == "Regularized" and task.tolerance.value() == .1
        task.policy.setCurrentText("Reject")
        task.accept()
        until(lambda: task.job is None)
        assert not task.closed and task.result is None and len(doc.Objects) == 2
        assert "Creation failed" in task.status.text()
        task.policy.setCurrentText("Regularized")
        task.accept()
        # Rendering may add transient mesh data to the original operand while
        # the source job holds its immutable pre-render B-Rep record.
        box.Shape.tessellate(.5)
        assert until(lambda: task.job is None) > 0
        source = task.result
        assert task.closed and source is not None, task.status.text()
        assert source.BackgroundRecompute and source.Geometry is not None and source.SeamBoundVerified
        assert not field.ViewObject.Visibility and not box.ViewObject.Visibility
        source_name = source.Name
        doc.undo(); doc.recompute()
        assert doc.getObject(source_name) is None
        assert field.ViewObject.Visibility and box.ViewObject.Visibility
        doc.redo(); doc.recompute()
        source = doc.getObject(source_name)
        assert source.BackgroundRecompute and source.Geometry is not None
        assert not field.ViewObject.Visibility and not box.ViewObject.Visibility

        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(source)
        solid_task = ImplicitSolid.selected()
        assert not solid_task.accept()
        assert until(lambda: solid_task.job is None) > 10
        owner = solid_task.result
        assert solid_task.closed and owner is not None, solid_task.status.text()
        assert owner.BackgroundRecompute and source.BackgroundRecompute
        assert owner.SolidValidated and owner.Geometry is not None

        doc.openTransaction("Default GUI source edit")
        source.Operation = "BoxMinusField"
        assert doc.recompute()
        doc.commitTransaction()
        assert source.Geometry is None and owner.Geometry is None and not owner.SolidValidated
        assert until(lambda: source.Proxy._recompute_request is None
                     and owner.Proxy._recompute_request is None) > 10
        assert source.Geometry is not None and owner.SolidValidated, owner.BackendStatus

        with tempfile.TemporaryDirectory(prefix="implicit-defaults-") as directory:
            filename = os.path.join(directory, "defaults.FCStd")
            doc.saveCopy(filename)
            loaded = App.openDocument(filename)
            saved_source, saved_owner = loaded.getObject(source.Name), loaded.getObject(owner.Name)
            loaded.recompute()
            assert saved_source.BackgroundRecompute and saved_owner.BackgroundRecompute
            assert saved_source.Geometry is not None and saved_owner.Geometry is not None
            assert not saved_source.SeamBoundVerified and not saved_owner.SolidValidated
            assert saved_source.Proxy._recompute_request is None and saved_owner.Proxy._recompute_request is None
            App.closeDocument(loaded.Name)
            App.setActiveDocument(doc.Name)

        select_operands(field, box)
        task = ImplicitMixed.selected()
        task.accept()
        closing = task.job
        App.closeDocument(doc.Name)
        until(lambda: native.native_job_status(closing)["state"] == "cancelled", 10)
        assert not Gui.Control.activeDialog() and task.result is None
    finally:
        native.mixed_box, native._mixed_box, native.build_mixed_solids = mixed, raw, build
        if "CreationDefaultsGUI" in App.listDocuments():
            App.closeDocument("CreationDefaultsGUI")
    print("native implicit GUI creation defaults smoke test passed", flush=True)


try:
    main()
except BaseException:
    traceback.print_exc()
    os._exit(1)
finally:
    Gui.getMainWindow().close()
