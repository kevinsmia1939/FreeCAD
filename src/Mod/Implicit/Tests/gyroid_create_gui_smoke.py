# SPDX-License-Identifier: LGPL-2.1-or-later
"""Default toolbar native gyroid staging and four-owner transaction."""
import os
import time
import traceback
import tempfile
import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore
import ImplicitPartBoolean as bridge
import ImplicitOCCT as native
import ImplicitSolid


def pulse():
    loop = QtCore.QEventLoop()
    QtCore.QTimer.singleShot(20, loop.quit)
    loop.exec()


def finish(task):
    deadline = time.monotonic() + 180
    while task.job is not None:
        assert time.monotonic() < deadline, task.status.text()
        pulse()


def main():
    def forbidden(*_args, **_kwargs):
        raise AssertionError("Native gyroid workflow used synchronous geometry construction")
    native.mixed_box = native._mixed_box = native.build_mixed_solids = forbidden
    Gui.activateWorkbench("ImplicitModelingWorkbench")
    doc = App.newDocument("NativeGyroidCreationGUI")
    doc.UndoMode = 1
    Gui.runCommand("Implicit_NativeGyroid")
    task = bridge.current_task()
    assert task is not None and not doc.Objects
    assert App.getActiveTransaction() is None
    task.accept()
    assert task.job is not None and not doc.Objects
    task.reject()
    assert not doc.Objects and App.getActiveTransaction() is None
    for _ in range(20):
        pulse()
    Gui.runCommand("Implicit_NativeGyroid")
    task = bridge.current_task()
    task.controls["MaximumCells"].setValue(1)
    task.accept()
    finish(task)
    assert not task.closed and not doc.Objects, task.status.text()
    assert "failed" in task.status.text() and App.getActiveTransaction() is None
    task.controls["MaximumCells"].setValue(4000000)
    publish = ImplicitSolid.NativeSolid.publish
    def fail_publication(*_args, **_kwargs):
        raise RuntimeError("injected solid publication failure")
    ImplicitSolid.NativeSolid.publish = fail_publication
    try:
        task.accept()
        finish(task)
        assert not task.closed and not doc.Objects, task.status.text()
        assert "injected" in task.status.text() and App.getActiveTransaction() is None
        assert task.field is None and task.box is None
    finally:
        ImplicitSolid.NativeSolid.publish = publish
    task.accept()
    finish(task)
    assert task.closed and task.result is not None, task.status.text()
    assert len(doc.Objects) == 4
    solid, source, field, box = task.result, task.source, task.field, task.box
    assert solid.SolidValidated and solid.isValid() and source.isValid()
    assert solid.Label == "Gyroid solid" and not hasattr(solid, "Shape")
    assert field.Period.Value == 10 and field.Length.Value == 10
    assert source.Field == field and source.Box == box and solid.Source == source
    assert not field.ViewObject.Visibility and not box.ViewObject.Visibility
    assert "Length" in dict(box.ExpressionEngine)
    doc.undo()
    assert not doc.Objects
    doc.redo()
    assert len(doc.Objects) == 4
    field, source, solid, box = (doc.getObject(name) for name in
                                ("Gyroid", "NativeMixedBoundary", "NativeSolid", "GyroidDomain"))
    previous = native.dumps_mixed_solids(solid.Geometry)
    doc.openTransaction("Resize native gyroid")
    field.Period = 20
    field.Length = field.Width = field.Height = 20
    doc.recompute()
    doc.commitTransaction()
    deadline = time.monotonic() + 180
    while source.Proxy._recompute_request is not None or solid.Proxy._recompute_request is not None:
        assert time.monotonic() < deadline
        pulse()
    assert source.isValid() and solid.isValid() and solid.SolidValidated, (
        source.State, source.BackendStatus, solid.State, solid.BackendStatus,
        source.ViewObject.BuildFeedback, solid.ViewObject.BuildFeedback)
    assert box.Length.Value == 20 and field.DomainMax.x == 20
    assert native.dumps_mixed_solids(solid.Geometry) != previous
    record = native.dumps_mixed_solids(solid.Geometry)
    with tempfile.TemporaryDirectory() as directory:
        path = os.path.join(directory, "NativeGyroid.FCStd")
        doc.saveAs(path)
        App.closeDocument(doc.Name)
        restored = App.openDocument(path)
        solid = restored.getObject("NativeSolid")
        assert native.dumps_mixed_solids(solid.Geometry) == record
        assert not solid.SolidValidated
        assert restored.getObject("GyroidDomain").Length.Value == 20
        App.closeDocument(restored.Name)
    closing = App.newDocument("ClosingNativeGyroid")
    Gui.runCommand("Implicit_NativeGyroid")
    task = bridge.current_task()
    task.accept()
    assert task.job is not None and not closing.Objects
    App.closeDocument(closing.Name)
    assert task.closed and task.job is None and not Gui.Control.activeDialog()
    print("native gyroid creation GUI smoke test passed", flush=True)


try:
    main()
except BaseException:
    traceback.print_exc()
    os._exit(1)
finally:
    Gui.getMainWindow().close()
