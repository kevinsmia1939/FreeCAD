# SPDX-License-Identifier: LGPL-2.1-or-later
"""Native mixed task editor: preview, cancel, undo/redo and failure recovery."""
import os
import tempfile
import traceback
import time
import FreeCAD as App
import FreeCADGui as Gui
import Implicit
import ImplicitMixed


def edit(obj):
    gui = Gui.getDocument(obj.Document.Name)
    assert gui.setEdit(obj.Name)
    task = obj.ViewObject.Proxy._task
    assert task is not None and Gui.Control.activeDialog(gui)
    assert task.form.objectName() == "ImplicitMixedBoundaryEditor"
    return task


def state(obj, operation, tolerance):
    assert str(obj.Operation) == operation
    assert abs(obj.GeometricTolerance.Value - tolerance) < 1e-12
    assert obj.isValid() and obj.Geometry is not None, obj.BackendStatus
    assert obj.ViewObject.Proxy._coordinates.point.getNum() > 0
    query = Implicit.classifyNative(obj.getSubObject(""), (0, 0, 2))
    assert query["state"] == ("inside" if operation == "Common" else "outside")


def click(button):
    from PySide import QtCore, QtWidgets
    Gui.updateGui()
    boxes = [box for box in Gui.getMainWindow().findChildren(QtWidgets.QDialogButtonBox)
             if box.isVisible() and box.button(button) is not None]
    assert len(boxes) == 1, "missing or ambiguous task buttons"
    tasks = [getattr(getattr(item.ViewObject, "Proxy", None), "_task", None)
             for item in App.ActiveDocument.Objects]
    task = next(item for item in tasks if item is not None)
    boxes[0].button(button).click()
    Gui.updateGui()
    wait_task(task)


def wait_task(task):
    from PySide import QtCore
    deadline = time.monotonic() + 90
    while task.batch is not None:
        assert time.monotonic() < deadline, task.status.text()
        loop = QtCore.QEventLoop()
        QtCore.QTimer.singleShot(20, loop.quit)
        loop.exec()


def main():
    from PySide import QtWidgets
    Gui.activateWorkbench("NativeImplicitWorkbench")
    obj = ImplicitMixed.demo()
    doc = obj.Document
    doc.UndoMode = 1
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(obj)
    Gui.runCommand("Std_Edit", 0)
    menu_task = obj.ViewObject.Proxy._task
    assert menu_task is not None and Gui.Control.activeDialog()
    assert menu_task.accept(), menu_task.status.text()
    original = Implicit.nativeGeometry(obj).getElementName("Cap1", 1)
    task = edit(obj)
    task.operation.setCurrentText("BoxMinusField")
    assert str(obj.Operation) == "Common"  # staged controls are not model edits
    click(QtWidgets.QDialogButtonBox.Apply)
    state(obj, "BoxMinusField", .1)
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(obj, "Cap1")
    assert Gui.Selection.getSelectionEx()[0].SubObjects[0].getLines(.1)[0]
    preview = obj.getSubObject("")
    click(QtWidgets.QDialogButtonBox.Cancel)
    assert not Gui.Control.activeDialog()
    state(obj, "Common", .1)
    assert Implicit.nativeGeometry(obj).getElementName("Cap1", 1) == original
    assert Implicit.classifyNative(preview, (0, 0, 2))["state"] == "outside"
    task = edit(obj)
    task.operation.setCurrentText("BoxMinusField")
    click(QtWidgets.QDialogButtonBox.Apply)
    state(obj, "BoxMinusField", .1)
    assert App.getActiveTransaction()[1] == task.transaction
    task.tolerance.setValue(.08)
    click(QtWidgets.QDialogButtonBox.Ok)
    state(obj, "BoxMinusField", .08)
    doc.undo()
    doc.recompute()
    state(obj, "Common", .1)
    doc.redo()
    doc.recompute()
    state(obj, "BoxMinusField", .08)
    task = edit(obj)
    task.cells.setCurrentText("4")
    assert not task.apply()
    assert obj.Geometry is None and obj.Proxy._boundary is None
    assert not obj.ViewObject.Proxy._cap_nodes and not obj.ViewObject.Proxy._seam_nodes
    assert "Preview failed:" in task.status.text()
    assert not task.accept() and Gui.Control.activeDialog()
    assert task.reject()
    state(obj, "BoxMinusField", .08)
    task = edit(obj)
    task.cells.setCurrentText("4")
    assert not task.apply()
    task.cells.setCurrentText("512")
    assert task.apply()
    state(obj, "BoxMinusField", .08)
    task.reject()
    state(obj, "BoxMinusField", .08)
    # ResetEdit (instead of pressing Cancel) must also roll back its preview.
    task = edit(obj)
    task.operation.setCurrentText("Common")
    assert task.apply()
    Gui.getDocument(doc.Name).resetEdit()
    state(obj, "BoxMinusField", .08)
    # Never adopt/abort an unrelated transaction.
    doc.openTransaction("Unrelated label edit")
    obj.Label = "Label changed by another transaction"
    active = App.getActiveTransaction()
    assert not obj.ViewObject.Proxy.doubleClicked(obj.ViewObject)
    assert App.getActiveTransaction() == active
    doc.abortTransaction()
    task = edit(obj)
    doc.openTransaction("Unrelated edit while task is open")
    obj.Label = "Another external label edit"
    active = App.getActiveTransaction()
    task.operation.setCurrentText("Common")
    assert not task.apply()
    assert not task.reject() and Gui.Control.activeDialog()
    assert App.getActiveTransaction() == active
    doc.abortTransaction()
    assert task.reject()
    state(obj, "BoxMinusField", .08)
    with tempfile.TemporaryDirectory(prefix="implicit-editor-") as directory:
        filename = os.path.join(directory, "edited.FCStd")
        name = obj.Name
        doc.saveAs(filename)
        App.closeDocument(doc.Name)
        doc = App.openDocument(filename)
        obj = doc.getObject(name)
        state(obj, "BoxMinusField", .08)
        assert obj.ViewObject.Proxy.doubleClicked(obj.ViewObject)
        task = obj.ViewObject.Proxy._task
        assert task is not None and Gui.Control.activeDialog()
        task.operation.setCurrentText("Common")
        assert not task.accept() and task.batch is not None
        wait_task(task)
        assert task.closed and not Gui.Control.activeDialog()
        state(obj, "Common", .08)
        task = edit(obj)
        task.operation.setCurrentText("BoxMinusField")
        assert task.apply()
        retained = obj.getSubObject("")
        App.closeDocument(doc.Name)
        assert App.getActiveTransaction() is None
        assert Implicit.classifyNative(retained, (0, 0, 2))["state"] == "outside"
    assert not Gui.Control.activeDialog()
    crossing = ImplicitMixed.demo(open_contours=True)
    assert crossing.BoxEdgeRootCount > 4
    identity = Implicit.nativeGeometry(crossing).getElementName("Seam1", 1)
    task = edit(crossing)
    task.operation.setCurrentText("BoxMinusField")
    assert task.apply(), task.status.text()
    assert crossing.isValid() and crossing.Geometry is not None
    assert crossing.ViewObject.Proxy._cap_nodes and crossing.ViewObject.Proxy._seam_nodes
    assert Implicit.classifyNative(crossing.getSubObject(""), (0, 0, 0))["state"] == "near_boundary"
    assert task.reject()
    assert str(crossing.Operation) == "Common"
    assert Implicit.nativeGeometry(crossing).getElementName("Seam1", 1) == identity
    App.closeDocument(crossing.Document.Name)
    print("native implicit mixed editor GUI smoke test passed", flush=True)
    Gui.getMainWindow().close()


try:
    main()
except BaseException:
    traceback.print_exc()
    os._exit(1)
