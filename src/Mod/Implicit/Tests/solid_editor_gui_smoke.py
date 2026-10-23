# SPDX-License-Identifier: LGPL-2.1-or-later
"""Native solid task UI, shared-source edits, undo/redo and failure recovery."""
import os
import tempfile
import traceback
import time
import FreeCAD as App
import FreeCADGui as Gui
import ImplicitMixed
import ImplicitSolid
import ImplicitOCCT as native
from PySide import QtCore, QtWidgets


def edit(obj):
    assert Gui.getDocument(obj.Document.Name).setEdit(obj.Name)
    task = obj.ViewObject.Proxy._task
    assert task.form.objectName() == "ImplicitNativeSolidEditor" and Gui.Control.activeDialog()
    return task


def click(button, press=True):
    # Task overlays expand asynchronously. Wait for actual visible controls,
    # rather than invoking hidden buttons or assuming one processEvents is enough.
    for _ in range(40):
        Gui.updateGui()
        boxes = [box for box in Gui.getMainWindow().findChildren(QtWidgets.QDialogButtonBox)
                 if box.isVisible() and box.button(button) is not None
                 and all(Gui.getMainWindow().rect().contains(QtCore.QRect(
                     child.mapTo(Gui.getMainWindow(), QtCore.QPoint()), child.size()))
                         and child.visibleRegion().contains(child.rect())
                         for child in box.buttons())]
        if len(boxes) == 1:
            break
        loop = QtCore.QEventLoop()
        QtCore.QTimer.singleShot(50, loop.quit)
        loop.exec()
    ancestry = []
    if len(boxes) != 1:
        Gui.getMainWindow().grab().save("/tmp/implicit-solid-editor-button-failure.png")
        for box in Gui.getMainWindow().findChildren(QtWidgets.QDialogButtonBox):
            chain = []
            widget = box
            while widget is not None:
                chain.append((widget.metaObject().className(), widget.objectName(),
                              widget.isVisible(), widget.isHidden()))
                widget = widget.parentWidget()
            ancestry.append(chain)
    assert len(boxes) == 1, ancestry
    if press:
        boxes[0].button(button).click()
    Gui.updateGui()
    deadline = time.monotonic() + 120
    while App.ActiveDocument is not None and any(
            getattr(getattr(getattr(item.ViewObject, "Proxy", None), "_task", None), "batch", None) is not None
            for item in App.ActiveDocument.Objects):
        assert time.monotonic() < deadline, "Background edit did not finish"
        loop = QtCore.QEventLoop()
        QtCore.QTimer.singleShot(20, loop.quit)
        loop.exec()


def check(obj, operation, depth):
    wait_display(obj)
    assert str(obj.Source.Operation) == operation and obj.MaximumGeometryDepth == depth
    assert obj.GeometricTolerance.Value == .1
    assert obj.Geometry is not None and obj.isValid(), obj.BackendStatus
    assert obj.ViewObject.Proxy._mesh, obj.ViewObject.SurfacePreviewStatus
    assert "NativeFace1" in obj.ViewObject.Proxy._elements


def wait_display(obj):
    deadline = time.monotonic() + 90
    while obj.ViewObject.Proxy._display_pending:
        assert time.monotonic() < deadline, obj.ViewObject.SurfacePreviewStatus
        loop = QtCore.QEventLoop()
        QtCore.QTimer.singleShot(20, loop.quit)
        loop.exec()


def main():
    Gui.activateWorkbench("ImplicitModelingWorkbench")
    doc = App.newDocument("NativeSolidEditorGUI")
    doc.UndoMode = 1
    field = doc.addObject("Implicit::Feature", "Gyroid")
    field.Function, field.Period, field.IsoValue = "Gyroid", 10, 0
    field.DomainMin, field.DomainMax = (0, 0, 0), (10, 10, 10)
    box = doc.addObject("Part::Box", "Box")
    box.Length = box.Width = box.Height = 10
    doc.recompute()
    source = ImplicitMixed.create(field, box, corner_policy="Regularized")
    obj = ImplicitSolid.create(source)
    field.ViewObject.Visibility = box.ViewObject.Visibility = source.ViewObject.Visibility = False
    Gui.activeDocument().activeView().viewAxonometric()
    Gui.activeDocument().activeView().fitAll()
    # Low-level stored boundary owners need no recipe proxy. Their operation
    # must not appear editable or be mislabelled as Common.
    static = doc.addObject("Implicit::NativeFeaturePython", "StoredBoundary")
    static.Geometry = source.Geometry
    stored_solid = ImplicitSolid.create(static)
    stored_solid.ViewObject.Visibility = static.ViewObject.Visibility = False
    stored_task = edit(stored_solid)
    assert not stored_task.edit_operation and not stored_task.operation.isEnabled()
    assert stored_task.operation.currentText() == "Stored source (read-only)"
    assert stored_task.reject()
    doc.removeObject(stored_solid.Name)
    doc.removeObject(static.Name)
    original = native.dumps_mixed_solids(obj.Geometry)
    task = edit(obj)
    task.operation.setCurrentText("BoxMinusField")
    task.controls["MaximumGeometryDepth"].setValue(18)
    assert str(source.Operation) == "Common" and obj.MaximumGeometryDepth == -1
    click(QtWidgets.QDialogButtonBox.Apply)
    check(obj, "BoxMinusField", 18)
    target = task.controls["MaximumGeometryDepth"]
    ancestor = target.parentWidget()
    while ancestor is not None:
        if isinstance(ancestor, QtWidgets.QScrollArea):
            ancestor.ensureWidgetVisible(target, 0, 2)
        ancestor = ancestor.parentWidget()
    click(QtWidgets.QDialogButtonBox.Apply, press=False)
    assert target.visibleRegion().contains(target.rect())
    Gui.getMainWindow().grab().save("/tmp/implicit-solid-editor.png")
    assert App.getActiveTransaction()[1] == task.transaction
    click(QtWidgets.QDialogButtonBox.Cancel)
    check(obj, "Common", -1)
    assert native.dumps_mixed_solids(obj.Geometry) == original
    task = edit(obj)
    task.operation.setCurrentText("BoxMinusField")
    task.controls["MaximumGeometryDepth"].setValue(18)
    click(QtWidgets.QDialogButtonBox.Ok)
    check(obj, "BoxMinusField", 18)
    doc.undo(); doc.recompute(); check(obj, "Common", -1)
    doc.redo(); doc.recompute(); check(obj, "BoxMinusField", 18)
    task = edit(obj)
    task.controls["MaximumGeometryCells"].setValue(1)
    click(QtWidgets.QDialogButtonBox.Apply)
    assert "Preview failed:" in task.status.text()
    assert obj.Geometry is None and obj.ViewObject.Proxy._mesh is None
    assert not obj.ViewObject.Proxy._elements and not obj.ViewObject.DisplayProximityChecked
    assert not task.accept() and Gui.Control.activeDialog()
    task.controls["MaximumGeometryCells"].setValue(2000000)
    assert task.apply(), task.status.text()
    check(obj, "BoxMinusField", 18)
    assert task.reject()
    # ResetEdit is also a rollback, and unrelated transactions are never adopted.
    task = edit(obj)
    task.operation.setCurrentText("Common")
    assert task.apply(), task.status.text()
    Gui.getDocument(doc.Name).resetEdit()
    check(obj, "BoxMinusField", 18)
    doc.openTransaction("Unrelated label edit")
    obj.Label = "Unrelated user label"
    active = App.getActiveTransaction()
    assert not obj.ViewObject.Proxy.doubleClicked(obj.ViewObject)
    assert App.getActiveTransaction() == active
    doc.abortTransaction()
    task = edit(obj)
    doc.openTransaction("Unrelated edit during task")
    obj.Label = "Another external label"
    active = App.getActiveTransaction()
    assert not task.apply() and not task.reject()
    assert App.getActiveTransaction() == active
    doc.abortTransaction()
    assert task.reject()
    # A real failed solid build must invalidate previously checked display state.
    obj.ViewObject.CheckSurfaceDisplay = True
    wait_display(obj)
    assert obj.ViewObject.DisplayProximityChecked
    task = edit(obj)
    task.controls["MaximumGeometryCells"].setValue(1)
    assert not task.apply()
    assert not obj.ViewObject.DisplayProximityChecked and obj.ViewObject.Proxy._mesh is None
    assert task.reject()
    wait_display(obj)
    assert obj.ViewObject.DisplayProximityChecked
    name = obj.Name
    record = native.dumps_mixed_solids(obj.Geometry)
    build = native.build_mixed_solids
    def forbidden(*_args):
        raise AssertionError("unchanged accepted task restore rebuilt native solids")
    native.build_mixed_solids = forbidden
    try:
        with tempfile.TemporaryDirectory(prefix="implicit-solid-task-") as directory:
            filename = os.path.join(directory, "edited.FCStd")
            doc.saveAs(filename)
            App.closeDocument(doc.Name)
            doc = App.openDocument(filename)
            doc.recompute()
            obj = doc.getObject(name)
            check(obj, "BoxMinusField", 18)
            assert not obj.SolidValidated and obj.ViewObject.DisplayProximityChecked
            assert native.dumps_mixed_solids(obj.Geometry) == record
            task = edit(obj)
            assert task.apply(), task.status.text()  # Unchanged loaded settings do not revalidate.
            App.closeDocument(doc.Name)
            assert App.getActiveTransaction() is None
    finally:
        native.build_mixed_solids = build
    assert not Gui.Control.activeDialog()
    print("native implicit solid editor GUI smoke test passed", flush=True)


try:
    main()
except BaseException:
    traceback.print_exc()
    os._exit(1)
finally:
    Gui.getMainWindow().close()
