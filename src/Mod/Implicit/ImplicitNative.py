# SPDX-License-Identifier: LGPL-2.1-or-later
"""Experimental OCCT 8 sphere-boundary GUI adapter, isolated from OCCT 7 Part.

Only editable mathematical inputs persist. Native faces are reconstructed in a
separate executable on recompute; returned triangles are disposable Coin data.
This is not a Part::Feature or an in-process OCCT 8 FreeCAD build.
"""
import json
import math
import os
from pathlib import Path
import subprocess

import FreeCAD as App


def worker_path():
    """Executable selection is environment/user configuration, never FCStd data."""
    configured = os.environ.get("IMPLICIT_OCCT_NATIVE_WORKER") or App.ParamGet(
        "User parameter:BaseApp/Preferences/Mod/Implicit").GetString("NativeWorker", "")
    path = Path(configured) if configured else Path(App.getHomePath()).parent / (
        "build-occt-implicit/native-face-tests/implicit_occt_native_worker")
    if not path.is_file() or not os.access(path, os.X_OK):
        raise RuntimeError("Build the isolated OCCT 8 native worker and set "
                           "IMPLICIT_OCCT_NATIVE_WORKER to its executable path")
    return str(path.resolve())


class NativeBoundary:
    def __init__(self, obj):
        self._mesh = None
        obj.addProperty("App::PropertyInteger", "NativeSchema", "Native OCCT").NativeSchema = 1
        obj.addProperty("App::PropertyEnumeration", "Operation", "Native OCCT")
        obj.Operation = ["Sphere", "Trim", "Common", "Fuse", "Cut"]
        obj.addProperty("App::PropertyVector", "LeftCenter", "Operands")
        obj.addProperty("App::PropertyLength", "LeftRadius", "Operands").LeftRadius = 2
        obj.addProperty("App::PropertyVector", "RightCenter", "Operands").RightCenter = (2, 0, 0)
        obj.addProperty("App::PropertyLength", "RightRadius", "Operands").RightRadius = 2
        obj.addProperty("App::PropertyVector", "PlaneNormal", "Trim").PlaneNormal = (0, 0, 1)
        obj.addProperty("App::PropertyDistance", "PlaneOffset", "Trim").PlaneOffset = .5
        obj.addProperty("App::PropertyLength", "GeometricTolerance", "Native OCCT").GeometricTolerance = .1
        obj.addProperty("App::PropertyString", "BackendStatus", "Diagnostics")
        obj.addProperty("App::PropertyInteger", "NativeFaceCount", "Diagnostics")
        obj.addProperty("App::PropertyFloat", "DisplayErrorBound", "Diagnostics")
        obj.addProperty("App::PropertyInteger", "NativeRevision", "Diagnostics")
        for name in ("NativeSchema", "BackendStatus", "NativeFaceCount", "DisplayErrorBound"):
            obj.setEditorMode(name, 1)
        obj.setEditorMode("NativeRevision", 2)
        obj.Proxy = self

    def execute(self, obj):
        self._mesh = None
        try:
            if obj.NativeSchema != 1:
                raise ValueError("Unsupported native boundary feature schema")
            mode = str(obj.Operation).lower()
            a = list(obj.LeftCenter) + [obj.LeftRadius.Value]
            b = (list(obj.PlaneNormal) + [obj.PlaneOffset.Value] if mode == "trim"
                 else list(obj.RightCenter) + [obj.RightRadius.Value])
            values = [obj.GeometricTolerance.Value] + a + b
            if not all(math.isfinite(v) for v in values):
                raise ValueError("Native inputs must be finite")
            run = subprocess.run([worker_path(), mode] + [format(v, ".17g") for v in values],
                                 capture_output=True, text=True, timeout=30, check=False)
            if run.returncode:
                raise RuntimeError(run.stderr.strip() or "Native worker failed")
            data = json.loads(run.stdout)
            if (data.get("schema") != 1 or data.get("backend") != "OCCT-8.1-native-sphere"
                    or data.get("solid_validated") is not False or len(data["faces"]) > 2):
                raise ValueError("Unexpected native worker response")
            bound = max((f["geometric_bound"] for f in data["faces"]), default=0.0)
            if not math.isfinite(bound) or not 0 <= bound <= obj.GeometricTolerance.Value * (1+1e-12):
                raise ValueError("Native mesh did not meet requested geometric bound")
            self._mesh = data
            obj.NativeFaceCount = len(data["faces"])
            obj.DisplayErrorBound = bound
            obj.BackendStatus = "OCCT 8 native boundary; experimental, NOT a validated Part solid"
        except Exception as error:
            obj.NativeFaceCount = 0
            obj.DisplayErrorBound = 0
            obj.BackendStatus = "Unsupported/failed: " + str(error)
            raise
        finally:
            # Never leave a stale successful display after an operation fails.
            obj.NativeRevision += 1

    def onDocumentRestored(self, obj):
        self._mesh = None
        # FreeCAD clears the touched state after restoration callbacks; rebuild
        # here rather than rely on a later recompute to notice a missing cache.
        self.execute(obj)

    def dumps(self):
        return None  # Never persist mesh buffers or executable paths.

    def loads(self, _state):
        self._mesh = None


class NativeBoundaryView:
    def __init__(self, view):
        view.addProperty("App::PropertyColor", "SurfaceColor", "Display").SurfaceColor = (.3, .7, .9)
        view.Proxy = self

    def attach(self, view):
        from pivy import coin
        # Dynamic view properties may not have been replayed on FCStd restore.
        if "SurfaceColor" not in view.PropertiesList:
            view.addProperty("App::PropertyColor", "SurfaceColor", "Display")
            view.SurfaceColor = (.3, .7, .9)
        self._root = coin.SoSeparator()
        self._material = coin.SoMaterial()
        self._coordinates = coin.SoCoordinate3()
        self._normals = coin.SoNormal()
        self._faces = coin.SoIndexedFaceSet()
        binding = coin.SoNormalBinding()
        binding.value = coin.SoNormalBinding.PER_VERTEX_INDEXED
        hints = coin.SoShapeHints()
        hints.vertexOrdering = coin.SoShapeHints.COUNTERCLOCKWISE
        for node in (self._material, hints, self._coordinates, self._normals, binding, self._faces):
            self._root.addChild(node)
        view.addDisplayMode(self._root, "Native boundary")
        self.onChanged(view, "SurfaceColor")
        self.updateData(view.Object, "NativeRevision")

    def updateData(self, obj, prop):
        if prop != "NativeRevision" or not hasattr(self, "_faces"):
            return
        data = getattr(obj.Proxy, "_mesh", None)
        vertices, normals, indices = [], [], []
        for face in data["faces"] if data else []:
            base = len(vertices)
            vertices.extend(face["vertices"])
            normals.extend(face["normals"])
            for triangle in face["triangles"]:
                indices.extend([base + i for i in triangle] + [-1])
        self._faces.coordIndex.setNum(0)
        self._coordinates.point.setNum(0)
        self._normals.vector.setNum(0)
        if vertices:
            self._coordinates.point.setValues(0, len(vertices), vertices)
            self._normals.vector.setValues(0, len(normals), normals)
            self._faces.coordIndex.setValues(0, len(indices), indices)

    def onChanged(self, view, prop):
        if prop == "SurfaceColor" and hasattr(self, "_material"):
            self._material.diffuseColor = tuple(float(v) for v in view.SurfaceColor[:3])

    def getDisplayModes(self, _view):
        return ["Native boundary"]

    def getDefaultDisplayMode(self):
        return "Native boundary"

    def setDisplayMode(self, mode):
        return mode

    def dumps(self):
        return None

    def loads(self, _state):
        pass


def create(operation="Trim"):
    """Create an editable analytic test case, not a selected-operand Part BOP."""
    worker_path()
    document = App.ActiveDocument or App.newDocument()
    document.openTransaction("Create experimental OCCT native boundary")
    try:
        obj = document.addObject("App::FeaturePython", "OCCTNativeBoundary")
        NativeBoundary(obj)
        obj.Operation = operation
        obj.Label = "OCCT " + operation + " (experimental boundary)"
        if App.GuiUp:
            NativeBoundaryView(obj.ViewObject)
        document.recompute()
        if not obj.isValid() or obj.Proxy._mesh is None:
            raise RuntimeError(obj.BackendStatus)
        document.commitTransaction()
        return obj
    except BaseException:
        document.abortTransaction()
        raise
