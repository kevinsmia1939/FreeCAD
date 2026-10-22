# SPDX-License-Identifier: LGPL-2.1-or-later
"""Actual event-loop progress, multi-owner preview and in-flight rollback."""
import os
import time
import traceback
import FreeCAD as App
import FreeCADGui as Gui
import ImplicitMixed
import ImplicitSolid
import ImplicitSolidBatch
import ImplicitOCCT as native
from PySide import QtCore, QtWidgets


def pulse():
    loop = QtCore.QEventLoop()
    QtCore.QTimer.singleShot(20, loop.quit)
    loop.exec()


def finish(task):
    deadline = time.monotonic() + 120
    ticks = 0
    while task.batch is not None:
        assert time.monotonic() < deadline, task.status.text()
        pulse()
        ticks += 1
    return ticks


def edit(obj):
    assert Gui.getDocument(obj.Document.Name).setEdit(obj.Name)
    return obj.ViewObject.Proxy._task


def main():
    Gui.activateWorkbench("ImplicitModelingWorkbench")
    doc = App.newDocument("NativeBatchGUI")
    doc.UndoMode = 1
    field = doc.addObject("Implicit::Feature", "Gyroid")
    field.Function, field.Period, field.IsoValue = "Gyroid", 10, 0
    field.DomainMin, field.DomainMax = (0, 0, 0), (10, 10, 10)
    box = doc.addObject("Part::Box", "Box")
    box.Length = box.Width = box.Height = 10
    doc.recompute()
    source = ImplicitMixed.create(field, box, corner_policy="Regularized")
    owners = [ImplicitSolid.create(source), ImplicitSolid.create(source)]
    for item in (field, box, source):
        item.ViewObject.Visibility = False
    originals = [native.dumps_mixed_solids(obj.Geometry) for obj in owners]
    build, mesh = native.build_mixed_solids, native.tessellate_mixed

    def forbidden(*_args):
        raise AssertionError("background preview used synchronous construction/extraction")

    task = edit(owners[0])
    task.operation.setCurrentText("BoxMinusField")
    native.build_mixed_solids = native.tessellate_mixed = forbidden
    try:
        task.clicked(QtWidgets.QDialogButtonBox.Apply)
        assert task.batch is not None, task.status.text()
        assert all(obj.Geometry is None for obj in owners)
        doc.recompute()  # Must not bypass the pending native jobs.
        assert finish(task) > 10
        assert all(obj.SolidValidated and obj.ViewObject.Proxy._mesh for obj in owners)
    finally:
        native.build_mixed_solids, native.tessellate_mixed = build, mesh
    assert task.reject()
    assert [native.dumps_mixed_solids(obj.Geometry) for obj in owners] == originals

    # A preflight failure after applying settings must clear old validity too.
    task = edit(owners[0])
    task.controls["MaximumGeometryDepth"].setValue(18)
    signature = ImplicitSolidBatch.source_signature
    def unavailable_source(_source):
        raise ValueError("Injected stale source preflight")
    ImplicitSolidBatch.source_signature = unavailable_source
    try:
        task.clicked(QtWidgets.QDialogButtonBox.Apply)
        assert task.batch is None and "stale source" in task.status.text()
        assert owners[0].Geometry is None and not owners[0].SolidValidated
    finally:
        ImplicitSolidBatch.source_signature = signature
    assert task.reject()

    # Cancel while the native worker still owns the private input snapshot.
    task = edit(owners[0])
    task.operation.setCurrentText("BoxMinusField")
    task.clicked(QtWidgets.QDialogButtonBox.Apply)
    assert task.batch is not None
    batch = task.batch
    assert task.reject()
    assert batch.state == "cancelled" and not Gui.Control.activeDialog()
    assert [native.dumps_mixed_solids(obj.Geometry) for obj in owners] == originals

    task = edit(owners[0])
    task.operation.setCurrentText("BoxMinusField")
    task.clicked(QtWidgets.QDialogButtonBox.Apply)
    assert task.batch is not None
    task.controls["MaximumGeometryDepth"].setValue(18)
    finish(task)
    assert "settings changed" in task.status.text()
    assert all(obj.Geometry is None for obj in owners)
    assert task.reject()

    task = edit(owners[0])
    task.operation.setCurrentText("BoxMinusField")
    assert not task.accept() and task.batch is not None
    finish(task)
    assert task.closed and not Gui.Control.activeDialog()
    assert all(obj.SolidValidated for obj in owners)
    doc.undo(); doc.recompute()
    assert str(source.Operation) == "Common"
    doc.redo(); doc.recompute()
    assert str(source.Operation) == "BoxMinusField"
    task = edit(owners[0])
    task.operation.setCurrentText("Common")
    task.clicked(QtWidgets.QDialogButtonBox.Apply)
    batch = task.batch
    assert batch is not None
    App.closeDocument(doc.Name)
    assert batch.state == "cancelled"
    assert not Gui.Control.activeDialog() and App.getActiveTransaction() is None
    print("native implicit solid batch GUI smoke test passed", flush=True)


try:
    main()
except BaseException:
    traceback.print_exc()
    os._exit(1)
finally:
    Gui.getMainWindow().close()
