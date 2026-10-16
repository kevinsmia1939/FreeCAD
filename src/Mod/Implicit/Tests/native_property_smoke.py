# SPDX-License-Identifier: LGPL-2.1-or-later
"""Native complex geometry ownership, FCStd topology, transactions and migration."""
import os
import io
import base64
import tempfile
import traceback
import zipfile
import xml.etree.ElementTree as ET
import FreeCAD as App
import Part
import Implicit
import ImplicitMixed
import ImplicitOCCT as native


def main():
    obj = ImplicitMixed.demo()
    doc = obj.Document
    doc.UndoMode = 1
    assert obj.TypeId == "Implicit::NativeFeaturePython"
    assert obj.getPropertyNameOfGeometry() == "Geometry"
    assert obj.getTypeIdOfProperty("Geometry") == "Implicit::PropertyNativeGeometry"
    assert obj.isDerivedFrom("App::GeoFeature") and "Shape" not in obj.PropertiesList
    assert native.classify_mixed(obj.getPropertyOfGeometry(), (0, 0, 2))["state"] == "inside"
    old = obj.Geometry
    geometry = Implicit.nativeGeometry(obj)
    assert geometry.getElementTypes() == ["NativeFace", "Cap", "Seam"]
    assert geometry.countSubElements("NativeFace") == 1
    assert geometry.countSubElements("Cap") == obj.PlanarCapCount
    assert geometry.countSubElements("Seam") == obj.SeamCount
    original_seams = native.inspect_mixed(obj.Geometry)["seams"]
    for index, expected in enumerate(original_seams, 1):
        points, lines = geometry.getLinesFromSubElement("Seam", index)
        assert [tuple(p) for p in points] == expected
        assert lines == [(i, i + 1) for i in range(len(points) - 1)]
    for index in range(1, obj.PlanarCapCount + 1):
        points, lines = geometry.getLinesFromSubElement("Cap", index)
        assert points and lines
    for kind, index in (("Cap", 0), ("Cap", obj.PlanarCapCount + 1), ("Face", 1)):
        try:
            geometry.getLinesFromSubElement(kind, index)
        except RuntimeError:
            pass
        else:
            raise AssertionError("unknown native subelement accepted")
    try:
        geometry.getFacesFromSubElement("NativeFace", 1)
    except RuntimeError:
        pass
    else:
        raise AssertionError("unimplemented native surface mesh returned silently")
    roundtrip = native.loads_mixed(native.dumps_mixed(obj.Geometry))
    assert roundtrip["seams"] == original_seams
    obj.Operation = "BoxMinusField"
    doc.recompute()
    cut = obj.Geometry
    assert native.classify_mixed(old, (0, 0, 2))["state"] == "inside"
    assert native.classify_mixed(cut, (0, 0, 2))["state"] == "outside"
    slot = doc.addObject("Implicit::NativeFeaturePython", "Snapshot")
    assert slot.Geometry is None
    slot.Geometry = old
    doc.openTransaction("Change native geometry")
    slot.Geometry = cut
    doc.commitTransaction()
    doc.undo()
    assert native.classify_mixed(slot.Geometry, (0, 0, 2))["state"] == "inside"
    doc.redo()
    assert native.classify_mixed(slot.Geometry, (0, 0, 2))["state"] == "outside"
    for bad in (Part.makeBox(1, 1, 1), "not a topology record"):
        try:
            slot.Geometry = bad
        except (TypeError, ValueError):
            pass
        else:
            raise AssertionError("invalid native property assignment succeeded")
        assert native.classify_mixed(slot.Geometry, (0, 0, 2))["state"] == "outside"
    slot.Geometry = native.dumps_mixed(old)
    assert native.inspect_mixed(slot.Geometry)["seam_bound_verified"] is False
    # Core property/object transfer must retain topology without a recipe.
    transfer = doc.addObject("Implicit::NativeFeaturePython", "Transfer")
    transfer.restorePropertyContent("Geometry", slot.dumpPropertyContent("Geometry"))
    assert native.classify_mixed(transfer.Geometry, (0, 0, 2))["state"] == "inside"
    assert native.inspect_mixed(transfer.Geometry)["seam_bound_verified"] is False
    transfer.Geometry = cut
    transfer.restoreContent(slot.dumpContent())
    assert native.classify_mixed(transfer.Geometry, (0, 0, 2))["state"] == "inside"
    # Content forces XML-only output. Exercise the inline Base64 reader too,
    # by passing that XML through the ordinary content-restoration envelope.
    inline_xml = slot.Content
    element = ET.fromstring(inline_xml).find(".//NativeGeometry")
    assert element is not None and element.attrib.get("inline") == "1"
    assert base64.b64decode("".join(element.itertext())).startswith(
        b"OCCT_IMPLICIT_BOX_TOPOLOGY 1 ")
    inline_archive = io.BytesIO()
    with zipfile.ZipFile(inline_archive, "w") as archive:
        archive.writestr("Persistence.xml", "<Content>" + inline_xml + "</Content>")
    transfer.Geometry = cut
    transfer.restoreContent(bytearray(inline_archive.getvalue()))
    assert native.classify_mixed(transfer.Geometry, (0, 0, 2))["state"] == "inside"
    assert native.inspect_mixed(transfer.Geometry)["seam_bound_verified"] is False
    slot.Geometry = None
    transfer.restorePropertyContent("Geometry", slot.dumpPropertyContent("Geometry"))
    assert transfer.Geometry is None
    slot.Geometry = old
    # Cross-document copy is the core object-transfer path underlying GUI
    # copy/paste. The independent snapshot must outlive its source owner.
    copied_doc = App.newDocument("NativePropertyCopy")
    copied = copied_doc.copyObject(slot, False)
    assert copied.getPropertyNameOfGeometry() == "Geometry"
    assert native.classify_mixed(copied.Geometry, (0, 0, 2))["state"] == "inside"
    slot.Geometry = cut
    assert native.classify_mixed(copied.Geometry, (0, 0, 2))["state"] == "inside"
    App.closeDocument(copied_doc.Name)
    doc.removeObject(transfer.Name)
    slot.Geometry = native.dumps_mixed(old)
    name, snapshot_name = obj.Name, slot.Name
    build, gyroid = native._mixed_box, native.gyroid
    with tempfile.TemporaryDirectory(prefix="implicit-property-") as directory:
        filename = os.path.join(directory, "native.FCStd")
        doc.saveAs(filename)
        with zipfile.ZipFile(filename) as archive:
            payloads = [n for n in archive.namelist() if n.endswith(".nativegeo")]
            assert len(payloads) == 2, archive.namelist()
            assert all(archive.read(n).startswith(b"OCCT_IMPLICIT_BOX_TOPOLOGY 1 ") for n in payloads)
            assert b"Implicit::PropertyNativeGeometry" in archive.read("Document.xml")
            assert b"ImplicitOCCT.HybridBoundary.v1" not in archive.read("Document.xml")
        def forbidden(*_args, **_kwargs):
            raise AssertionError("FCStd topology restoration attempted numerical recipe rebuilding")
        native._mixed_box = native.gyroid = forbidden
        try:
            App.closeDocument(doc.Name)
            doc = App.openDocument(filename)
            obj, slot = doc.getObject(name), doc.getObject(snapshot_name)
            assert obj.Proxy.native_boundary()["seam_bound_verified"] is False
            doc.recompute()
            assert obj.isValid(), obj.BackendStatus
            assert obj.Proxy.classify((0, 0, 2))["state"] == "outside"
            assert native.classify_mixed(slot.Geometry, (0, 0, 2))["state"] == "inside"
        finally:
            native._mixed_box, native.gyroid = build, gyroid
        # Corrupt native topology is not silently replaced by a fresh recipe.
        corrupt_file = os.path.join(directory, "corrupt.FCStd")
        with zipfile.ZipFile(filename) as source, zipfile.ZipFile(corrupt_file, "w") as target:
            for item in source.infolist():
                target.writestr(item, b"invalid native topology" if item.filename.endswith(".nativegeo")
                               else source.read(item.filename))
        corrupted = App.openDocument(corrupt_file)
        bad_obj = corrupted.getObject(name)
        assert bad_obj.Geometry is None and bad_obj.Proxy._restore_failed
        try:
            bad_obj.Proxy.execute(bad_obj)
        except RuntimeError:
            pass
        else:
            raise AssertionError("corrupt topology was silently rebuilt")
        bad_obj.Proxy.rebuild(bad_obj)
        assert bad_obj.Geometry is not None
        App.closeDocument(corrupted.Name)
        # Structurally readable topology must not override unchanged field inputs.
        mismatch_file = os.path.join(directory, "mismatch.FCStd")
        with zipfile.ZipFile(filename) as source, zipfile.ZipFile(mismatch_file, "w") as target:
            for item in source.infolist():
                content = source.read(item.filename)
                if item.filename.endswith(".nativegeo"):
                    assert b"GYROID 10 " in content
                    content = content.replace(b"GYROID 10 ", b"GYROID 20 ", 1)
                target.writestr(item, content)
        mismatch = App.openDocument(mismatch_file)
        bad_obj = mismatch.getObject(name)
        try:
            bad_obj.Proxy.execute(bad_obj)
        except ValueError:
            pass
        else:
            raise AssertionError("stored geometry silently overrode unchanged field inputs")
        assert bad_obj.Proxy._restore_failed and bad_obj.Geometry is None
        App.closeDocument(mismatch.Name)
        obj.Field.IsoValue = 1.46
        doc.recompute()
        assert obj.isValid() and obj.Proxy.native_boundary()["seam_bound_verified"] is True
        obj.Field.Period = -1
        doc.recompute()
        assert not obj.isValid() and obj.Geometry is None
        assert obj.Proxy._boundary is None
        obj.Field.Period = 10
        doc.recompute()
        assert obj.isValid() and obj.Geometry is not None, obj.BackendStatus
        # Old recipe owners are migrated in place, preserving object/link names.
        legacy = doc.addObject("App::FeaturePython", "LegacyMixedBoundary")
        ImplicitMixed.MixedBoundary(legacy)
        legacy.Field, legacy.Box = obj.Field, obj.Box
        legacy.removeProperty("Geometry")
        legacy.removeProperty("InputFingerprint")
        legacy.MixedSchema = 1
        legacy_name = legacy.Name
        legacy_file = os.path.join(directory, "legacy.FCStd")
        doc.saveAs(legacy_file)
        App.closeDocument(doc.Name)
        doc = App.openDocument(legacy_file)
        doc.recompute()
        legacy = doc.getObject(legacy_name)
        assert legacy.TypeId == "App::FeaturePython" and legacy.isValid(), legacy.BackendStatus
        assert legacy.MixedSchema == 2 and legacy.Geometry is not None
        assert legacy.getTypeIdOfProperty("Geometry") == "Implicit::PropertyNativeGeometry"
    App.closeDocument(doc.Name)
    assert geometry.countSubElements("Cap") > 0
    assert geometry.getLinesFromSubElement("Seam", 1)[0]
    assert native.classify_mixed(old, (0, 0, 2))["state"] == "inside"
    # The multi-face, open-contour fixture exposes the distinction between
    # tracing order and stored wire-edge order. Every SeamN must survive I/O.
    crossing = ImplicitMixed.demo(open_contours=True)
    crossing_doc = crossing.Document
    before = Implicit.nativeGeometry(crossing)
    assert before.countSubElements("Seam") > 4
    preview = native.inspect_mixed(crossing.Geometry)["seams"]
    restored_owner = crossing_doc.addObject("Implicit::NativeFeaturePython", "RestoredSnapshot")
    restored_owner.Geometry = native.dumps_mixed(crossing.Geometry)
    after = Implicit.nativeGeometry(restored_owner)
    assert native.inspect_mixed(restored_owner.Geometry)["seams"] == preview
    for kind in ("NativeFace", "Cap", "Seam"):
        assert before.countSubElements(kind) == after.countSubElements(kind)
        for index in range(1, before.countSubElements(kind) + 1):
            a = before.getLinesFromSubElement(kind, index)
            b = after.getLinesFromSubElement(kind, index)
            assert a == b, (kind, index)
    App.closeDocument(crossing_doc.Name)
    print("native implicit geometry property smoke test passed", flush=True)


try:
    main()
except BaseException:
    traceback.print_exc()
    os._exit(1)
