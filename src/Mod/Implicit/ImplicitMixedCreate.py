# SPDX-License-Identifier: LGPL-2.1-or-later
"""Create a GUI boundary from private work, then enable background recompute."""
from types import SimpleNamespace
import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets
import ImplicitOCCT as native
from ImplicitMixed import MixedBoundary, _create


def capture(field, box, operation, tolerance, cells, policy):
    if (field.Document != box.Document or any("Touched" in obj.State or not obj.isValid()
                                            for obj in (field, box))):
        raise ValueError("Recompute valid same-document operands before creating a boundary")
    recipe = SimpleNamespace(Field=field, Box=box, Operation=operation,
        GeometricTolerance=SimpleNamespace(Value=tolerance), MaximumCells=cells, CornerPolicy=policy)
    MixedBoundary._validate_operands(recipe)
    face = native.gyroid(field.Period.Value, field.IsoValue, tuple(field.DomainMin),
                          tuple(field.DomainMax), tolerance)
    return (MixedBoundary._fingerprint(recipe), native.dumps(face), box.Shape.exportBrepToString(),
            ("common" if operation == "Common" else "box_minus_field", tolerance, cells, policy.lower()))


class BoundaryCreationTask:
    def __init__(self, field, box, operation):
        self.field, self.box = field, box
        self.document, self.document_name = field.Document, field.Document.Name
        self.closed, self.result, self.job = False, None, None
        self.form = QtWidgets.QWidget()
        self.form.setObjectName("ImplicitBoundaryCreation")
        self.form.setWindowTitle("Create native mixed boundary")
        layout = QtWidgets.QFormLayout(self.form)
        layout.setRowWrapPolicy(QtWidgets.QFormLayout.WrapAllRows)
        self.operation = QtWidgets.QComboBox()
        self.operation.addItems(["Common", "BoxMinusField"])
        self.operation.setCurrentText(operation)
        layout.addRow("Operation", self.operation)
        self.tolerance = QtWidgets.QDoubleSpinBox()
        self.tolerance.setDecimals(6)
        self.tolerance.setRange(.000001, 1000000)
        self.tolerance.setSuffix(" mm")
        self.tolerance.setValue(.1)
        layout.addRow("Seam tolerance", self.tolerance)
        self.cells = QtWidgets.QComboBox()
        self.cells.addItems([str(1 << power) for power in range(2, 10)])
        self.cells.setCurrentText("512")
        layout.addRow("Tracing budget", self.cells)
        self.policy = QtWidgets.QComboBox()
        self.policy.addItems(["Regularized", "Reject"])
        layout.addRow("Corner handling", self.policy)
        self.hide = QtWidgets.QCheckBox()
        self.hide.setChecked(True)
        layout.addRow("Hide operands after creation", self.hide)
        note = QtWidgets.QLabel("Create a native boundary before building a native solid. "
            "New boundaries rebuild in the background when their inputs change.")
        note.setWordWrap(True)
        layout.addRow(note)
        self.status = QtWidgets.QLabel("Ready at 0.1 mm seam tolerance")
        self.status.setTextFormat(QtCore.Qt.PlainText)
        self.status.setWordWrap(True)
        layout.addRow(self.status)
        self.timer = QtCore.QTimer(self.form)
        self.timer.setInterval(50)
        self.timer.timeout.connect(self._poll)
        self.form.destroyed.connect(self._destroyed)
        App.addDocumentObserver(self)

    def _values(self):
        return (self.operation.currentText(), self.tolerance.value(), int(self.cells.currentText()),
                self.policy.currentText(), self.hide.isChecked())

    def _check(self):
        if (App.getDocument(self.document_name) != self.document
                or not self.field.isValid() or not self.box.isValid()
                or self.field.Document != self.document or self.box.Document != self.document):
            raise RuntimeError("The creation document or operands changed")
        if App.getActiveTransaction():
            raise RuntimeError("Finish the active transaction before creating a boundary")

    def _stop(self):
        if self.job is not None:
            native.cancel_native_job(self.job)
            self.job = None
        try:
            self.timer.stop()
        except RuntimeError:
            pass  # The parent task widget may already be destroying its timer.

    def _destroyed(self, *_args):
        self._stop()
        self.closed = True
        App.removeDocumentObserver(self)

    def slotDeletedDocument(self, doc):
        if doc == self.document:
            self._destroyed()

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
            self._check()
            self.request = self._values()
            operation, tolerance, cells, policy, _hide = self.request
            self.snapshot = capture(self.field, self.box, operation, tolerance, cells, policy)
            self.job = native.start_boundary_job_from_record(native.loads(self.snapshot[1]),
                                                             self.snapshot[2], *self.snapshot[3])
            self.status.setText("Preparing boundary in background; Cancel stops this request")
            self.timer.start()
        except Exception as error:
            self.status.setText("Creation failed: " + str(error))
        return False

    def _poll(self):
        if self.closed or self.job is None:
            self.timer.stop()
            return
        try:
            self._check()
            if self._values() != self.request:
                raise RuntimeError("Creation settings changed; submit a new build")
            operation, tolerance, cells, policy, hide = self.request
            current = capture(self.field, self.box, operation, tolerance, cells, policy)
            if any(current[index] != self.snapshot[index] for index in (0, 1, 3)):
                raise RuntimeError("Operands changed; recompute and submit a new build")
            status = native.native_job_status(self.job)
            if status["state"] in ("queued", "running", "cancelling"):
                self.status.setText("Preparing boundary: " + status["phase"])
                return
            if status["state"] != "ready":
                raise RuntimeError(status["error"] or status["state"])
            completed = native.take_boundary_job(self.job)
            self.job = None
            self.timer.stop()
            self.result = _create(self.field, self.box, operation, policy, completed=completed,
                tolerance=tolerance, cells=cells, background_recompute=True, hide_operands=hide,
                submitted_snapshot=self.snapshot)
        except Exception as error:
            self._stop()
            self.status.setText("Creation failed: " + str(error))
            return
        self.closed = True
        App.removeDocumentObserver(self)
        Gui.Control.closeDialog(Gui.getDocument(self.document_name))
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(self.result)

    def reject(self):
        if not self.closed:
            self._destroyed()
            if self.document_name in App.listDocuments():
                Gui.Control.closeDialog(Gui.getDocument(self.document_name))
        return True


def open_task(field, box, operation="Common"):
    if Gui.Control.activeDialog():
        raise RuntimeError("Finish the active task before creating a boundary")
    if App.getActiveTransaction():
        raise RuntimeError("Finish the active transaction before creating a boundary")
    if operation not in ("Common", "BoxMinusField"):
        raise ValueError("Unsupported mixed-boundary operation")
    capture(field, box, operation, .1, 512, "Regularized")
    task = BoundaryCreationTask(field, box, operation)
    Gui.Control.showDialog(task, Gui.getDocument(field.Document.Name))
    Gui.Control.showTaskView()
    return task
