# SPDX-License-Identifier: LGPL-2.1-or-later
"""Linked input GUI creation, ordinary jobs, task edits and stale-result guards."""
import os
import time
import traceback
import FreeCAD as App
import FreeCADGui as Gui
import ImplicitMixed
import ImplicitSolid
import ImplicitSolidCreate
import ImplicitOCCT as native
from ImplicitOperands import box_shape
from PySide import QtCore, QtWidgets


def until(predicate, seconds=100):
    deadline = time.monotonic() + seconds
    while not predicate():
        assert time.monotonic() < deadline, "Instance GUI condition timed out"
        loop = QtCore.QEventLoop()
        QtCore.QTimer.singleShot(20, loop.quit)
        loop.exec()


def main():
    Gui.activateWorkbench("ImplicitModelingWorkbench")
    doc = App.newDocument("OperandInstancesGUI")
    doc.UndoMode = 1
    field = doc.addObject("Implicit::Feature", "Gyroid")
    field.Function, field.Period = "Gyroid", 10
    field.DomainMin, field.DomainMax = (0, 0, 0), (20, 20, 20)
    box = doc.addObject("Part::Box", "Box")
    box.Length = box.Width = box.Height = 10
    box.Placement.Base = (.31, .37, 0)
    field_link = doc.addObject("App::Link", "FieldInstance"); field_link.setLink(field)
    box_link = doc.addObject("App::Link", "BoxInstance"); box_link.setLink(box)
    box_link.LinkTransform = True
    parent = doc.addObject("App::Part", "Container")
    parent.addObject(box_link); parent.Placement.Base = (1, 2, 0)
    doc.recompute(); doc.commitTransaction()
    original = box.Shape.exportBrepToString()
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(field_link); Gui.Selection.addSelection(box_link)
    task = ImplicitMixed.selected("Common")
    assert not task.accept()
    until(lambda: task.closed or task.job is None)
    assert task.result is not None, task.status.text()
    source = task.result
    task = ImplicitSolidCreate.open_task(source)
    assert not task.accept()
    until(lambda: task.closed or task.job is None)
    assert task.result is not None, task.status.text()
    solid = task.result
    assert source.BackgroundRecompute and solid.BackgroundRecompute
    assert source.Field is field_link and source.Box is box_link and solid.SolidValidated
    mixed, build = native.mixed_box, native.build_mixed_solids
    def forbidden(*args, **kwargs):
        raise AssertionError("Linked GUI workflow used synchronous numerical construction")
    native.mixed_box = native.build_mixed_solids = forbidden
    try:
        # Container movement must participate in live dependency recompute.
        parent.Placement.Base = (2, 2, 0)
        doc.recompute()
        assert source.Proxy._recompute_request is not None
        assert source.Geometry is None and solid.Geometry is None
        until(lambda: source.Proxy._recompute_request is None and solid.Proxy._recompute_request is None)
        assert solid.SolidValidated, solid.BackendStatus
        info = native.info(source.Proxy._boundary["implicit_face"])
        assert info["minimum"][0] == 2.31
        # Task editing reaches the shared primitive target, not a forwarded
        # property on an alias, and stages source preparation before solids.
        assert Gui.getDocument(doc.Name).setEdit(solid.Name)
        editor = solid.ViewObject.Proxy._task
        assert editor.source_edits is not None
        editor.parameters["Length"].setValue(9)
        editor.fit_domain.setChecked(False)
        editor.clicked(QtWidgets.QDialogButtonBox.Apply)
        assert editor.batch is not None, editor.status.text()
        until(lambda: editor.batch is None)
        assert box.Length.Value == 9 and solid.SolidValidated, editor.status.text()
        editor.reject()
        until(lambda: source.Proxy._recompute_request is None and solid.Proxy._recompute_request is None)
        assert box.Length.Value == 10 and solid.Geometry is not None
        replacement = doc.addObject("Implicit::Feature", "ReplacementGyroid")
        replacement.Function, replacement.Period = "Gyroid", 10
        replacement.DomainMin, replacement.DomainMax = (0, 0, 0), (20, 20, 20)
        doc.recompute(); doc.commitTransaction()
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(field_link); Gui.Selection.addSelection(box_link)
        task = ImplicitMixed.selected("Common")
        task.accept()
        field_link.setLink(replacement)  # Same math, different live target identity.
        assert field_link.recompute()
        field_link.purgeTouched()
        until(lambda: task.job is None)
        assert task.result is None and "changed" in task.status.text().lower(), task.status.text()
        task.reject()
        field_link.setLink(field)
        doc.recompute()
        until(lambda: source.Proxy._recompute_request is None and solid.Proxy._recompute_request is None)
        # The submitted instance transform cannot silently change underneath a
        # task result. Use a new creation task to exercise pre-publication guards.
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(field_link); Gui.Selection.addSelection(box_link)
        task = ImplicitMixed.selected("BoxMinusField")
        task.accept()
        parent.Placement.Base = (3, 2, 0)
        until(lambda: task.job is None)
        assert task.result is None and "changed" in task.status.text().lower(), task.status.text()
        task.reject()
    finally:
        native.mixed_box, native.build_mixed_solids = mixed, build
    doc.recompute()
    until(lambda: source.Proxy._recompute_request is None and solid.Proxy._recompute_request is None)
    assert solid.SolidValidated, solid.BackendStatus
    assert box.Shape.exportBrepToString() == original
    assert box_shape(box_link).BoundBox.XMin == 3.31
    App.closeDocument(doc.Name)
    print("native implicit operand instances GUI smoke test passed", flush=True)


try:
    main()
except BaseException:
    traceback.print_exc()
    os._exit(1)
finally:
    Gui.getMainWindow().close()
