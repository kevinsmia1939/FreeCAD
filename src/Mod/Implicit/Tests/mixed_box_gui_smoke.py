# SPDX-License-Identifier: LGPL-2.1-or-later
import os
import tempfile
import traceback
import FreeCAD as App
import FreeCADGui as Gui
import ImplicitMixed
import ImplicitOCCT as native


def main():
    Gui.activateWorkbench("NativeImplicitWorkbench")
    assert "Implicit_OCCTMixedCommon" in Gui.listCommands()
    assert "Implicit_OCCTMixedBoxMinusField" in Gui.listCommands()
    obj = ImplicitMixed.demo()
    doc = obj.Document
    view = obj.ViewObject.Proxy
    caps, seams = view._coordinates, view._seam_coordinates
    assert caps.point.getNum() > 0 and seams.point.getNum() > 0
    old = obj.Proxy.native_boundary()["implicit_face"]
    old_region = obj.Proxy.native_boundary()["boundary_handle"]
    assert obj.Proxy.classify((0, 0, 2))["state"] == "inside"
    obj.Operation = "BoxMinusField"
    doc.recompute()
    assert obj.isValid() and obj.PlanarCapCount == 1
    assert obj.Proxy.classify((0, 0, 2))["state"] == "outside"
    assert view._coordinates is caps and view._seam_coordinates is seams
    assert caps.point.getNum() > 0 and seams.point.getNum() > 0
    with tempfile.TemporaryDirectory(prefix="implicit-mixed-gui-") as directory:
        filename = os.path.join(directory, "mixed.FCStd")
        name = obj.Name
        doc.saveAs(filename)
        App.closeDocument(doc.Name)
        doc = App.openDocument(filename)
        doc.recompute()
        obj = doc.getObject(name)
        assert obj.isValid() and obj.Proxy.native_boundary()["seam_count"] == 1
        view = obj.ViewObject.Proxy
        assert view._coordinates.point.getNum() > 0 and view._seam_coordinates.point.getNum() > 0
    obj.Field.IsoValue = 0
    doc.recompute()
    assert obj.isValid() and obj.BoxEdgeRootCount > 0, obj.BackendStatus
    assert view._coordinates.point.getNum() > 0 and view._seam_coordinates.point.getNum() > 0
    obj.MaximumCells = 4
    try:
        obj.Proxy.execute(obj)
    except (ValueError, NotImplementedError):
        pass
    else:
        raise AssertionError("unresolved sections returned a successful boundary")
    assert view._coordinates.point.getNum() == 0 and view._seam_coordinates.point.getNum() == 0
    assert obj.Proxy._boundary is None
    obj.Field.IsoValue = 1.45
    obj.MaximumCells = 512
    doc.recompute()
    assert obj.isValid() and obj.SeamCount == 1
    other = ImplicitMixed.demo(open_contours=True)
    assert other.isValid() and other.BoxEdgeRootCount > 4
    assert other.SeamGeometricBound <= .1
    snapshot = other.Proxy.native_boundary()
    restored = native.loads_mixed(native.dumps_mixed(snapshot["boundary_handle"]))
    assert restored["box_edge_root_count"] == other.BoxEdgeRootCount
    assert restored["seam_bound_verified"] is False and restored["seams"]
    query = other.Proxy.classify((0, 0, 0))
    assert query["state"] == "near_boundary" and query["has_boundary_witness"]
    assert query["witness_bracket_width"] <= .1 / 256
    App.closeDocument(other.Document.Name)
    assert native.classify_mixed(restored["boundary_handle"], (0, 0, 0))["state"] == "near_boundary"
    App.closeDocument(doc.Name)
    assert native.value(old, (1, 1, 1)) > -1
    assert native.classify_mixed(old_region, (0, 0, 2))["state"] == "inside"
    print("native implicit mixed box GUI smoke test passed", flush=True)
    Gui.getMainWindow().close()


try:
    main()
except BaseException:
    traceback.print_exc()
    os._exit(1)
