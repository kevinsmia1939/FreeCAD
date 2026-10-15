# SPDX-License-Identifier: LGPL-2.1-or-later
"""OCCT 8 worker -> OCCT 7 GUI: no native handles cross the process boundary."""
import os
import tempfile
import traceback
import FreeCAD as App
import FreeCADGui as Gui
import ImplicitNative


def main():
    document = App.newDocument("OCCTNativeBoundarySmoke")
    Gui.activateWorkbench("NativeImplicitWorkbench")
    Gui.runCommand("Implicit_OCCTTrim")
    obj = document.Objects[-1]
    assert obj.isValid() and obj.NativeFaceCount == 1, obj.BackendStatus
    assert obj.TypeId == "App::FeaturePython" and not hasattr(obj, "Shape")
    assert obj.Proxy._mesh["faces"][0]["trimmed"]
    provider = obj.ViewObject.Proxy
    coordinates = provider._coordinates
    initial = coordinates.point.getNum()
    assert initial > 0 and provider._faces.coordIndex.getNum() > 0
    assert 0 < obj.DisplayErrorBound <= .1
    obj.LeftRadius = 3
    obj.PlaneNormal = (1, 1, 1)
    obj.PlaneOffset = .7
    document.recompute()
    assert obj.isValid() and obj.ViewObject.Proxy._coordinates is coordinates
    assert coordinates.point.getNum() != initial
    for operation in ("Common", "Fuse", "Cut"):
        obj.LeftRadius = 2
        obj.Operation = operation
        document.recompute()
        assert obj.isValid() and obj.NativeFaceCount == 2, obj.BackendStatus
        assert [f["source"] for f in obj.Proxy._mesh["faces"]] == [0, 1]
    assert obj.Proxy._mesh["faces"][1]["reversed"]
    revision = obj.NativeRevision
    Gui.activeDocument().activeView().fitAll()
    Gui.activeDocument().activeView().viewAxonometric()
    Gui.updateGui()
    assert obj.NativeRevision == revision, "camera motion regenerated geometry"
    # Rejection clears stale display; exercise directly to avoid framework log
    # tracebacks for an intentionally unsupported tangency.
    obj.RightCenter = (4, 0, 0)
    try:
        obj.Proxy.execute(obj)
    except RuntimeError:
        pass
    else:
        raise AssertionError("tangent spheres were accepted")
    assert obj.Proxy._mesh is None and obj.NativeFaceCount == 0
    assert coordinates.point.getNum() == 0
    obj.RightCenter = (2, 0, 0)
    document.recompute()
    assert obj.isValid() and obj.NativeFaceCount == 2
    with tempfile.TemporaryDirectory(prefix="implicit-native-boundary-") as directory:
        filename = os.path.join(directory, "native.FCStd")
        document.saveAs(filename)
        name = obj.Name
        App.closeDocument(document.Name)
        document = App.openDocument(filename)
        document.recompute()
        restored = document.getObject(name)
        assert restored.NativeSchema == 1 and str(restored.Operation) == "Cut"
        assert restored.Proxy._mesh is not None and restored.isValid(), restored.BackendStatus
        assert restored.NativeFaceCount == 2 and restored.DisplayErrorBound <= .1
        Gui.updateGui()
        assert restored.ViewObject.Proxy._coordinates.point.getNum() > 0
        App.closeDocument(document.Name)
    print("native OCCT boundary GUI smoke test passed", flush=True)
    Gui.getMainWindow().close()


try:
    main()
except BaseException:
    traceback.print_exc()
    os._exit(1)
