# SPDX-License-Identifier: LGPL-2.1-or-later
"""Stage native solid settings before the first atomic construction."""
import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets
from ImplicitSolid import NativeSolid, build_limit_controls, create


class NativeSolidCreationTaskPanel:
    def __init__(self, source):
        self.source = source
        self.document_name = source.Document.Name
        self.closed = False
        self.result = None
        self.form = QtWidgets.QWidget()
        self.form.setObjectName("ImplicitNativeSolidCreation")
        self.form.setWindowTitle("Create native implicit solid")
        layout = QtWidgets.QFormLayout(self.form)
        layout.setRowWrapPolicy(QtWidgets.QFormLayout.WrapAllRows)
        label = QtWidgets.QLabel(source.Label)
        label.setTextFormat(QtCore.Qt.PlainText)
        label.setWordWrap(True)
        layout.addRow("Boundary source", label)
        self.tolerance = QtWidgets.QDoubleSpinBox()
        self.tolerance.setDecimals(6)
        self.tolerance.setRange(.000001, 1000000)
        self.tolerance.setSuffix(" mm")
        self.tolerance.setValue(.1)
        layout.addRow("Solid tolerance", self.tolerance)
        self.resolution = QtWidgets.QComboBox()
        self.resolution.addItems(["4", "8", "16", "32", "64"])
        self.resolution.setCurrentText("32")
        layout.addRow("Topology reference resolution", self.resolution)
        self.controls = build_limit_controls(layout)
        self.hide_source = QtWidgets.QCheckBox()
        self.hide_source.setChecked(True)
        layout.addRow("Hide boundary after successful build", self.hide_source)
        note = QtWidgets.QLabel(
            "Choose settings before the first build. More geometry depth or a larger "
            "work budget may be needed for larger models. Depth does not change the "
            "physical tolerance. A failed build leaves this panel open for adjustment.")
        note.setWordWrap(True)
        layout.addRow(note)
        self.status = QtWidgets.QLabel("Ready to build at 0.1 mm tolerance")
        self.status.setTextFormat(QtCore.Qt.PlainText)
        self.status.setWordWrap(True)
        layout.addRow(self.status)

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

    def isAllowedAlterDocument(self):
        return False

    def isAllowedAlterView(self):
        return True

    def isAllowedAlterSelection(self):
        return False

    def accept(self):
        if self.closed:
            return True
        try:
            doc = App.getDocument(self.document_name)
            if doc is None or self.source.Document != doc:
                raise RuntimeError("The boundary document is no longer available")
            limits = {name: widget.value() for name, widget in self.controls.items()}
            depth = limits.pop("MaximumGeometryDepth")
            if depth == 0:
                raise ValueError("Geometry depth must be -1 (inherit) or 1 to 24")
            self.result = create(self.source, self.tolerance.value(),
                                 int(self.resolution.currentText()), depth,
                                 build_limits=limits, hide_source=self.hide_source.isChecked())
        except Exception as error:
            self.status.setText("Build failed: " + str(error))
            return False
        self.closed = True
        Gui.Control.closeDialog(Gui.getDocument(self.document_name))
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(self.result)
        return True

    def reject(self):
        if not self.closed:
            self.closed = True
            if App.getDocument(self.document_name) is not None:
                Gui.Control.closeDialog(Gui.getDocument(self.document_name))
        return True


def open_task(source):
    if Gui.Control.activeDialog():
        raise RuntimeError("Finish the active task before creating a native solid")
    if App.getActiveTransaction():
        raise RuntimeError("Finish the active transaction before creating a native solid")
    NativeSolid._boundary_record(source)
    task = NativeSolidCreationTaskPanel(source)
    Gui.Control.showDialog(task, Gui.getDocument(source.Document.Name))
    Gui.Control.showTaskView()
    return task
