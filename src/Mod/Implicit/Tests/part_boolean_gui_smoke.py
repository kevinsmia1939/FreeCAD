# SPDX-License-Identifier: LGPL-2.1-or-later
"""Exercise real Part dispatch, private staging and atomic native publication."""
import os
import time
import traceback
import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore
import ImplicitOCCT as native
import ImplicitPartBoolean as bridge


def pulse():
    loop = QtCore.QEventLoop()
    QtCore.QTimer.singleShot(20, loop.quit)
    loop.exec()


def finish(task):
    deadline = time.monotonic() + 180
    while task.job is not None:
        assert time.monotonic() < deadline, task.status.text()
        pulse()


def select(*objects):
    Gui.Selection.clearSelection()
    for obj in objects:
        Gui.Selection.addSelection(obj)


def main():
    Gui.activateWorkbench("ImplicitModelingWorkbench")
    Gui.activateWorkbench("PartWorkbench")
    doc = App.newDocument("PartNativeBooleanGUI")
    doc.UndoMode = 1
    field = doc.addObject("Implicit::Feature", "Gyroid")
    field.Function, field.Period, field.IsoValue = "Gyroid", 10, 0
    field.DomainMin, field.DomainMax = (0, 0, 0), (10, 10, 10)
    box = doc.addObject("Part::Box", "Box")
    box.Length = box.Width = box.Height = 10
    doc.recompute()
    doc.commitTransaction()
    baseline = {obj.Name for obj in doc.Objects}
    select(field, box)
    Gui.runCommand("Part_Common")
    task = bridge.current_task()
    assert task is not None and Gui.Control.activeDialog()
    assert {obj.Name for obj in doc.Objects} == baseline
    assert App.getActiveTransaction() is None
    task.accept()
    assert task.job is not None
    task.reject()
    assert {obj.Name for obj in doc.Objects} == baseline
    # A worker may still be completing cooperative cancellation.
    for _ in range(20):
        pulse()
    select(field, box)
    Gui.runCommand("Part_Common")
    task = bridge.current_task()
    task.accept()
    finish(task)
    assert task.closed and task.result is not None, task.status.text()
    solid, source = task.result, task.source
    assert solid.SolidValidated and solid.isValid() and source.isValid()
    assert source.Field == field and source.Box == box
    assert source.BackgroundRecompute and solid.BackgroundRecompute
    assert not hasattr(solid, "Shape")
    assert not field.ViewObject.Visibility and not box.ViewObject.Visibility
    names = source.Name, solid.Name
    doc.undo()
    assert {obj.Name for obj in doc.Objects} == baseline
    assert field.ViewObject.Visibility and box.ViewObject.Visibility
    doc.redo()
    assert all(doc.getObject(name) is not None for name in names)
    select(field, box)
    Gui.runCommand("Part_Cut")
    assert "box minus field" in bridge._error and not Gui.Control.activeDialog()
    Gui.runCommand("Part_Fuse")
    assert "not yet supported" in bridge._error and not Gui.Control.activeDialog()
    select(doc.getObject(names[1]), box)
    Gui.runCommand("Part_Common")
    assert "native solid/boundary" in bridge._error and not Gui.Control.activeDialog()
    count = len(doc.Objects)
    select(box, field)
    Gui.runCommand("Part_Cut")
    task = bridge.current_task()
    assert task.operation == "BoxMinusField"
    task.controls["MaximumCells"].setValue(1)
    task.accept()
    finish(task)
    assert not task.closed and task.result is None and "failed" in task.status.text()
    assert len(doc.Objects) == count and App.getActiveTransaction() is None
    task.controls["MaximumCells"].setValue(4000000)
    task.accept()
    finish(task)
    assert task.closed and task.result.SolidValidated, task.status.text()
    assert task.source.Operation == "BoxMinusField"
    # Ordinary B-Reps still take the stock Part command path.
    first = doc.addObject("Part::Box", "OrdinaryFirst")
    second = doc.addObject("Part::Box", "OrdinarySecond")
    second.Placement.Base = (1, 1, 1)
    doc.recompute()
    select(first, second)
    Gui.runCommand("Part_Common")
    doc.recompute()
    assert any(obj.TypeId == "Part::MultiCommon" and not obj.Shape.isNull()
               for obj in doc.Objects)
    assert not Gui.Control.activeDialog()
    App.closeDocument(doc.Name)
    print("native Part Boolean GUI smoke test passed", flush=True)


try:
    main()
except BaseException:
    traceback.print_exc()
    os._exit(1)
finally:
    Gui.getMainWindow().close()
