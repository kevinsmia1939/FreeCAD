# SPDX-License-Identifier: LGPL-2.1-or-later
"""Creation settings precede geometry; failed builds are atomic and repairable."""
import os
import tempfile
import traceback
import time
import FreeCAD as App
import FreeCADGui as Gui
import ImplicitMixed
import ImplicitSolid
import ImplicitSolidCreate
import ImplicitOCCT as native
from PySide import QtCore, QtWidgets


def finish(task):
    deadline = time.monotonic() + 120
    pulses = 0
    while task.job is not None:
        assert time.monotonic() < deadline, task.status.text()
        loop = QtCore.QEventLoop()
        QtCore.QTimer.singleShot(20, loop.quit)
        loop.exec()
        pulses += 1
    return pulses


def cancelled(job):
    deadline = time.monotonic() + 10
    while native.solid_job_status(job)["state"] != "cancelled":
        assert time.monotonic() < deadline, native.solid_job_status(job)
        loop = QtCore.QEventLoop()
        QtCore.QTimer.singleShot(10, loop.quit)
        loop.exec()


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
    assert len(boxes) == 1, "Creation buttons are not fully visible"
    boxes[0].button(button).click()
    Gui.updateGui()


def main():
    Gui.getMainWindow().showMaximized()
    Gui.activateWorkbench("ImplicitModelingWorkbench")
    doc = App.newDocument("NativeSolidCreationGUI")
    doc.UndoMode = 1
    field = doc.addObject("Implicit::Feature", "Gyroid")
    field.Function, field.Period, field.IsoValue = "Gyroid", 20, 0
    field.DomainMin, field.DomainMax = (-20, -20, 20), (0, 0, 40)
    box = doc.addObject("Part::Box", "Box")
    box.Length = box.Width = box.Height = 20
    box.Placement.Base = (-20, -20, 20)
    doc.recompute()
    source = ImplicitMixed.create(field, box, corner_policy="Regularized")
    field.ViewObject.Visibility = box.ViewObject.Visibility = False
    count = len(doc.Objects)
    source_record = native.dumps_mixed(source.Geometry)
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(source)
    build = native.build_mixed_solids
    def forbidden(*_args):
        raise AssertionError("staging/unchanged restoration rebuilt native solids")
    native.build_mixed_solids = forbidden
    try:
        # The actual menu command must open settings without running the kernel.
        Gui.runCommand("Implicit_NativeSolid")
        assert Gui.Control.activeDialog() and len(doc.Objects) == count
        assert App.getActiveTransaction() is None
        click(QtWidgets.QDialogButtonBox.Cancel)
        assert not Gui.Control.activeDialog() and source.ViewObject.Visibility
        assert len(doc.Objects) == count and App.getActiveTransaction() is None
        for limits in ({"Source": source}, {"MaximumDepth": 17},
                       {"MaximumCells": 1.5}, {"MaximumTests": True}):
            try:
                ImplicitSolid.create(source, build_limits=limits)
            except ValueError:
                pass
            else:
                raise AssertionError("invalid creation build limits were accepted")
            assert len(doc.Objects) == count and App.getActiveTransaction() is None
    finally:
        native.build_mixed_solids = build
    for candidate in (box, None):
        try:
            ImplicitSolidCreate.open_task(candidate)
        except ValueError:
            pass
        else:
            raise AssertionError("non-boundary source entered creation")
        assert not Gui.Control.activeDialog() and len(doc.Objects) == count
    doc.openTransaction("Unrelated user change")
    active = App.getActiveTransaction()
    try:
        ImplicitSolidCreate.open_task(source)
    except RuntimeError:
        pass
    else:
        raise AssertionError("creation adopted an unrelated transaction")
    assert App.getActiveTransaction() == active
    doc.abortTransaction()
    task = ImplicitSolidCreate.open_task(source)
    click(QtWidgets.QDialogButtonBox.Ok)
    job = task.job
    assert job is not None and len(doc.Objects) == count
    click(QtWidgets.QDialogButtonBox.Cancel)
    cancelled(job)
    assert not Gui.Control.activeDialog() and task.result is None
    assert len(doc.Objects) == count and source.ViewObject.Visibility

    task = ImplicitSolidCreate.open_task(source)
    click(QtWidgets.QDialogButtonBox.Ok)
    task.controls["MaximumGeometryDepth"].setValue(18)
    finish(task)
    assert "settings changed" in task.status.text() and task.result is None
    click(QtWidgets.QDialogButtonBox.Ok)
    doc.openTransaction("External edit during worker")
    active = App.getActiveTransaction()
    finish(task)
    assert App.getActiveTransaction() == active and task.result is None
    doc.abortTransaction()
    click(QtWidgets.QDialogButtonBox.Ok)
    field.IsoValue = .01
    finish(task)
    assert "inputs changed" in task.status.text() and task.result is None
    field.IsoValue = 0
    doc.recompute()
    click(QtWidgets.QDialogButtonBox.Cancel)
    assert len(doc.Objects) == count
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(source)
    task = ImplicitSolid.selected()
    assert task.form.objectName() == "ImplicitNativeSolidCreation"
    task.controls["MaximumGeometryDepth"].setValue(18)
    task.controls["MaximumGeometryCells"].setValue(1)
    target = task.controls["MaximumGeometryDepth"]
    scrolls = []
    ancestor = target.parentWidget()
    while ancestor is not None:
        if isinstance(ancestor, QtWidgets.QScrollArea):
            scrolls.append(ancestor)
        ancestor = ancestor.parentWidget()
    assert scrolls
    for _ in range(20):
        for scroll in scrolls:
            center = target.mapTo(scroll.widget(), target.rect().center())
            scroll.ensureVisible(center.x(), center.y(),
                                 target.width() // 2 + 8, target.height() // 2 + 8)
        loop = QtCore.QEventLoop()
        QtCore.QTimer.singleShot(100, loop.quit)
        loop.exec()
        if all(scroll.viewport().rect().contains(QtCore.QRect(
                target.mapTo(scroll.viewport(), QtCore.QPoint()), target.size())) for scroll in scrolls):
            break
    assert all(scroll.viewport().rect().contains(QtCore.QRect(
        target.mapTo(scroll.viewport(), QtCore.QPoint()), target.size())) for scroll in scrolls)
    Gui.getMainWindow().grab().save("/tmp/implicit-solid-creation-settings.png")
    click(QtWidgets.QDialogButtonBox.Ok)
    finish(task)
    assert not task.closed and task.result is None and Gui.Control.activeDialog()
    assert "Build failed:" in task.status.text()
    assert len(doc.Objects) == count and App.getActiveTransaction() is None
    assert source.ViewObject.Visibility and native.dumps_mixed(source.Geometry) == source_record
    task.controls["MaximumGeometryCells"].setValue(2000000)
    extract = native.tessellate_mixed
    native.build_mixed_solids = native.tessellate_mixed = forbidden
    try:
        click(QtWidgets.QDialogButtonBox.Ok)
        assert finish(task) > 10, "GUI event loop did not run during construction"
    finally:
        native.build_mixed_solids, native.tessellate_mixed = build, extract
    obj = task.result
    assert task.closed and not Gui.Control.activeDialog()
    assert obj is not None and obj.SolidValidated and obj.Geometry is not None
    assert obj.MaximumGeometryDepth == 18 and obj.MaximumDepth == 16
    assert obj.MaximumGeometryCells == 2000000 and obj.GeometricTolerance.Value == .1
    assert native.inspect_mixed_solids(obj.Geometry)["geometry"]["boundary_bound"] <= .1
    assert len(doc.Objects) == count + 1 and not source.ViewObject.Visibility
    assert Gui.Selection.getSelection() == [obj] and App.getActiveTransaction() is None
    assert obj.ViewObject.Proxy._mesh, obj.ViewObject.SurfacePreviewStatus
    assert "NativeFace1" in obj.ViewObject.Proxy._elements
    Gui.activeDocument().activeView().viewAxonometric()
    # Fit an expanded box so the report dock leaves an inspection margin.
    Gui.activeDocument().activeView().fitAll(1.5)
    # Let the animated camera fit finish before capturing the resulting model.
    loop = QtCore.QEventLoop()
    QtCore.QTimer.singleShot(500, loop.quit)
    loop.exec()
    Gui.updateGui()
    Gui.getMainWindow().grab().save("/tmp/implicit-solid-created.png")
    name, source_name = obj.Name, source.Name
    record = native.dumps_mixed_solids(obj.Geometry)
    native.build_mixed_solids = forbidden
    try:
        doc.undo(); doc.recompute()
        assert doc.getObject(name) is None and source.ViewObject.Visibility
        doc.redo(); doc.recompute()
        obj = doc.getObject(name)
        assert obj is not None and native.dumps_mixed_solids(obj.Geometry) == record
        assert obj.MaximumGeometryDepth == 18 and not source.ViewObject.Visibility
        with tempfile.TemporaryDirectory(prefix="implicit-solid-create-") as directory:
            filename = os.path.join(directory, "created.FCStd")
            doc.saveAs(filename)
            App.closeDocument(doc.Name)
            doc = App.openDocument(filename)
            doc.recompute()
            obj, source = doc.getObject(name), doc.getObject(source_name)
            assert obj.MaximumGeometryDepth == 18 and obj.GeometricTolerance.Value == .1
            assert native.dumps_mixed_solids(obj.Geometry) == record and not obj.SolidValidated
            assert not source.ViewObject.Visibility and obj.ViewObject.Proxy._mesh
            # Closing the source document while staging creates no orphan result.
            closing = ImplicitSolidCreate.open_task(source)
            click(QtWidgets.QDialogButtonBox.Ok)
            job = closing.job
            assert job is not None
            App.closeDocument(doc.Name)
            cancelled(job)
            assert not Gui.Control.activeDialog() and App.getActiveTransaction() is None
    finally:
        native.build_mixed_solids = build
    print("native implicit solid creation GUI smoke test passed", flush=True)


try:
    main()
except BaseException:
    traceback.print_exc()
    os._exit(1)
finally:
    Gui.getMainWindow().close()
