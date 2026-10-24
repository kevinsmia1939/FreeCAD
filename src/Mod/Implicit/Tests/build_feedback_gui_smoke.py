# SPDX-License-Identifier: LGPL-2.1-or-later
"""Live tree/property feedback follows jobs without writing model or undo data."""
import os
import time
import tempfile
import traceback
import zipfile
import FreeCAD as App
import FreeCADGui as Gui
import ImplicitMixed
import ImplicitSolid
import ImplicitBuildFeedback as feedback
import ImplicitOCCT as native
from PySide import QtCore, QtWidgets


def until(predicate, seconds=90):
    deadline = time.monotonic() + seconds
    while not predicate():
        assert time.monotonic() < deadline, "Feedback condition timed out"
        loop = QtCore.QEventLoop()
        QtCore.QTimer.singleShot(20, loop.quit)
        loop.exec()


def property_text():
    editor = Gui.getMainWindow().findChild(QtWidgets.QTreeView, "propertyEditorView")
    assert editor is not None
    def find(parent=QtCore.QModelIndex()):
        model = editor.model()
        for row in range(model.rowCount(parent)):
            index = model.index(row, 0, parent)
            if str(model.data(index)) in ("Build Feedback", "BuildFeedback"):
                return str(model.data(model.index(row, 1, parent)))
            found = find(index)
            if found is not None:
                return found
        return None
    return find()


def tree_icon(label):
    def visit(item):
        if item.text(0) == label:
            return item.icon(0).pixmap(32, 32).toImage()
        for index in range(item.childCount()):
            found = visit(item.child(index))
            if found is not None:
                return found
        return None
    for tree in Gui.getMainWindow().findChildren(QtWidgets.QTreeWidget):
        for index in range(tree.topLevelItemCount()):
            found = visit(tree.topLevelItem(index))
            if found is not None:
                return found
    return None


def main():
    Gui.activateWorkbench("ImplicitModelingWorkbench")
    doc = App.newDocument("BuildFeedbackGUI")
    doc.UndoMode = 1
    field = doc.addObject("Implicit::Feature", "Gyroid")
    field.Function, field.Period = "Gyroid", 10
    field.DomainMin, field.DomainMax = (0, 0, 0), (10, 10, 10)
    box = doc.addObject("Part::Box", "Box")
    box.Length = box.Width = box.Height = 10
    doc.recompute()
    source = ImplicitMixed.create(field, box, corner_policy="Regularized")
    obj = ImplicitSolid.create(source)
    source.Label, obj.Label = "Feedback source", "Feedback solid"
    obj.BackgroundRecompute = True
    doc.recompute(); doc.commitTransaction()
    assert feedback.describe(source)[0] == "Ready"
    assert feedback.describe(obj)[0] == "Ready"
    assert "Ready:" in str(obj.ViewObject.BuildFeedback)
    assert not obj.ViewObject.Icon.isNull()
    Gui.Selection.clearSelection(); Gui.Selection.addSelection(obj)
    tabs = Gui.getMainWindow().findChild(QtWidgets.QTabWidget, "propertyTab")
    editor = Gui.getMainWindow().findChild(QtWidgets.QTreeView, "propertyEditorView")
    tabs.setCurrentWidget(editor)
    until(lambda: property_text() is not None)
    assert "Ready:" in property_text(), property_text()
    until(lambda: tree_icon(obj.Label) is not None)
    ready_icon = tree_icon(obj.Label)
    feedback_object = obj.ViewObject.BuildFeedback

    obj.MaximumCells = 1
    assert feedback.describe(obj)[0] == "Changed"
    doc.recompute()
    assert feedback.describe(obj)[0] == "Pending"
    assert obj.Geometry is None and not obj.SolidValidated
    until(lambda: obj.Proxy._recompute_request is None)
    assert feedback.describe(obj)[0] == "Failed", obj.BackendStatus
    assert obj.ViewObject.BuildFeedback is feedback_object  # No status setter/replacement.
    assert "Failed:" in str(feedback_object), str(feedback_object)
    assert obj in Gui.Selection.getSelection()  # Keep the property panel attached.
    until(lambda: "Failed:" in (property_text() or ""))
    until(lambda: tree_icon(obj.Label) != ready_icon)
    obj.MaximumCells = 4000000
    doc.recompute()
    until(lambda: obj.Proxy._recompute_request is None)
    assert obj.SolidValidated and feedback.describe(obj)[0] == "Ready", obj.BackendStatus

    # A source failure is visible on the source and its unavailable solid.
    source.BackgroundRecompute = True
    Gui.Selection.clearSelection(); Gui.Selection.addSelection(source)
    source.MaximumCells = 4
    doc.recompute()
    assert feedback.describe(source)[0] == "Pending"
    until(lambda: source.Proxy._recompute_request is None)
    assert feedback.describe(source)[0] == feedback.describe(obj)[0] == "Failed"
    assert source in Gui.Selection.getSelection()
    until(lambda: "Failed:" in (property_text() or ""))
    source.MaximumCells = 512
    doc.recompute()
    until(lambda: source.Proxy._recompute_request is None and obj.Proxy._recompute_request is None)
    assert feedback.describe(obj)[0] == "Ready"

    with tempfile.TemporaryDirectory(prefix="implicit-feedback-") as directory:
        filename = os.path.join(directory, "feedback.FCStd")
        doc.saveCopy(filename)
        with zipfile.ZipFile(filename) as archive:
            gui_xml = archive.read("GuiDocument.xml").decode()
            assert "document_identity" not in gui_xml and "ImplicitBuildFeedback.Feedback" not in gui_xml
        loaded = App.openDocument(filename)
        other = loaded.getObject(obj.Name)
        loaded.recompute()
        assert feedback.describe(other)[0] == "Unverified"
        assert "Unverified:" in str(other.ViewObject.BuildFeedback)
        assert not other.SolidValidated
        App.closeDocument(loaded.Name)
        App.setActiveDocument(doc.Name)

    # Let polling repaint feedback during a foreign transaction, then undo only
    # that edit. Presentation must not add property writes to its journal.
    doc.openTransaction("Unrelated label")
    old_label = box.Label
    box.Label = "Unrelated label"
    before = (obj.NativeRevision, obj.BackendStatus, obj.InputFingerprint,
              native.dumps_mixed_solids(obj.Geometry), doc.UndoCount)
    # Exercise an actual repaint/icon notification inside the transaction.
    reference, _ = feedback._watcher.views[id(obj.ViewObject.Proxy)]
    feedback._watcher.views[id(obj.ViewObject.Proxy)] = reference, None
    for _ in range(4):
        feedback._watcher.poll()
    assert (obj.NativeRevision, obj.BackendStatus, obj.InputFingerprint,
            native.dumps_mixed_solids(obj.Geometry), doc.UndoCount) == before
    doc.commitTransaction(); doc.undo()
    assert box.Label == old_label and obj.Geometry is not None
    until(lambda: feedback.describe(obj)[0] == "Ready")
    assert str(feedback_object).startswith("Ready:")
    Gui.Selection.clearSelection(); Gui.Selection.addSelection(obj)
    until(lambda: "Ready:" in (property_text() or ""))
    Gui.activeDocument().activeView().viewAxonometric()
    Gui.activeDocument().activeView().fitAll()
    Gui.updateGui()
    Gui.getMainWindow().grab().save("/tmp/implicit-build-feedback.png")
    App.closeDocument(doc.Name)
    feedback._watcher.poll()
    assert str(feedback_object) == "Unavailable"
    assert not feedback._watcher.views and not feedback._watcher.timer.isActive()
    print("native implicit build feedback GUI smoke test passed", flush=True)


try:
    main()
except BaseException:
    traceback.print_exc()
    os._exit(1)
finally:
    Gui.getMainWindow().close()
