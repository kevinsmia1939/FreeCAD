# SPDX-License-Identifier: LGPL-2.1-or-later
"""In-process native faces, no worker; recipe persistence and retained Coin buffers."""
import os
from pathlib import Path
import tempfile
import traceback
import zipfile
import FreeCAD as App
import FreeCADGui as Gui
import ImplicitNative
import ImplicitOCCT as native


def main():
    Gui.activateWorkbench("NativeImplicitWorkbench")
    assert "Implicit_OCCTInProcessSphere" in Gui.listCommands()
    original = ImplicitNative.subprocess.run
    def forbidden(*_args, **_kwargs):
        raise AssertionError("in-process operation attempted a worker subprocess")
    ImplicitNative.subprocess.run = forbidden
    try:
        obj = ImplicitNative.create("Sphere", backend="InProcess")
        doc = obj.Document
        assert obj.TypeId == "App::FeaturePython" and "Shape" not in obj.PropertiesList
        old = obj.Proxy.native_faces()[0]
        assert native.value(old, (0, 0, 0)) == -2
        points = obj.ViewObject.Proxy._coordinates
        assert points.point.getNum() > 0
        obj.LeftRadius = 3
        doc.recompute()
        assert native.value(obj.Proxy.native_faces()[0], (0, 0, 0)) == -3
        assert native.value(old, (0, 0, 0)) == -2, "recompute mutated an earlier snapshot"
        assert obj.ViewObject.Proxy._coordinates is points
        obj.Operation = "Trim"
        doc.recompute()
        assert obj.isValid() and obj.NativeFaceCount == 1
        trimmed = obj.Proxy.native_faces()[0]
        try:
            native.dumps(trimmed)
        except NotImplementedError:
            pass
        else:
            raise AssertionError("trim persistence silently lost topology")
        for mode in ("Common", "Fuse", "Cut"):
            obj.Operation = mode
            doc.recompute()
            assert obj.isValid() and obj.NativeFaceCount == 2, obj.BackendStatus
        assert obj.DisplayErrorBound <= .1 and points.point.getNum() > 0
        name = obj.Name
        with tempfile.TemporaryDirectory(prefix="implicit-inprocess-") as directory:
            filename = os.path.join(directory, "native.FCStd")
            doc.saveAs(filename)
            with zipfile.ZipFile(filename) as saved:
                assert "_ImplicitOCCT" not in saved.read("Document.xml").decode()
                assert not any(n.endswith((".brep", ".brp")) for n in saved.namelist())
            App.closeDocument(doc.Name)
            doc = App.openDocument(filename)
            doc.recompute()
            obj = doc.getObject(name)
            assert obj.isValid() and str(obj.Backend) == "InProcess", obj.BackendStatus
            assert len(obj.Proxy.native_faces()) == 2 and obj.ViewObject.Proxy._coordinates.point.getNum() > 0
        points = obj.ViewObject.Proxy._coordinates
        obj.LeftRadius = -1
        try:
            obj.Proxy.execute(obj)
        except (ValueError, RuntimeError):
            pass
        else:
            raise AssertionError("invalid native definition succeeded")
        assert obj.Proxy._mesh is None and obj.Proxy._native_faces is None
        assert obj.NativeFaceCount == 0 and points.point.getNum() == 0
        obj.LeftRadius = 2
        doc.recompute()
        assert obj.isValid() and obj.Proxy.native_faces()
        App.closeDocument(doc.Name)
        assert native.value(old, (0, 0, 0)) == -2, "document close invalidated owned geometry"
        assert not any("libTK" in line and ".so.7." in line
                       for line in Path("/proc/self/maps").read_text().splitlines())
    finally:
        ImplicitNative.subprocess.run = original
    print("native implicit in-process face GUI smoke test passed", flush=True)
    Gui.getMainWindow().close()


try:
    main()
except BaseException:
    traceback.print_exc()
    os._exit(1)
