# SPDX-License-Identifier: LGPL-2.1-or-later
"""Stage native solid settings before the first atomic construction."""
import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets
from ImplicitSolid import NativeSolid, build_limit_controls, _create
import ImplicitOCCT as native


class NativeSolidCreationTaskPanel:
    def __init__(self, source):
        self.source = source
        self.document_name = source.Document.Name
        self.document = source.Document
        self.closed = False
        self.result = None
        self.job = None
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
        self.timer = QtCore.QTimer(self.form)
        self.timer.setInterval(50)
        self.timer.timeout.connect(self._poll)
        self.form.destroyed.connect(self._destroyed)
        App.addDocumentObserver(self)

    def _stop(self):
        if self.job is not None:
            native.cancel_solid_job(self.job)
            self.job = None

    def _destroyed(self, *_args):
        self._stop()
        self.closed = True
        App.removeDocumentObserver(self)

    def slotDeletedDocument(self, doc):
        if doc == self.document:
            self.timer.stop()
            self._destroyed()

    def _values(self):
        return (self.tolerance.value(), int(self.resolution.currentText()),
                {name: widget.value() for name, widget in self.controls.items()},
                self.hide_source.isChecked())

    def _check_source(self):
        if (App.getDocument(self.document_name) != self.document
                or not self.source.isValid() or self.source.Document != self.document):
            raise RuntimeError("The boundary document or source is no longer available")
        if App.getActiveTransaction():
            raise RuntimeError("Finish the active transaction before creating a native solid")
        if any("Touched" in item.State or not item.isValid()
               for item in [self.source] + self.source.OutListRecursive):
            raise RuntimeError("Boundary inputs changed; recompute before building")

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
        if self.job is not None:
            return False
        try:
            self._check_source()
            self.request = self._values()
            tolerance, resolution, limits, _hide = self.request
            depth = limits["MaximumGeometryDepth"]
            if depth == 0:
                raise ValueError("Geometry depth must be -1 (inherit) or 1 to 24")
            self.record = NativeSolid._boundary_record(self.source)
            self.job = native.start_solid_job(self.source.Geometry, tolerance, resolution,
                *(limits[name] for name in ("MaximumDepth", "MaximumCells", "MaximumTests",
                    "MaximumSeparatorCells", "MaximumGeometryCells", "MaximumSegmentTests")), depth)
            self.status.setText("Building in background; Cancel stops this request")
            self.timer.start()
        except Exception as error:
            self.status.setText("Build failed: " + str(error))
        return False

    def _poll(self):
        if self.closed or self.job is None:
            self.timer.stop()
            return
        try:
            self._check_source()
            if self._values() != self.request:
                raise RuntimeError("Build settings changed; submit a new build")
            state = native.solid_job_status(self.job)
            if state["state"] in ("queued", "running", "cancelling"):
                self.status.setText("Background build: " + state["phase"].replace("_", " "))
                return
            if state["state"] != "ready":
                raise RuntimeError(state["error"] or state["state"])
            if NativeSolid._boundary_record(self.source) != self.record:
                raise RuntimeError("Boundary changed during construction; submit a new build")
            completed = native.take_solid_job(self.job)
            self.job = None
            self.timer.stop()
            tolerance, resolution, limits, hide = self.request
            limits = dict(limits)
            depth = limits.pop("MaximumGeometryDepth")
            self.result = _create(self.source, tolerance, resolution, depth,
                                  build_limits=limits, hide_source=hide, completed=completed,
                                  background_recompute=True)
        except Exception as error:
            self._stop()
            self.timer.stop()
            self.status.setText("Build failed: " + str(error))
            return
        self.closed = True
        App.removeDocumentObserver(self)
        Gui.Control.closeDialog(Gui.getDocument(self.document_name))
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(self.result)

    def reject(self):
        if not self.closed:
            self._stop()
            self.timer.stop()
            App.removeDocumentObserver(self)
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
