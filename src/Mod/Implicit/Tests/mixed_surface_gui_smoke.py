# SPDX-License-Identifier: LGPL-2.1-or-later
"""Opt-in native trim-conforming surface preview and semantic picking."""
import os
import tempfile
import traceback
import FreeCAD as App
import FreeCADGui as Gui
import ImplicitMixed
import ImplicitOCCT as native
from pivy import coin


def check_pick(obj):
    view = obj.ViewObject.Proxy
    mesh = view._surface_mesh
    assert mesh and mesh["mesh_closed"] and not mesh["solid_validated"]
    assert not mesh["surface_coverage_verified"]
    assert view._surface_faces.coordIndex.getNum() == len(mesh["implicit_triangles"]) * 4
    assert view._surface_normals.vector.getNum() == len(mesh["vertices"])
    binding = view._surface_root.getChild(2)
    assert binding.value.getValue() == coin.SoNormalBinding.PER_VERTEX_INDEXED
    triangle = mesh["implicit_triangles"][len(mesh["implicit_triangles"]) // 2]
    p, q, r = (App.Vector(*mesh["vertices"][i]) for i in triangle)
    center, normal = (p + q + r) / 3, (q - p).cross(r - p).normalize()
    action = coin.SoRayPickAction(coin.SbViewportRegion(512, 512))
    action.setPickAll(True)
    action.setRay(coin.SbVec3f(*(center + normal * .01)), coin.SbVec3f(*(-normal)), 0., .02)
    action.apply(obj.ViewObject.RootNode)
    names = [obj.ViewObject.getElementPicked(hit) for hit in action.getPickedPointList()]
    assert "NativeFace1" in names, names
    path = coin.SoPath()
    obj.ViewObject.getDetailPath("NativeFace1", path)
    assert path.getLength() and path.getTail() == view._surface_faces
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(obj, "NativeFace1")
    selection = Gui.Selection.getSelectionEx()
    assert selection and selection[0].SubElementNames == ("NativeFace1",)
    assert len(selection[0].SubObjects) == 1
    assert "NOT validated" in obj.ViewObject.SurfacePreviewStatus


def main():
    Gui.activateWorkbench("ImplicitModelingWorkbench")
    assert "Implicit_NativeTopologyDemo" in Gui.listCommands()
    for crossing in (False, True):
        if crossing:
            Gui.runCommand("Implicit_NativeTopologyDemo")
            obj = App.ActiveDocument.Objects[-1]
            check_pick(obj)
            assert obj.ViewObject.Proxy._edge_nodes and obj.ViewObject.Proxy._vertex_nodes
            obj.ViewObject.ShowImplicitSurface = False
        else:
            obj = ImplicitMixed.demo(open_contours=False)
        doc = obj.Document
        view = obj.ViewObject.Proxy
        assert not obj.ViewObject.ShowImplicitSurface and view._surface_mesh is None
        record = native.dumps_mixed(obj.Geometry)
        calls = []
        original = native.tessellate_mixed
        def counted(*args):
            calls.append(1)
            return original(*args)
        native.tessellate_mixed = counted
        try:
            obj.ViewObject.ShowImplicitSurface = True
            check_pick(obj)
            first = view._surface_mesh
            assert len(calls) == 1
            view.updateData(obj, "NativeRevision")
            Gui.activeDocument().activeView().viewAxonometric()
            Gui.activeDocument().activeView().fitAll()
            Gui.updateGui()
            assert len(calls) == 1 and view._surface_mesh is first
            for name in ("ShowVertices", "ShowBoundaryEdges"):
                setattr(obj.ViewObject, name, False)
                setattr(obj.ViewObject, name, True)
            assert len(calls) == 1 and view._surface_mesh is first, "display toggles remeshed geometry"
            assert native.dumps_mixed(obj.Geometry) == record
            obj.ViewObject.ShowImplicitSurface = False
            assert view._surface_mesh is None and view._surface_faces.coordIndex.getNum() == 0
            assert len(view._cap_nodes) == obj.PlanarCapCount
            obj.ViewObject.SurfaceMaximumCells = 7
            obj.ViewObject.ShowImplicitSurface = True
            assert view._surface_mesh is None and view._surface_faces.coordIndex.getNum() == 0
            assert "failed" in obj.ViewObject.SurfacePreviewStatus
            assert obj.Geometry is not None and obj.isValid()
            obj.ViewObject.SurfaceMaximumCells = 128
            check_pick(obj)
            obj.Operation = "BoxMinusField"
            doc.recompute()
            assert not Gui.Selection.getSelectionEx()
            check_pick(obj)
            assert view._surface_mesh is not first
        finally:
            native.tessellate_mixed = original
        with tempfile.TemporaryDirectory(prefix="implicit-surface-gui-") as directory:
            filename, name = os.path.join(directory, "surface.FCStd"), obj.Name
            doc.saveAs(filename)
            App.closeDocument(doc.Name)
            doc = App.openDocument(filename)
            Gui.updateGui()
            obj = doc.getObject(name)
            assert obj.ViewObject.ShowImplicitSurface
            check_pick(obj)
            assert obj.ViewObject.Proxy._surface_mesh["seam_bound_verified"] is False
            retained = obj.ViewObject.Proxy._surface_mesh
            obj.MaximumCells = 4
            try:
                obj.Proxy.execute(obj)
            except (ValueError, NotImplementedError):
                pass
            else:
                raise AssertionError("unresolved native boundary unexpectedly succeeded")
            assert obj.Geometry is None and obj.ViewObject.Proxy._surface_mesh is None
            assert obj.ViewObject.Proxy._surface_faces.coordIndex.getNum() == 0
            assert not Gui.Selection.getSelectionEx()
            assert retained["implicit_triangles"]
        App.closeDocument(doc.Name)
    print("native implicit mixed surface GUI smoke test passed")


try:
    main()
except Exception:
    traceback.print_exc()
finally:
    Gui.getMainWindow().close()
