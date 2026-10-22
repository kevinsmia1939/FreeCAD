# SPDX-License-Identifier: LGPL-2.1-or-later
"""Real task parameter controls, shared native results and persistence."""
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
    assert task.source_edits is not None and len(task.parameters) == 5
    return task


def click(button):
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
    assert len(boxes) == 1, "Task buttons are not fully visible"
    boxes[0].button(button).click()
    Gui.updateGui()
    deadline = time.monotonic() + 120
    while App.ActiveDocument is not None and any(
            getattr(getattr(getattr(item.ViewObject, "Proxy", None), "_task", None), "batch", None) is not None
            for item in App.ActiveDocument.Objects):
        assert time.monotonic() < deadline, "Background shared-input edit did not finish"
        loop = QtCore.QEventLoop()
        QtCore.QTimer.singleShot(20, loop.quit)
        loop.exec()


def main():
    Gui.activateWorkbench("ImplicitModelingWorkbench")
    doc = App.newDocument("NativeSourceParametersGUI")
    doc.UndoMode = 1
    field = doc.addObject("Implicit::Feature", "Gyroid")
    field.Function, field.Period = "Gyroid", 10
    field.DomainMin = (0, 0, 0)
    for name, axis in zip(("Length", "Width", "Height"), "xyz"):
        field.addProperty("App::PropertyLength", name)
        setattr(field, name, 10)
        field.setExpression("DomainMax." + axis, "DomainMin." + axis + " + " + name + " / (1 mm)")
    box = doc.addObject("Part::Box", "Box")
    box.Length = box.Width = box.Height = 10
    doc.recompute()
    source = ImplicitMixed.create(field, box, corner_policy="Regularized")
    obj, peer = ImplicitSolid.create(source), ImplicitSolid.create(source)
    # An untouched six-decimal widget must not truncate an authoritative double.
    obj.GeometricTolerance = .10000000001
    doc.recompute()
    expressions = field.ExpressionEngine
    for hidden in (field, box, source, peer):
        hidden.ViewObject.Visibility = False
    Gui.activeDocument().activeView().viewAxonometric()
    Gui.activeDocument().activeView().fitAll()
    task = edit(obj)
    assert task.fit_domain.isChecked()
    for name in ("Period", "Length", "Width", "Height"):
        task.parameters[name].setValue(5)
    assert field.Period.Value == 10 and box.Length.Value == 10
    click(QtWidgets.QDialogButtonBox.Apply)
    assert "Preview failed:" not in task.status.text(), task.status.text()
    assert field.Period.Value == 5 and tuple(field.DomainMax) == (5, 5, 5)
    assert field.ExpressionEngine == expressions
    assert obj.SolidValidated and peer.SolidValidated
    assert obj.GeometricTolerance.Value == .10000000001
    assert obj.ViewObject.Proxy._mesh and "NativeFace1" in obj.ViewObject.Proxy._elements
    target = task.parameters["Period"]
    scrolls = []
    ancestor = target.parentWidget()
    while ancestor is not None:
        if isinstance(ancestor, QtWidgets.QScrollArea):
            scrolls.append(ancestor)
        ancestor = ancestor.parentWidget()
    assert scrolls
    # Qt ensureWidgetVisible uses a spin box's input-method cursor rectangle,
    # which can be visible while the control frame is clipped. Scroll the full
    # control rectangle, then check viewport containment after layout settles.
    for _ in range(20):
        for scroll in scrolls:
            center = target.mapTo(scroll.widget(), target.rect().center())
            scroll.ensureVisible(center.x(), center.y(),
                                 target.width() // 2 + 8, target.height() // 2 + 8)
        loop = QtCore.QEventLoop()
        QtCore.QTimer.singleShot(100, loop.quit)
        loop.exec()
        Gui.updateGui()
        if all(scroll.viewport().rect().contains(QtCore.QRect(
                target.mapTo(scroll.viewport(), QtCore.QPoint()), target.size())) for scroll in scrolls):
            break
    visible = all(scroll.viewport().rect().contains(QtCore.QRect(
        target.mapTo(scroll.viewport(), QtCore.QPoint()), target.size())) for scroll in scrolls)
    if not visible:
        Gui.getMainWindow().grab().save("/tmp/implicit-source-parameters-clipped.png")
    assert visible, [(scroll.metaObject().className(), scroll.objectName(),
                     scroll.viewport().rect(), target.mapTo(scroll.viewport(), QtCore.QPoint()),
                     target.size(), scroll.verticalScrollBar().value(),
                     scroll.verticalScrollBar().maximum()) for scroll in scrolls]
    assert target.visibleRegion().contains(target.rect())
    Gui.getMainWindow().grab().save("/tmp/implicit-source-parameters-editor.png")
    click(QtWidgets.QDialogButtonBox.Ok)
    assert not Gui.Control.activeDialog()
    doc.undo(); doc.recompute()
    assert field.Period.Value == 10 and obj.SolidValidated and peer.SolidValidated
    doc.redo(); doc.recompute()
    assert field.Period.Value == 5 and obj.SolidValidated and peer.SolidValidated
    record = native.dumps_mixed_solids(obj.Geometry)
    task = edit(obj)
    task.parameters["IsoValue"].setValue(1.5)
    click(QtWidgets.QDialogButtonBox.Apply)
    assert "Preview failed:" in task.status.text()
    for result in (obj, peer):
        assert result.Geometry is None and not result.SolidValidated
        assert result.ViewObject.Proxy._mesh is None and not result.ViewObject.Proxy._elements
    assert not task.accept() and Gui.Control.activeDialog()
    task.parameters["IsoValue"].setValue(0)
    assert task.apply(), task.status.text()
    assert obj.SolidValidated and peer.SolidValidated
    click(QtWidgets.QDialogButtonBox.Cancel)
    assert native.dumps_mixed_solids(obj.Geometry) == record and field.IsoValue == 0
    assert field.ExpressionEngine == expressions
    names = obj.Name, field.Name
    build = native.build_mixed_solids
    def forbidden(*_args):
        raise AssertionError("unchanged loaded parameter editor rebuilt native solids")
    native.build_mixed_solids = forbidden
    try:
        with tempfile.TemporaryDirectory(prefix="implicit-source-task-") as directory:
            filename = os.path.join(directory, "parameters.FCStd")
            doc.saveAs(filename)
            App.closeDocument(doc.Name)
            doc = App.openDocument(filename)
            doc.recompute()
            obj, field = (doc.getObject(name) for name in names)
            assert field.ExpressionEngine == expressions and field.Period.Value == 5
            assert not obj.SolidValidated and native.dumps_mixed_solids(obj.Geometry) == record
            task = edit(obj)
            assert task.apply(), task.status.text()
            assert obj.GeometricTolerance.Value == .10000000001
            assert task.reject()
            App.closeDocument(doc.Name)
    finally:
        native.build_mixed_solids = build
    assert not Gui.Control.activeDialog() and App.getActiveTransaction() is None
    print("native implicit source parameters GUI smoke test passed", flush=True)


try:
    main()
except BaseException:
    traceback.print_exc()
    os._exit(1)
finally:
    Gui.getMainWindow().close()
