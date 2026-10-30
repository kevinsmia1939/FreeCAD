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
print("native implicit cylinder property smoke test passed", flush=True)
