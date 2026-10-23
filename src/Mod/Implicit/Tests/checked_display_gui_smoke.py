# SPDX-License-Identifier: LGPL-2.1-or-later
"""Checked upload buffers, cache invalidation, failed-preview repair and restore."""
import os
import tempfile
import traceback
import time
import FreeCAD as App
import FreeCADGui as Gui
import ImplicitMixed
import ImplicitSolid
import ImplicitOCCT as native
from pivy import coin
from PySide import QtCore


def wait_display(obj):
    deadline = time.monotonic() + 90
    while obj.ViewObject.Proxy._display_pending:
        assert time.monotonic() < deadline, obj.ViewObject.SurfacePreviewStatus
        loop = QtCore.QEventLoop()
        QtCore.QTimer.singleShot(20, loop.quit)
        loop.exec()


def check(obj):
    Gui.updateGui()
    wait_display(obj)
    view = obj.ViewObject.Proxy
    mesh = view._mesh
    assert obj.ViewObject.DisplayProximityChecked, obj.ViewObject.SurfacePreviewStatus
    assert "Local binary32" in obj.ViewObject.SurfacePreviewStatus
    assert mesh["display_checks"]["boundary_proximity_resolved"]
    assert mesh["display_checks"]["triangle_contacts_clear"]
    assert not mesh["solid_validated"] and not mesh["surface_coverage_verified"]
    # Inspect the actual uploaded SoCoordinate3, not just Python cache metadata.
    find = coin.SoSearchAction()
    find.setNode(view._elements["NativeFace1"])
    find.apply(obj.ViewObject.RootNode)
    group = find.getPath().getNodeFromTail(1)
    coords = group.getChild(0)
    used = sorted({i for tri in mesh["implicit_triangles"] for i in tri})
    assert [tuple(p) for p in coords.point.getValues()] == [tuple(mesh["vertices"][i]) for i in used]
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(obj, "NativeFace1")
    selected = Gui.Selection.getSelectionEx()
    assert selected and selected[0].SubObjects
    return mesh


def main():
    Gui.activateWorkbench("ImplicitModelingWorkbench")
    doc = App.newDocument("CheckedDisplayGUI")
    doc.UndoMode = 1
    field = doc.addObject("Implicit::Feature", "Gyroid")
    field.Function, field.Period, field.IsoValue = "Gyroid", 10, 0
    field.DomainMin, field.DomainMax = (0, 0, 0), (10, 10, 10)
    box = doc.addObject("Part::Box", "Box")
    box.Length = box.Width = box.Height = 10
    doc.recompute()
    source = ImplicitMixed.create(field, box, corner_policy="Regularized")
    obj = ImplicitSolid.create(source)
    field.ViewObject.Visibility = box.ViewObject.Visibility = source.ViewObject.Visibility = False
    assert not obj.ViewObject.DisplayProximityChecked
    obj.ViewObject.CheckSurfaceDisplay = True
    first = check(obj)
    checked_extract = native.start_surface_job
    def forbidden(*_args):
        raise AssertionError("unexpected display extraction")
    native.start_surface_job = forbidden
    try:
        obj.ViewObject.ShowBoundaryEdges = False
        assert check(obj) is first  # Visibility/camera changes reuse checked buffers.
        Gui.activeDocument().activeView().viewAxonometric()
        Gui.updateGui()
        assert check(obj) is first
        view = obj.ViewObject.Proxy
        upload = view._face
        def broken_upload(*_args):
            raise ValueError("injected scene upload failure")
        view._face = broken_upload
        try:
            obj.ViewObject.ShowVertices = False
            assert not obj.ViewObject.DisplayProximityChecked
            assert view._mesh is None and not view._elements
            assert "failed display upload" in obj.ViewObject.SurfacePreviewStatus
        finally:
            view._face = upload
        # A changed extraction key must discard the old checked state.
        obj.ViewObject.SurfaceMaximumCells = 128
        wait_display(obj)
        assert not obj.ViewObject.DisplayProximityChecked and obj.ViewObject.Proxy._mesh is None
        assert "NativeFace1" not in obj.ViewObject.Proxy._elements
        assert obj.Geometry is not None and obj.SolidValidated
        assert "Unsupported/failed" in obj.ViewObject.SurfacePreviewStatus
    finally:
        native.start_surface_job = checked_extract
    obj.touch(); doc.recompute()
    second = check(obj)
    assert second is not first
    doc.openTransaction("Complement checked display")
    source.Operation = "BoxMinusField"
    doc.recompute(); doc.commitTransaction()
    assert check(obj) is not second
    doc.undo(); doc.recompute(); check(obj)
    doc.redo(); doc.recompute(); check(obj)
    obj.ViewObject.ShowImplicitSurface = False
    assert not obj.ViewObject.DisplayProximityChecked and obj.ViewObject.Proxy._mesh is None
    obj.ViewObject.ShowImplicitSurface = True
    check(obj)
    name = obj.Name
    record = native.dumps_mixed_solids(obj.Geometry)
    build = native.build_mixed_solids
    native.build_mixed_solids = forbidden
    try:
        with tempfile.TemporaryDirectory(prefix="implicit-checked-gui-") as directory:
            filename = os.path.join(directory, "checked.FCStd")
            Gui.Selection.clearSelection()
            doc.saveAs(filename)
            App.closeDocument(doc.Name)
            doc = App.openDocument(filename)
            doc.recompute()
            obj = doc.getObject(name)
            assert obj.ViewObject.CheckSurfaceDisplay
            check(obj)  # New transient checks, not a saved proof flag/cache.
            assert native.dumps_mixed_solids(obj.Geometry) == record
            assert not obj.SolidValidated
            App.closeDocument(doc.Name)
    finally:
        native.build_mixed_solids = build
    print("native implicit checked display GUI smoke test passed", flush=True)


try:
    main()
except BaseException:
    traceback.print_exc()
    os._exit(1)
finally:
    Gui.getMainWindow().close()
