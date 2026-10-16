# SPDX-License-Identifier: LGPL-2.1-or-later
"""Native hybrid boundaries, recipe persistence, live links and rejection guards."""
import os
import tempfile
import traceback
import FreeCAD as App
import Part
import ImplicitMixed
import ImplicitOCCT as native


def main():
    obj = ImplicitMixed.demo()
    doc = obj.Document
    assert obj.isValid(), obj.BackendStatus
    assert "Shape" not in obj.PropertiesList
    data = obj.Proxy.native_boundary()
    assert data["solid_validated"] is False
    assert data["inside_convention"] == "F<=0" and data["operation"] == "common"
    assert data["seam_count"] == 1 and len(data["planar_caps"]) == 6
    assert data["seam_geometric_bound"] <= .1
    assert all(cap.isValid() and cap.ShapeType == "Face" for cap in data["planar_caps"])
    assert not native.in_domain(data["implicit_face"], (0, 0, 0))
    old = data["implicit_face"]
    old_region = data["boundary_handle"]
    query = obj.Proxy.classify((0, 0, 2))
    assert query["state"] == "inside" and query["distance_lower_bound"] > .1
    assert query["solid_validated"] is False and query["has_boundary_witness"] is False
    query = native.classify_mixed(old_region, (-.33, 0, 2))
    assert query["state"] == "near_boundary" and query["has_boundary_witness"]
    assert query["witness_distance_upper_bound"] <= .1
    source_shape = obj.Box.Shape.exportBrepToString()
    obj.Operation = "BoxMinusField"
    doc.recompute()
    cut = obj.Proxy.native_boundary()
    assert obj.isValid() and len(cut["planar_caps"]) == 1
    assert obj.Proxy.classify((0, 0, 2))["state"] == "outside"
    assert native.classify_mixed(old_region, (0, 0, 2))["state"] == "inside"
    assert native.normal(old, (1, 1, 1.25))[0] == -native.normal(cut["implicit_face"], (1, 1, 1.25))[0]
    assert obj.Box.Shape.exportBrepToString() == source_shape
    obj.Field.IsoValue = 1.46
    doc.recompute()
    assert obj.isValid(), obj.BackendStatus
    assert native.value(old, (1, 1, 1)) != native.value(obj.Proxy.native_boundary()["implicit_face"], (1, 1, 1))
    obj.Box.Height = 2.6
    doc.recompute()
    assert obj.isValid(), obj.BackendStatus
    assert native.info(obj.Proxy.native_boundary()["implicit_face"])["maximum"][2] == 3.85
    name, box_name, field_name = obj.Name, obj.Box.Name, obj.Field.Name
    with tempfile.TemporaryDirectory(prefix="implicit-mixed-") as directory:
        filename = os.path.join(directory, "mixed.FCStd")
        doc.saveAs(filename)
        App.closeDocument(doc.Name)
        doc = App.openDocument(filename)
        doc.recompute()
        obj = doc.getObject(name)
        assert obj.isValid(), obj.BackendStatus
        assert obj.Field.Name == field_name and obj.Box.Name == box_name
        assert obj.Proxy.native_boundary()["seam_count"] == 1
        assert obj.Proxy.classify((0, 0, 2))["state"] == "outside"
    obj.Field.IsoValue = 0
    doc.recompute()
    assert obj.isValid(), obj.BackendStatus
    assert obj.BoxEdgeRootCount > 0
    assert obj.Proxy.native_boundary()["box_edge_root_count"] == obj.BoxEdgeRootCount
    assert obj.SeamGeometricBound <= .1
    obj.MaximumCells = 4
    # Explicit execute verifies error propagation without treating the expected
    # document recompute diagnostic as an unexpected smoke-test traceback.
    try:
        obj.Proxy.execute(obj)
    except (ValueError, NotImplementedError):
        pass
    else:
        raise AssertionError("unresolved low-budget sections succeeded")
    assert obj.Proxy._boundary is None and obj.Proxy._mesh is None
    assert obj.SeamCount == 0 and obj.SeamGeometricBound == 0
    try:
        obj.Proxy.classify((0, 0, 2))
    except RuntimeError:
        pass
    else:
        raise AssertionError("failed feature retained a queryable stale region")
    for handle, point, tolerance, error in (
            (old, (0, 0, 2), .1, TypeError),
            (old_region, (float("nan"), 0, 0), .1, ValueError),
            (old_region, (0, 0, 2), -1, ValueError)):
        try:
            native.classify_mixed(handle, point, tolerance)
        except error:
            pass
        else:
            raise AssertionError("invalid region query succeeded")
    for bad in (Part.makeCylinder(1, 2), Part.makePlane(1, 2)):
        try:
            native.mixed_box(native.gyroid(10, 1.45, (-5, -5, -5), (6, 6, 6)), bad)
        except (ValueError, NotImplementedError):
            pass
        else:
            raise AssertionError("non-box operand succeeded")
    try:
        native.mixed_box(native.gyroid(10, 1.45, (-5, -5, -5), (6, 6, 6)), obj.Box.Shape, "cut")
    except ValueError:
        pass
    else:
        raise AssertionError("ambiguous cut operand order was accepted")
    App.closeDocument(doc.Name)
    assert native.classify_mixed(old_region, (0, 0, 2))["state"] == "inside"
    assert native.value(old, (1, 1, 1)) > -1
    print("native implicit mixed box smoke test passed", flush=True)


try:
    main()
except BaseException:
    traceback.print_exc()
    os._exit(1)
