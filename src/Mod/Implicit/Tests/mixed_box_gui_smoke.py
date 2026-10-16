# SPDX-License-Identifier: LGPL-2.1-or-later
import os
import tempfile
import traceback
import FreeCAD as App
import FreeCADGui as Gui
import ImplicitMixed
import ImplicitOCCT as native
import Implicit


def check_subelements(obj):
    from pivy import coin
    view = obj.ViewObject.Proxy
    assert len(view._cap_nodes) == obj.PlanarCapCount
    assert len(view._seam_nodes) == obj.SeamCount
    geometry = Implicit.nativeGeometry(obj)
    for prefix, nodes in (("Cap", view._cap_nodes), ("Seam", view._seam_nodes)):
        for index, node in enumerate(nodes, 1):
            name = prefix + str(index)
            path = coin.SoPath()
            obj.ViewObject.getDetailPath(name, path)
            assert path.getLength() > 0 and path.getTail() == node
            mapped = ";" + geometry.getElementName(name, 1) + "." + name
            mapped_path = coin.SoPath()
            obj.ViewObject.getDetailPath(mapped, mapped_path)
            assert mapped_path.getLength() > 0 and mapped_path.getTail() == node
            assert geometry.getLinesFromSubElement(prefix, index)[0]
    path = coin.SoPath()
    obj.ViewObject.getDetailPath("Cap999999", path)
    assert path.getLength() == 0
    # A real Coin ray hit on a cap must resolve to the complete native cap,
    # not the triangle index of its disposable tessellation.
    cap = obj.Proxy._mesh["faces"][0]
    triangle = cap["triangles"][0]
    center = sum((App.Vector(cap["vertices"][i]) for i in triangle), App.Vector()) / 3
    normal = App.Vector(cap["normals"][triangle[0]])
    pick = coin.SoRayPickAction(coin.SbViewportRegion(512, 512))
    pick.setPickAll(True)
    pick.setRay(coin.SbVec3f(*(center + normal * 10)), coin.SbVec3f(*(-normal)), 0., 20.)
    pick.apply(obj.ViewObject.RootNode)
    names = [obj.ViewObject.getElementPicked(hit) for hit in pick.getPickedPointList()]
    assert "Cap1" in names, names
    seam = obj.Proxy._section["curves"][0]["points"]
    a, b = App.Vector(seam[0]), App.Vector(seam[1])
    midpoint = (a + b) * .5
    direction = (b - a).cross(App.Vector(1, 2, 3)).normalize()
    pick.setRay(coin.SbVec3f(*(midpoint + direction)), coin.SbVec3f(*(-direction)), 0., 2.)
    pick.apply(obj.ViewObject.RootNode)
    names = [obj.ViewObject.getElementPicked(hit) for hit in pick.getPickedPointList()]
    assert "Seam1" in names, names
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(obj, "Cap1")
    Gui.Selection.addSelection(obj, "Seam1")
    selected = Gui.Selection.getSelectionEx()
    assert selected and set(selected[0].SubElementNames) == {"Cap1", "Seam1"}
    assert len(selected[0].SubObjects) == 2
    for element in selected[0].SubObjects:
        assert element.getElementTypes() == ["Element"]
        assert element.getLines(.1)[0]
    return geometry


def main():
    Gui.activateWorkbench("NativeImplicitWorkbench")
    assert "Implicit_OCCTMixedCommon" in Gui.listCommands()
    assert "Implicit_OCCTMixedBoxMinusField" in Gui.listCommands()
    obj = ImplicitMixed.demo()
    doc = obj.Document
    view = obj.ViewObject.Proxy
    caps, seams = view._coordinates, view._seam_coordinates
    assert caps.point.getNum() > 0 and seams.point.getNum() > 0
    retained_geometry = check_subelements(obj)
    # App::Link must render/pick the native target and extract its placed
    # selected geometry without inventing a Part shape or applying pose twice.
    from pivy import coin
    instance = doc.addObject("App::Link", "NativeInstance")
    instance.LinkedObject = obj
    instance.LinkTransform = True
    instance.LinkPlacement = App.Placement(App.Vector(11, 2, -3), App.Rotation(17, 0, 0))
    doc.recompute()
    Gui.updateGui()
    cap = obj.Proxy._mesh["faces"][0]
    triangle = cap["triangles"][0]
    center = sum((App.Vector(cap["vertices"][i]) for i in triangle), App.Vector()) / 3
    normal = instance.LinkPlacement.Rotation.multVec(App.Vector(cap["normals"][triangle[0]]))
    center = instance.LinkPlacement.multVec(center)
    pick = coin.SoRayPickAction(coin.SbViewportRegion(512, 512))
    pick.setPickAll(True)
    pick.setRay(coin.SbVec3f(*(center + normal * 10)), coin.SbVec3f(*(-normal)), 0., 20.)
    pick.apply(instance.ViewObject.RootNode)
    names = [instance.ViewObject.getElementPicked(hit) for hit in pick.getPickedPointList()]
    assert "Cap1" in names, names
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(instance, "Cap1")
    linked_selection = Gui.Selection.getSelectionEx()
    assert len(linked_selection) == 1 and len(linked_selection[0].SubObjects) == 1
    linked_geometry = linked_selection[0].SubObjects[0]
    expected = [instance.LinkPlacement.multVec(p)
                for p in retained_geometry.getLinesFromSubElement("Cap", 1)[0]]
    actual = linked_geometry.getLines(.1)[0]
    assert len(actual) == len(expected)
    assert all((a - b).Length < 1e-10 for a, b in zip(actual, expected))
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(instance)
    whole_selection = Gui.Selection.getSelectionEx()[0]
    assert not whole_selection.SubElementNames and not whole_selection.SubObjects
    whole_geometry = whole_selection.Object.getSubObject("")
    assert whole_geometry.getElementTypes() == ["NativeFace", "Cap", "Seam"]
    expected = [instance.LinkPlacement.multVec(p) for p in retained_geometry.getLines(.1)[0]]
    actual = whole_geometry.getLines(.1)[0]
    assert len(actual) == len(expected)
    assert all((a - b).Length < 1e-10 for a, b in zip(actual, expected))
    placed_point = tuple(instance.LinkPlacement.multVec(App.Vector(0, 0, 2)))
    classification = Implicit.classifyNative(whole_geometry, placed_point)
    assert classification["state"] == "inside" and classification["solid_validated"] is False
    assert classification["placement_error_bound"] < .1
    doc.removeObject(instance.Name)
    retained_name = ";" + retained_geometry.getElementName("Cap1", 1) + ".Cap1"
    old = obj.Proxy.native_boundary()["implicit_face"]
    old_region = obj.Proxy.native_boundary()["boundary_handle"]
    assert obj.Proxy.classify((0, 0, 2))["state"] == "inside"
    obj.Operation = "BoxMinusField"
    doc.recompute()
    assert obj.isValid() and obj.PlanarCapCount == 1
    assert obj.Proxy.classify((0, 0, 2))["state"] == "outside"
    assert not Gui.Selection.getSelectionEx()
    from pivy import coin
    stale_path = coin.SoPath()
    obj.ViewObject.getDetailPath(retained_name, stale_path)
    assert stale_path.getLength() == 0
    check_subelements(obj)
    assert view._coordinates is caps and view._seam_coordinates is seams
    assert caps.point.getNum() > 0 and seams.point.getNum() > 0
    with tempfile.TemporaryDirectory(prefix="implicit-mixed-gui-") as directory:
        filename = os.path.join(directory, "mixed.FCStd")
        name = obj.Name
        doc.saveAs(filename)
        build = native._mixed_box
        def forbidden(*_args, **_kwargs):
            raise AssertionError("GUI topology restore attempted numerical rebuilding")
        native._mixed_box = forbidden
        try:
            App.closeDocument(doc.Name)
            doc = App.openDocument(filename)
            obj = doc.getObject(name)
            assert obj.ViewObject.Proxy._coordinates.point.getNum() > 0
            doc.recompute()
        finally:
            native._mixed_box = build
        assert obj.isValid() and obj.Proxy.native_boundary()["seam_count"] == 1
        assert obj.Proxy.native_boundary()["seam_bound_verified"] is False
        view = obj.ViewObject.Proxy
        assert view._coordinates.point.getNum() > 0 and view._seam_coordinates.point.getNum() > 0
        check_subelements(obj)
    obj.Field.IsoValue = 0
    doc.recompute()
    assert obj.isValid() and obj.BoxEdgeRootCount > 0, obj.BackendStatus
    assert view._coordinates.point.getNum() > 0 and view._seam_coordinates.point.getNum() > 0
    check_subelements(obj)
    obj.MaximumCells = 4
    try:
        obj.Proxy.execute(obj)
    except (ValueError, NotImplementedError):
        pass
    else:
        raise AssertionError("unresolved sections returned a successful boundary")
    assert view._coordinates.point.getNum() == 0 and view._seam_coordinates.point.getNum() == 0
    assert obj.Proxy._boundary is None
    assert not view._cap_nodes and not view._seam_nodes
    assert not Gui.Selection.getSelectionEx()
    obj.Field.IsoValue = 1.45
    obj.MaximumCells = 512
    doc.recompute()
    assert obj.isValid() and obj.SeamCount == 1
    other = ImplicitMixed.demo(open_contours=True)
    assert other.isValid() and other.BoxEdgeRootCount > 4
    assert other.SeamGeometricBound <= .1
    check_subelements(other)
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
    assert retained_geometry.getLinesFromSubElement("Seam", 1)[0]
    print("native implicit mixed box GUI smoke test passed", flush=True)
    Gui.getMainWindow().close()


try:
    main()
except BaseException:
    traceback.print_exc()
    os._exit(1)
