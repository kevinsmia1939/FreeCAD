# SPDX-License-Identifier: LGPL-2.1-or-later
"""Schema-2 native corner graph survives real FCStd/property transactions."""
import os
import tempfile
import traceback
import FreeCAD as App
import Implicit
import ImplicitOCCT as native
import Part


def main():
    face = native.gyroid(10, 0, (0, 0, 0), (10, 10, 10))
    box = Part.makeBox(10, 10, 10)
    common = native.mixed_box(face, box, corner_policy="regularized")
    cut = native.mixed_box(face, box, "box_minus_field", corner_policy="regularized")
    record = native.dumps_mixed(common["boundary_handle"])
    assert record.startswith("OCCT_IMPLICIT_BOX_TOPOLOGY 2 ")
    restored = native.loads_mixed(record)
    assert restored["edge_vertices"] == common["edge_vertices"]
    assert restored["vertex_points"] == common["vertex_points"]
    assert restored["seams"] == common["seams"]
    assert not restored["seam_bound_verified"] and not restored["solid_validated"]
    doc = App.newDocument("CornerPersistence")
    doc.UndoMode = 1
    obj = doc.addObject("Implicit::NativeFeaturePython", "Boundary")
    obj.Geometry = common["boundary_handle"]
    assert "Shape" not in obj.PropertiesList
    geometry = Implicit.nativeGeometry(obj)
    assert geometry.countSubElements("Edge") == 30
    assert geometry.countSubElements("Vertex") == 19
    assert obj.getSubObject("Edge1") is not None
    assert obj.getSubObject("Vertex1") is not None
    common_reference = ";" + geometry.getElementName("Edge1", 1) + ".Edge1"
    assert obj.getSubObject(common_reference, retType=1) == obj
    doc.openTransaction("Complement regularized material")
    obj.Geometry = cut["boundary_handle"]
    doc.commitTransaction()
    doc.undo()
    assert native.inspect_mixed(obj.Geometry)["excluded_corner_contacts"] == [(0., 0., 0.)]
    assert obj.getSubObject(common_reference, retType=1) == obj
    doc.redo()
    assert native.inspect_mixed(obj.Geometry)["excluded_corner_contacts"] == [(10., 10., 10.)]
    assert obj.getSubObject(common_reference, retType=1) is None
    cut_geometry = Implicit.nativeGeometry(obj)
    cut_reference = ";" + cut_geometry.getElementName("Vertex1", 1) + ".Vertex1"
    link = doc.addObject("App::FeaturePython", "Attachment")
    link.addProperty("App::PropertyLinkSub", "Reference")
    link.Reference = (obj, ["Vertex1"])
    transfer = doc.addObject("Implicit::NativeFeaturePython", "Transfer")
    transfer.restorePropertyContent("Geometry", obj.dumpPropertyContent("Geometry"))
    assert native.inspect_mixed(transfer.Geometry)["corner_policy"] == "regularized"
    assert not native.inspect_mixed(transfer.Geometry)["seam_bound_verified"]
    # A malformed assignment cannot replace the currently owned graph.
    try:
        transfer.Geometry = record + "trailing"
    except (ValueError, RuntimeError):
        pass
    else:
        raise AssertionError("corrupt corner topology accepted")
    assert native.inspect_mixed(transfer.Geometry)["excluded_corner_contacts"] == [(10., 10., 10.)]
    with tempfile.TemporaryDirectory(prefix="implicit-corner-io-") as directory:
        filename = os.path.join(directory, "corner.FCStd")
        doc.recompute()
        doc.saveAs(filename)
        App.closeDocument(doc.Name)
        original = native.mixed_box

        def forbidden(*args, **kwargs):
            raise AssertionError("saved topology must not be rebuilt numerically")

        native.mixed_box = forbidden
        try:
            reopened = App.openDocument(filename)
            reopened.recompute()
            saved = native.inspect_mixed(reopened.Boundary.Geometry)
            assert saved["corner_policy"] == "regularized"
            assert saved["exact_corner_count"] == 8
            assert saved["corner_contour_ends"] == saved["planar_corner_contacts"] == 12
            assert saved["excluded_corner_contacts"] == [(10., 10., 10.)]
            assert saved["edge_vertices"] == cut["edge_vertices"]
            assert not saved["seam_bound_verified"] and not saved["solid_validated"]
            assert reopened.Boundary.getSubObject("Vertex1") is not None
            assert reopened.Boundary.getSubObject(cut_reference, retType=1) == reopened.Boundary
            assert reopened.Boundary.getSubObject(common_reference, retType=1) is None
            target, names = reopened.Attachment.Reference
            assert target == reopened.Boundary
            assert target.getSubObject(names[0], retType=1) == target
            owned = reopened.Boundary.Geometry
            App.closeDocument(reopened.Name)
        finally:
            native.mixed_box = original
    assert native.inspect_mixed(owned)["corner_policy"] == "regularized"
    assert native.inspect_mixed(common["boundary_handle"])["seam_bound_verified"]
    print("native implicit corner persistence smoke test passed", flush=True)


try:
    main()
except BaseException:
    traceback.print_exc()
    os._exit(1)
