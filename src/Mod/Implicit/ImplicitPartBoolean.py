# SPDX-License-Identifier: LGPL-2.1-or-later
"""Representation-aware Part commands; native work precedes atomic publication."""
import weakref
import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets
import ImplicitOCCT as native
from ImplicitMixed import MixedBoundary, MixedBoundaryView
from ImplicitMixedCreate import capture
from ImplicitSolid import NativeSolid, NativeSolidView, build_limit_controls


_task = None
_error = ""


def current_task():
    return _task() if _task is not None else None


def operands(operation):
    selection = Gui.Selection.getSelectionEx("", 0)
    if len(selection) != 2 or any(any(item.SubElementNames) for item in selection):
        raise ValueError("Native Part Boolean requires two whole objects")
    objects = [item.Object for item in selection]
    fields = [obj for obj in objects if obj.getLinkedObject(True).TypeId == "Implicit::Feature"]
    boxes = [obj for obj in objects if obj.getLinkedObject(True).isDerivedFrom("Part::Feature")]
    if len(fields) != 1 or len(boxes) != 1:
        raise ValueError("Native Part Boolean currently supports a primitive field and conventional box; "
                         "native solid/boundary operands are not yet supported")
    if operation == "Common":
        return fields[0], boxes[0], "Common"
    if operation == "Cut" and objects[0] is boxes[0]:
        return fields[0], boxes[0], "BoxMinusField"
    if operation == "Cut":
        raise ValueError("Native Cut currently supports box minus field; field minus box is not supported")
    raise ValueError("Native " + operation + " is not yet supported; no generic Part Boolean was attempted")


class BooleanTask:
    def __init__(self, field, box, operation):
        self.field, self.box, self.operation = field, box, operation
        self.document, self.document_name = field.Document, field.Document.Name
        self.closed, self.result, self.source, self.job = False, None, None, None
        self.boundary = self.completed = None
        self.phase = "boundary"
        self.form = QtWidgets.QScrollArea()
        self.form.setWidgetResizable(True)
        self.panel = QtWidgets.QWidget()
        self.form.setWidget(self.panel)
        self.form.setObjectName("ImplicitPartBoolean")
        self.form.setWindowTitle("Part native " + operation)
        layout = QtWidgets.QFormLayout(self.panel)
        layout.setRowWrapPolicy(QtWidgets.QFormLayout.WrapAllRows)
        label = QtWidgets.QLabel(field.Label + " / " + box.Label)
        label.setTextFormat(QtCore.Qt.PlainText)
        layout.addRow("Operands", label)
        self.tolerance = QtWidgets.QDoubleSpinBox()
        self.tolerance.setDecimals(6); self.tolerance.setRange(.000001, 1000000)
        self.tolerance.setSuffix(" mm"); self.tolerance.setValue(.1)
        layout.addRow("Geometric tolerance", self.tolerance)
        self.cells = QtWidgets.QComboBox(); self.cells.addItems([str(1 << n) for n in range(2, 10)])
        self.cells.setCurrentText("512"); layout.addRow("Tracing budget", self.cells)
        self.policy = QtWidgets.QComboBox(); self.policy.addItems(["Regularized", "Reject"])
        layout.addRow("Corner handling", self.policy)
        self.resolution = QtWidgets.QComboBox(); self.resolution.addItems(["4", "8", "16", "32", "64"])
        self.resolution.setCurrentText("32"); layout.addRow("Topology resolution", self.resolution)
        self.controls = build_limit_controls(layout)
        self.hide = QtWidgets.QCheckBox(); self.hide.setChecked(True)
        layout.addRow("Hide operands after success", self.hide)
        note = QtWidgets.QLabel("Build a validated native solid and its live boundary source. "
                               "Creation and visibility share one undo step. Cancel stops the build.")
        note.setWordWrap(True); layout.addRow(note)
        self.status = QtWidgets.QLabel("Ready at 0.1 mm tolerance")
        self.status.setTextFormat(QtCore.Qt.PlainText); self.status.setWordWrap(True)
        layout.addRow(self.status)
        self.timer = QtCore.QTimer(self.form); self.timer.setInterval(50)
        self.timer.timeout.connect(self._poll)
        self.form.destroyed.connect(self._destroyed)
        App.addDocumentObserver(self)

    def _values(self):
        return (self.tolerance.value(), int(self.cells.currentText()), self.policy.currentText(),
                int(self.resolution.currentText()), tuple((name, control.value())
                for name, control in self.controls.items()), self.hide.isChecked())

    def _check(self):
        if self.closed or App.getDocument(self.document_name) != self.document:
            raise RuntimeError("Boolean document is no longer available")
        if App.getActiveTransaction():
            raise RuntimeError("Finish the active transaction before creating a native Boolean")
        if self.field.Document != self.document or self.box.Document != self.document:
            raise RuntimeError("Boolean operands changed document")

    def _capture(self):
        tolerance, cells, policy, *_ = self._values()
        return capture(self.field, self.box, self.operation, tolerance, cells, policy)

    def _stop(self):
        if self.job is not None:
            native.cancel_native_job(self.job)
            self.job = None
        try:
            self.timer.stop()
        except RuntimeError:
            pass  # The parent widget may already be destroying its timer.

    def _destroyed(self, *_args):
        if not self.closed:
            self._stop(); self.closed = True
            App.removeDocumentObserver(self)

    def slotDeletedDocument(self, doc):
        if doc == self.document:
            self._destroyed()

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

    def isAllowedAlterDocument(self): return False
    def isAllowedAlterView(self): return True
    def isAllowedAlterSelection(self): return False

    def accept(self):
        if self.closed: return True
        if self.job is not None: return False
        try:
            self._check()
            self.request = self._values()
            if dict(self.request[4])["MaximumGeometryDepth"] == 0:
                raise ValueError("Geometry depth must be -1 (inherit) or 1 to 24")
            self.snapshot = self._capture()
            self.boundary = self.completed = None
            self.phase = "boundary"
            self.job = native.start_boundary_job_from_record(native.loads(self.snapshot[1]),
                                                              self.snapshot[2], *self.snapshot[3])
            self.status.setText("Preparing native boundary; Cancel stops the build")
            self.timer.start()
        except Exception as error:
            self._stop(); self.status.setText("Boolean failed: " + str(error))
        return False

    def _poll(self):
        if self.closed or self.job is None: return
        try:
            self._check()
            if self._values() != self.request:
                raise ValueError("Boolean settings changed; submit a new build")
            current = self._capture()
            if any(current[i] != self.snapshot[i] for i in (0, 1, 3)):
                raise ValueError("Boolean operands changed; recompute and submit again")
            state = native.native_job_status(self.job)
            if state["state"] in ("queued", "running", "cancelling"):
                self.status.setText("Background " + self.phase + ": " + state["phase"])
                return
            if state["state"] != "ready":
                raise RuntimeError(state["error"] or state["state"])
            if self.phase == "boundary":
                self.boundary = native.take_boundary_job(self.job); self.job = None
                tolerance, _, _, resolution, controls, _ = self.request
                limits = dict(controls)
                self.job = native.start_solid_job(self.boundary["boundary_handle"], tolerance, resolution,
                    *(limits[name] for name in ("MaximumDepth", "MaximumCells", "MaximumTests",
                      "MaximumSeparatorCells", "MaximumGeometryCells", "MaximumSegmentTests")),
                    limits["MaximumGeometryDepth"])
                self.phase = "solid"
                self.status.setText("Building native solid; Cancel stops the build")
                return
            self.completed = native.take_solid_job(self.job); self.job = None
            if not self.completed.get("solid_validated", False):
                raise ValueError(self.completed.get("reason", "Native solid validation failed"))
            self._publish()
        except Exception as error:
            self._stop(); self.status.setText("Boolean failed: " + str(error))
            return
        self._stop(); self.closed = True
        App.removeDocumentObserver(self)
        Gui.Control.closeDialog(Gui.getDocument(self.document_name))
        Gui.Selection.clearSelection(); Gui.Selection.addSelection(self.result)

    def _publish(self):
        self._check()
        doc = self.document
        doc.openTransaction("Part native " + self.operation)
        transaction = App.getActiveTransaction()[1]
        def owned():
            active = App.getActiveTransaction()
            if not active or active[1] != transaction:
                raise RuntimeError("Native Boolean publication transaction changed")
        try:
            self._prepare_operands()
            owned()
            source = doc.addObject("Implicit::NativeFeaturePython", "NativeMixedBoundary")
            MixedBoundary(source)
            source.Field, source.Box, source.Operation = self.field, self.box, self.operation
            tolerance, cells, policy, resolution, controls, hide = self.request
            source.GeometricTolerance, source.MaximumCells, source.CornerPolicy = tolerance, cells, policy
            source.BackgroundRecompute = True
            source.Label = "Native " + self.operation + " boundary"
            MixedBoundaryView(source.ViewObject)
            source.Proxy.publish(source, self.boundary, *self.snapshot)
            owned(); doc.recompute(); owned()
            solid = doc.addObject("Implicit::NativeSolidFeaturePython", "NativeSolid")
            NativeSolid(solid)
            solid.Source, solid.BackgroundRecompute = source, True
            solid.GeometricTolerance, solid.TopologyResolution = tolerance, resolution
            for name, value in controls: setattr(solid, name, value)
            solid.Label = getattr(self, "result_label", "Native Part " + self.operation)
            NativeSolidView(solid.ViewObject)
            solid.Proxy.publish(solid, self.completed)
            owned(); doc.recompute(); owned()
            if (not solid.isValid() or not solid.SolidValidated or not source.isValid()
                    or any(self._capture()[i] != self.snapshot[i] for i in (0, 1, 3))):
                raise ValueError("Native Boolean publication disagrees with current operands")
            source.ViewObject.Visibility = False
            if hide: self.field.ViewObject.Visibility = self.box.ViewObject.Visibility = False
            owned(); doc.commitTransaction()
            self.source, self.result = source, solid
        except BaseException:
            active = App.getActiveTransaction()
            if active and active[1] == transaction: doc.abortTransaction()
            raise

    def _prepare_operands(self):
        """Existing Part selections already have live document operands."""

    def reject(self):
        self._destroyed()
        if self.document_name in App.listDocuments():
            Gui.Control.closeDialog(Gui.getDocument(self.document_name))
        return True


def dispatch(operation):
    global _task, _error
    _error = ""
    try:
        if Gui.Control.activeDialog():
            raise RuntimeError("Finish the active task before a native Part Boolean")
        if App.getActiveTransaction():
            raise RuntimeError("Finish the active transaction before a native Part Boolean")
        field, box, mode = operands(operation)
        capture(field, box, mode, .1, 512, "Regularized")
        task = BooleanTask(field, box, mode)
        _task = weakref.ref(task)
        Gui.Control.showDialog(task, Gui.getDocument(field.Document.Name))
        Gui.Control.showTaskView()
        return task
    except Exception as error:
        _error = str(error)
        App.Console.PrintError("Native Part Boolean: " + _error + "\n")
        return None
