# SPDX-License-Identifier: LGPL-2.1-or-later
"""Native graph property save/restore, unverified state and transaction ownership."""
import math
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
    if App.GuiUp:
        import FreeCADGui as Gui
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
    doc.undo()
    assert obj.GeometryState == "Unverified"
    assert not native.inspect_stored_cylinder_solid(obj.Geometry)["solid_validated"]
    doc.redo()
    assert obj.GeometryState == "Ready"
    assert native.inspect_qualified_stored_cylinder_solid(obj.Geometry)["solid_validated"]
    App.closeDocument(doc.Name)
    assert snapshot.countSubElements("Vertex") == 3
    assert len(snapshot.getLines(.01)[1]) == len(segments)
print("native implicit cylinder property smoke test passed", flush=True)
