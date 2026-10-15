# SPDX-License-Identifier: LGPL-2.1-or-later
"""Native gyroid/plane sections via the isolated OCCT 8 worker, not Part shapes."""
import json
import math
import subprocess
import FreeCAD as App
from ImplicitNative import worker_path


class Section:
    def __init__(self, obj):
        self._section = None
        for name, kind, value in (
            ("NativeSchema", "Integer", 1), ("Period", "Length", 10),
            ("IsoValue", "Float", .21), ("PlaneNormal", "Vector", (0, 0, 1)),
            ("PlaneOffset", "Distance", .37), ("Span", "Length", 8),
            ("GeometricTolerance", "Length", .1), ("MaximumCells", "Integer", 512),
            ("CurveCount", "Integer", 0), ("ResolutionUsed", "Integer", 0),
            ("UnresolvedCells", "Integer", 0), ("GeometricBound", "Float", 0),
            ("BackendStatus", "String", ""), ("NativeRevision", "Integer", 0)):
            obj.addProperty("App::Property" + kind, name, "Native section")
            setattr(obj, name, value)
        for name in ("NativeSchema", "CurveCount", "ResolutionUsed", "UnresolvedCells",
                     "GeometricBound", "BackendStatus"):
            obj.setEditorMode(name, 1)
        obj.setEditorMode("NativeRevision", 2)
        obj.Proxy = self

    def execute(self, obj):
        self._section = None
        obj.CurveCount = 0
        obj.GeometricBound = 0
        obj.ResolutionUsed = obj.UnresolvedCells = 0
        try:
            if obj.NativeSchema != 1:
                raise ValueError("Unsupported native section schema")
            values = [obj.GeometricTolerance.Value, obj.Period.Value, obj.IsoValue,
                      *obj.PlaneNormal, obj.PlaneOffset.Value, obj.Span.Value, obj.MaximumCells]
            if not all(math.isfinite(v) for v in values):
                raise ValueError("Native section inputs must be finite")
            run = subprocess.run([worker_path(), "section"] + [format(v, ".17g") for v in values],
                                 capture_output=True, text=True, timeout=30, check=False)
            if run.returncode:
                raise RuntimeError(run.stderr.strip() or "Native section worker failed")
            data = json.loads(run.stdout)
            if data.get("schema") != 1 or data.get("backend") != "OCCT-8.1-native-section":
                raise ValueError("Unexpected native section response")
            obj.ResolutionUsed, obj.UnresolvedCells = data["resolution"], data["unresolved_cells"]
            if data["resolved"] is not True:
                raise RuntimeError("Unresolved native section: {} cells, {} potential-critical, {} ambiguous".format(
                    obj.UnresolvedCells, data["potential_critical_cells"], data["ambiguous_cells"]))
            bound = data["geometric_bound"]
            if not math.isfinite(bound) or not 0 <= bound <= obj.GeometricTolerance.Value:
                raise ValueError("Section did not meet its geometric bound")
            self._section = data
            obj.CurveCount, obj.GeometricBound = len(data["curves"]), bound
            obj.BackendStatus = "Resolved native section; tolerance-bearing polylines, NOT a Part shape"
        except Exception as error:
            obj.BackendStatus = "Unsupported/failed: " + str(error)
            raise
        finally:
            obj.NativeRevision += 1

    def onDocumentRestored(self, obj):
        self.execute(obj)

    def dumps(self):
        return None

    def loads(self, _state):
        self._section = None


class SectionView:
    def __init__(self, view):
        view.Proxy = self

    def attach(self, view):
        from pivy import coin
        self._root = coin.SoSeparator()
        self._coordinates = coin.SoCoordinate3()
        self._lines = coin.SoIndexedLineSet()
        color = coin.SoBaseColor()
        color.rgb = (.95, .6, .1)
        draw = coin.SoDrawStyle()
        draw.lineWidth = 2
        for node in (color, draw, self._coordinates, self._lines):
            self._root.addChild(node)
        view.addDisplayMode(self._root, "Native section")
        self.updateData(view.Object, "NativeRevision")

    def updateData(self, obj, name):
        if name != "NativeRevision" or not hasattr(self, "_lines"):
            return
        data = getattr(obj.Proxy, "_section", None)
        vertices, indices = [], []
        for curve in data["curves"] if data else []:
            indices.extend(range(len(vertices), len(vertices) + len(curve["points"])))
            indices.append(-1)
            vertices.extend(curve["points"])
        self._lines.coordIndex.setNum(0)
        self._coordinates.point.setNum(0)
        if vertices:
            self._coordinates.point.setValues(0, len(vertices), vertices)
            self._lines.coordIndex.setValues(0, len(indices), indices)

    def getDisplayModes(self, _view):
        return ["Native section"]

    def getDefaultDisplayMode(self):
        return "Native section"

    def setDisplayMode(self, name):
        return name

    def dumps(self):
        return None

    def loads(self, _state):
        pass


def create():
    worker_path()
    document = App.ActiveDocument or App.newDocument()
    document.openTransaction("Create experimental native gyroid section")
    try:
        obj = document.addObject("App::FeaturePython", "OCCTGyroidSection")
        Section(obj)
        obj.Label = "OCCT gyroid-plane section (experimental)"
        if App.GuiUp:
            SectionView(obj.ViewObject)
        document.recompute()
        if not obj.isValid() or obj.Proxy._section is None:
            raise RuntimeError(obj.BackendStatus)
        document.commitTransaction()
        return obj
    except BaseException:
        document.abortTransaction()
        raise
