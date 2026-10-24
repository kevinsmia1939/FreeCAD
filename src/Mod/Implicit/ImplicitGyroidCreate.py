# SPDX-License-Identifier: LGPL-2.1-or-later
"""Stage a native gyroid solid before publishing any document objects."""
import weakref
import FreeCAD as App
import FreeCADGui as Gui
import Part
from PySide import QtCore, QtWidgets
import ImplicitOCCT as native
import ImplicitPartBoolean as bridge
from ImplicitMixedCreate import capture


class GyroidTask(bridge.BooleanTask):
    def __init__(self, document):
        # The base task only reads these attributes while constructing its UI.
        from types import SimpleNamespace
        recipe = SimpleNamespace(Document=document, Label="New gyroid")
        super().__init__(recipe, recipe, "Common")
        self.field = self.box = None
        self.result_label = "Gyroid solid"
        self.controls["MaximumGeometryDepth"].setValue(18)
        self.form.setObjectName("ImplicitNativeGyroidCreation")
        self.form.setWindowTitle("Add native gyroid solid")
        self.dimensions = {}
        layout = self.panel.layout()
        for row, name in enumerate(("Period", "Length", "Width", "Height")):
            control = QtWidgets.QDoubleSpinBox()
            control.setDecimals(6)
            control.setRange(.000001, 1000000)
            control.setSuffix(" mm")
            control.setValue(10)
            self.dimensions[name] = control
            layout.insertRow(row, name, control)
        self.level = QtWidgets.QDoubleSpinBox()
        self.level.setDecimals(6)
        self.level.setRange(-10, 10)
        layout.insertRow(4, "Level set (dimensionless)", self.level)
        self.status.setText("Ready: 10 mm cube native gyroid at 0.1 mm tolerance")

    def _check(self):
        if self.field is not None:
            return super()._check()
        if self.closed or App.getDocument(self.document_name) != self.document:
            raise RuntimeError("Gyroid document is no longer available")
        if App.getActiveTransaction():
            raise RuntimeError("Finish the active transaction before creating a gyroid")

    def _capture(self):
        tolerance, cells, policy, *_ = self._values()
        if self.field is not None:
            return capture(self.field, self.box, "Common", tolerance, cells, policy)
        period, length, width, height = (control.value() for control in self.dimensions.values())
        level = self.level.value()
        face = native.gyroid(period, level, (0, 0, 0), (length, width, height), tolerance)
        return (repr((period, length, width, height, level)), native.dumps(face),
                Part.makeBox(length, width, height).exportBrepToString(),
                ("common", tolerance, cells, policy.lower()))

    def _prepare_operands(self):
        period, length, width, height = (control.value() for control in self.dimensions.values())
        doc = self.document
        field = doc.addObject("Implicit::Feature", "Gyroid")
        box = doc.addObject("Part::Box", "GyroidDomain")
        # Keep references local until the complete recipe has recomputed.
        field.Function, field.Period, field.IsoValue = "Gyroid", period, self.level.value()
        field.DomainMin, field.DomainMax = (0, 0, 0), (length, width, height)
        for name, axis, value in zip(("Length", "Width", "Height"), "xyz", (length, width, height)):
            field.addProperty("App::PropertyLength", name, "Gyroid dimensions",
                              "Clipped native gyroid domain size")
            setattr(field, name, value)
            field.setExpression("DomainMax." + axis, "DomainMin." + axis + " + " + name + " / (1 mm)")
            box.setExpression(name, field.Name + "." + name)
        doc.recompute()
        tolerance, cells, policy, *_ = self.request
        current = capture(field, box, "Common", tolerance, cells, policy)
        if current[1] != self.snapshot[1] or current[3] != self.snapshot[3]:
            raise ValueError("Published gyroid differs from the submitted mathematical recipe")
        # The private BRep record retains the exact worker descriptor. Live input
        # fingerprinting uses geometry, not transient OCCT serialization flags.
        self.snapshot = (current[0], *self.snapshot[1:])
        self.field, self.box = field, box

    def _publish(self):
        try:
            super()._publish()
        except BaseException:
            # Failed publication aborts all four owners. Retry must use the
            # controls rather than dangling references to rolled-back operands.
            self.field = self.box = None
            raise


def open_task():
    if Gui.Control.activeDialog() or App.getActiveTransaction():
        raise RuntimeError("Finish the active task or transaction before adding a native gyroid")
    document = App.ActiveDocument or App.newDocument()
    task = GyroidTask(document)
    bridge._task = weakref.ref(task)
    Gui.Control.showDialog(task, Gui.getDocument(document.Name))
    Gui.Control.showTaskView()
    return task
