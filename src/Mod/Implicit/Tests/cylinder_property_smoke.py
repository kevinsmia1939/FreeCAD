# SPDX-License-Identifier: LGPL-2.1-or-later
"""Native graph property save/restore, unverified state and transaction ownership."""
import math
import os
import tempfile
from pathlib import Path
import zipfile
import io
import xml.etree.ElementTree as ET
import FreeCAD as App
import Implicit
import ImplicitOCCT as native

source = native.gyroid(10, .21, (-10, -10, -10), (10, 10, 10))
geometry = native.check_cylinder_shell_geometry(
    source, (0, 0, 0), (0, 0, 1), (1, 0, 0), .5,
    (.27, .27 + 2 * math.pi), (-1.7, 1.3))
solid = native.build_cylinder_solid(geometry["geometry_handle"])
raw = native.loads_cylinder_solid(native.dumps_cylinder_solid(solid["solid_handle"]))
ready_geometry = native.qualify_stored_cylinder_geometry(raw["stored_solid_handle"])
ready = native.qualify_stored_cylinder_solid(ready_geometry["stored_geometry_handle"])
assert ready["solid_validated"], ready["solid_reason"]

with tempfile.TemporaryDirectory() as folder:
    path = str(Path(folder) / "Cylinder.FCStd")
    doc = App.newDocument("CylinderProperty")
    doc.UndoMode = 1
    obj = doc.addObject("Implicit::NativeCylinderFeature", "Cylinder")
    assert obj.Geometry is None and obj.GeometryState == "Empty"
    assert obj.getTypeIdOfProperty("Geometry") == "Implicit::PropertyNativeCylinderGeometry"
    assert not hasattr(obj, "Shape")
    obj.Geometry = ready["qualified_stored_solid_handle"]
    assert obj.GeometryState == "Ready"
    assert native.inspect_qualified_stored_cylinder_solid(obj.Geometry)["solid_validated"]
    source_record = native.dumps_cylinder_solid(obj.Geometry)
    snapshot = Implicit.nativeGeometry(obj)
    assert [snapshot.countSubElements(t) for t in ("Solid", "Shell", "Face", "Edge", "Vertex")] == [1, 1, 3, 4, 3]
    points, segments = snapshot.getLines(.01)
    vertices, normals = snapshot.getPoints(.01)
    assert len(vertices) == 3 and not normals
    assert len(points) > len(vertices) and segments
    assert all((points[i] - vertices[i]).Length < 1e-12 for i in range(3))
    degrees = [0] * len(points)
    for a, b in segments:
        assert a != b and 0 <= a < len(points) and 0 <= b < len(points)
        degrees[a] += 1
        degrees[b] += 1
    assert sorted(degrees[:3]) == [2, 3, 3], degrees[:3]
    assert all(degree == 2 for degree in degrees[3:])
    circles = 0
    for edge in range(1, 5):
        ep, el = snapshot.getLinesFromSubElement("Edge", edge)
        if max(p.z for p in ep) - min(p.z for p in ep) < 1e-10:
            circles += 1
            for a, b in el:
                middle = (ep[a] + ep[b]) * .5
                assert abs(.5 - math.hypot(middle.x, middle.y)) <= .01 + 1e-10
    assert circles == 2
    for accuracy in (0, -1, float("nan"), 1e-30):
        try:
            snapshot.getLines(accuracy)
        except RuntimeError:
            pass
        else:
            raise AssertionError("Invalid or unresolvable boundary deflection accepted")
    try:
        snapshot.getFaces(.01)
    except RuntimeError:
        pass
    else:
        raise AssertionError("Boundary lines were substituted for a surface mesh")
    assert native.dumps_cylinder_solid(obj.Geometry) == source_record
    for name in ("Face1", "Face3", "Edge1", "Vertex1"):
        selected = obj.getSubObject(name)
        assert selected is not None and selected.getElementTypes() == ["Element"], name
        assert selected.countSubElements("Element") == 1
        assert selected.getLines(.01)[0]
    assert obj.getSubObject("Face999") is None
    vertex_bounds = obj.getSubObject("Vertex1").BoundBox
    assert vertex_bounds.XLength == vertex_bounds.YLength == vertex_bounds.ZLength == 0
    preview = Implicit.cylinderPreview(obj, 8)
    assert preview["source_geometry_verified"] and preview["mesh_incidence_verified"]
    assert not preview["surface_distance_verified"]
    assert preview["native_vertex_count"] == 3 and len(preview["native_edges"]) == 4
    assert set(preview["native_faces"]) == {1, 2, 3}
    pp, tt = preview["points"], preview["triangles"]
    assert len(preview["corner_normals"]) == 3 * len(tt)
    assert all(abs(sum(v*v for v in normal) - 1) < 1e-10 for normal in preview["corner_normals"])
    assert all((App.Vector(*pp[i]) - vertices[i]).Length < 1e-12 for i in range(3))
    incidence = {}
    for triangle in tt:
        for i in range(3):
            a, b = triangle[i], triangle[(i+1) % 3]
            key = tuple(sorted((a, b)))
            count, orientation = incidence.get(key, (0, 0))
            incidence[key] = count + 1, orientation + (1 if a < b else -1)
    assert all(count == 2 and orientation == 0 for count, orientation in incidence.values())
    assert len(pp) - len(incidence) + len(tt) == 2
    boundary_nodes = {i for edge in preview["native_edges"] for i in edge}
    field_nodes = sorted({i for triangle, face in zip(tt, preview["native_faces"]) if face == 3 for i in triangle} - boundary_nodes)
    assert field_nodes
    wave = 2 * math.pi / 10
    for index in field_nodes[::max(1, len(field_nodes)//20)]:
        x, y, z = pp[index]
        low, high = -1.7, 1.3
        for _ in range(80):
            middle = (low + high) * .5
            value = (math.sin(wave*x)*math.cos(wave*y) + math.sin(wave*y)*math.cos(wave*middle)
                     + math.sin(wave*middle)*math.cos(wave*x) - .21)
            if value > 0:
                high = middle
            else:
                low = middle
        assert abs(z - (low + high)*.5) <= preview["root_point_bound"] + 1e-9
    assert native.dumps_cylinder_solid(obj.Geometry) == source_record
    for resolution in (-1, 0, 1, 65):
        try:
            Implicit.cylinderPreview(obj, resolution)
        except ValueError:
            pass
        else:
            raise AssertionError("Invalid preview resolution accepted")
    if App.GuiUp:
        import FreeCADGui as Gui
        from pivy import coin
        from ImplicitCylinder import attach_view
        renderer = attach_view(obj)
        assert renderer._mesh is not None, obj.ViewObject.PreviewState
        rgb = renderer._surface_material.diffuseColor.getValues()[0]
        assert all(abs(float(rgb[i]) - obj.ViewObject.SurfaceColor[i]) < 1e-6 for i in range(3))
        assert not obj.ViewObject.SurfaceDistanceVerified
        assert set(renderer._elements) == {"Face1", "Face2", "Face3", "Edge1", "Edge2", "Edge3", "Edge4", "Vertex1", "Vertex2", "Vertex3"}
        for name in renderer._elements:
            detail = coin.SoPath()
            obj.ViewObject.getDetailPath(name, detail)
            assert detail.getLength() > 0, name
        obj.ViewObject.PreviewResolution = 1
        assert renderer._mesh is None and obj.ViewObject.PreviewState.startswith("Failed")
        obj.ViewObject.PreviewResolution = 8
        assert renderer._mesh is not None, obj.ViewObject.PreviewState
        obj.ViewObject.Visibility = False
        assert renderer._mesh is None
        obj.ViewObject.Visibility = True
        assert renderer._mesh is not None, obj.ViewObject.PreviewState
        view = Gui.activeDocument().activeView()
        view.viewAxonometric()
        view.fitAll()
        Gui.updateGui()
        field_center = next(p for p in renderer._mesh["points"] if math.hypot(p[0], p[1]) < 1e-10 and -.5 < p[2] < .5)
        pixel = tuple(int(v) for v in view.getPointOnScreen(App.Vector(*field_center)))
        hits = view.getObjectsInfo(pixel) or []
        assert any(hit.get("Object") == obj.Name and hit.get("Component") == "Face3" for hit in hits), hits
        for kind in ("Edge", "Vertex"):
            found = False
            for index in range(1, snapshot.countSubElements(kind) + 1):
                name = kind + str(index)
                selected = obj.getSubObject(name)
                ep, el = selected.getLines(.01)
                target = ep[0] if kind == "Vertex" else (ep[el[0][0]] + ep[el[0][1]]) * .5
                x, y = view.getPointOnScreen(target)
                for dx, dy in ((0, 0), (1, 0), (-1, 0), (0, 1), (0, -1)):
                    infos = view.getObjectsInfo((int(x)+dx, int(y)+dy)) or []
                    if any(hit.get("Object") == obj.Name and hit.get("Component") == name for hit in infos):
                        found = True
                        break
                if found:
                    break
            assert found, "No actual native " + kind + " viewport hit"
        Gui.Selection.clearSelection()
        for name in ("Face3", "Edge1", "Vertex1"):
            Gui.Selection.addSelection(obj, name)
        selected = Gui.Selection.getSelectionEx()
        assert selected and set(selected[0].SubElementNames) == {"Face3", "Edge1", "Vertex1"}
        assert len(selected[0].SubObjects) == 3
        assert all(value.getElementTypes() == ["Element"] for value in selected[0].SubObjects)
        Gui.Selection.clearSelection()
        screenshot = os.environ.get("IMPLICIT_CYLINDER_PREVIEW_SCREENSHOT")
        if screenshot:
            Gui.updateGui()
            Gui.Selection.clearPreselection()
            view.saveImage(screenshot, 960, 720, "White")
        assert Gui.activeDocument().getObject(obj.Name) is not None
        Gui.Selection.addSelection(obj)
        assert Gui.Selection.getSelection() == [obj]
        Gui.Selection.clearSelection()
    record = native.dumps_cylinder_solid(obj.Geometry)
    transfer = doc.addObject("Implicit::NativeCylinderFeature", "Transfer")
    transfer.restorePropertyContent("Geometry", obj.dumpPropertyContent("Geometry"))
    assert transfer.GeometryState == "Unverified"
    xml = obj.Content
    element = ET.fromstring(xml).find(".//NativeCylinderGeometry")
    assert element is not None and element.attrib.get("inline") == "1"
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr("Persistence.xml", "<Content>" + xml + "</Content>")
    transfer.Geometry = None
    transfer.restoreContent(bytearray(payload.getvalue()))
    assert transfer.GeometryState == "Unverified"
    doc.removeObject(transfer.Name)
    for invalid in ("broken", source):
        try:
            obj.Geometry = invalid
        except (ValueError, TypeError, RuntimeError):
            pass
        else:
            raise AssertionError("Invalid geometry assignment accepted")
        assert obj.GeometryState == "Ready" and native.dumps_cylinder_solid(obj.Geometry) == record
    doc.recompute()
    doc.saveAs(path)
    with zipfile.ZipFile(path) as archive:
        names = [name for name in archive.namelist() if name.endswith(".nativecylinder")]
        assert len(names) == 1
        assert archive.read(names[0]).decode() == record
    App.closeDocument(doc.Name)
    doc = App.openDocument(path)
    doc.UndoMode = 1
    obj = doc.getObject("Cylinder")
    assert obj.GeometryState == "Unverified", obj.GeometryState
    assert obj.getSubObject("Face3") is None
    if App.GuiUp:
        assert obj.ViewObject.Proxy._mesh is None
    try:
        Implicit.cylinderPreview(obj)
    except ValueError:
        pass
    else:
        raise AssertionError("Unverified cylinder generated a preview")
    unverified_snapshot = Implicit.nativeGeometry(obj)
    assert unverified_snapshot.countSubElements("Edge") == 0
    try:
        unverified_snapshot.getLines(.01)
    except RuntimeError:
        pass
    else:
        raise AssertionError("Unverified cylinder exposed display boundaries")
    restored = native.inspect_stored_cylinder_solid(obj.Geometry)
    assert restored["topology_validated"]
    assert not restored["geometry_verified"] and not restored["solid_validated"]
    doc.recompute()
    assert obj.GeometryState == "Unverified"
    # Re-saving an unverified loaded graph preserves its actual payload.
    doc.saveAs(str(Path(folder) / "Unverified.FCStd"))
    fresh = native.qualify_stored_cylinder_geometry(obj.Geometry)
    qualified = native.qualify_stored_cylinder_solid(fresh["stored_geometry_handle"])
    doc.openTransaction("Requalify actual stored graph")
    obj.Geometry = qualified["qualified_stored_solid_handle"]
    doc.commitTransaction()
    assert obj.GeometryState == "Ready"
    if App.GuiUp:
        assert obj.ViewObject.Proxy._mesh is not None, obj.ViewObject.PreviewState
    doc.undo()
    assert obj.GeometryState == "Unverified"
    if App.GuiUp:
        assert obj.ViewObject.Proxy._mesh is None
    assert not native.inspect_stored_cylinder_solid(obj.Geometry)["solid_validated"]
    doc.redo()
    assert obj.GeometryState == "Ready"
    assert native.inspect_qualified_stored_cylinder_solid(obj.Geometry)["solid_validated"]
    App.closeDocument(doc.Name)
    assert snapshot.countSubElements("Vertex") == 3
    assert len(snapshot.getLines(.01)[1]) == len(segments)
print("native implicit cylinder property smoke test passed", flush=True)
