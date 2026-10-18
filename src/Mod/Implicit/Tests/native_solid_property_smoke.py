# SPDX-License-Identifier: LGPL-2.1-or-later
"""Actual solid ComplexGeoData, property transactions and FCStd topology ownership."""
import base64
import io
import itertools
import os
import tempfile
import traceback
import zipfile
import xml.etree.ElementTree as ET
import FreeCAD as App
import Implicit
import ImplicitMixed
import ImplicitOCCT as native
import Part

TYPES = ["Solid", "Shell", "Face", "NativeFace", "Cap", "Seam", "Edge", "Vertex"]


def compare(a, b, tolerance=1e-10):
    assert len(a) == len(b)
    assert all((p - q).Length < tolerance for p, q in zip(a, b))


def check(owner, report):
    geometry = Implicit.nativeGeometry(owner)
    assert geometry.getElementTypes() == TYPES
    for kind, key in (("Solid", "solid_count"), ("Shell", "shell_count"), ("Face", "face_count"),
                      ("NativeFace", "implicit_face_count")):
        assert geometry.countSubElements(kind) == report[key], (kind, report)
    assert geometry.countSubElements("Cap") == report["face_count"] - report["implicit_face_count"]
    retained = []
    for kind in TYPES:
        for index in range(1, geometry.countSubElements(kind) + 1):
            name = kind + str(index)
            identity = geometry.getElementName(name, 1)
            assert identity.startswith("ImplicitSolidV1_")
            mapped = ";" + identity + "." + name
            points, lines = geometry.getLinesFromSubElement(kind, index)
            selected = owner.getSubObject(mapped)
            assert selected.getElementTypes() == ["Element"]
            actual, actual_lines = selected.getLines(.1)
            compare(actual, [owner.Placement.multVec(p) for p in points])
            assert actual_lines == lines
            assert selected.Placement == App.Placement()
            if kind == "Vertex":
                compare(selected.getPoints(.1)[0], actual)
                assert not selected.getPoints(.1)[1]
            if kind == "NativeFace":
                low, high = report["component_domains"][index - 1]
                corners = [owner.Placement.multVec(App.Vector(*p))
                           for p in itertools.product(*zip(low, high))]
                for axis in "xyz":
                    assert abs(getattr(selected.BoundBox, axis.upper() + "Min")
                               - min(getattr(p, axis) for p in corners)) < 1e-10
                    assert abs(getattr(selected.BoundBox, axis.upper() + "Max")
                               - max(getattr(p, axis) for p in corners)) < 1e-10
            if kind in ("Shell", "Solid"):
                assert selected.BoundBox.isValid(), "closed field components need bounds without wires"
            retained.append((selected, actual))
    return geometry, retained


def main():
    obj = ImplicitMixed.demo(open_contours=True)
    doc = obj.Document
    doc.UndoMode = 1
    result = native.build_mixed_solids(obj.Geometry)
    assert result["solid_validated"], result["reason"]
    first_handle = result["solid_handle"]
    owner = doc.addObject("Implicit::NativeSolidFeaturePython", "SolidSnapshot")
    assert owner.getPropertyNameOfGeometry() == "Geometry"
    assert owner.getTypeIdOfProperty("Geometry") == "Implicit::PropertyNativeSolidGeometry"
    assert "Shape" not in owner.PropertiesList and owner.Geometry is None
    assert Implicit.nativeGeometry(owner).getElementTypes() == TYPES
    owner.Geometry = result["solid_handle"]
    assert native.inspect_mixed_solids(owner.getPropertyOfGeometry())["solid_validated"]
    owner.Placement = App.Placement(App.Vector(13, -4, 7), App.Rotation(App.Vector(1, 2, 3), 37))
    geometry, retained = check(owner, result)
    attachment = doc.addObject("App::FeaturePython", "SolidAttachment")
    attachment.addProperty("App::PropertyLinkSubList", "References")
    attachment.References = [(owner, ["Solid1", "Shell1", "Face1", "NativeFace1", "Edge1", "Vertex1"])]
    references = [";" + geometry.getElementName(name, 1) + "." + name
                  for name in attachment.References[0][1]]
    assert all(owner.getSubObject(name, retType=1) == owner for name in references)
    whole = owner.getSubObject("")
    query = Implicit.classifyNative(whole, tuple(owner.Placement.multVec(App.Vector(20, 20, 20))))
    assert query["state"] == "outside" and query["solid_validated"]
    assert "union" in query["region_scope"]
    try:
        Implicit.classifyNative(owner.getSubObject("Solid1"), (0, 0, 0))
    except NotImplementedError:
        pass
    else:
        raise AssertionError("selected SolidN silently classified the whole source union")
    record = native.dumps_mixed_solids(owner.Geometry)
    doc.openTransaction("Clear native solid")
    owner.Geometry = None
    doc.commitTransaction()
    assert owner.getSubObject("Solid1") is None
    assert all(owner.getSubObject(name, retType=1) is None for name in references)
    doc.undo()
    assert native.inspect_mixed_solids(owner.Geometry)["solid_validated"]
    assert all(owner.getSubObject(name, retType=1) == owner for name in references)
    doc.redo()
    assert owner.Geometry is None
    doc.undo()
    for bad in (obj.Geometry, native.dumps_mixed(obj.Geometry), Part.makeBox(1, 1, 1), geometry):
        try:
            owner.Geometry = bad
        except (TypeError, ValueError):
            pass
        else:
            raise AssertionError("source boundary/Part/wrapper was accepted as solid geometry")
        assert native.dumps_mixed_solids(owner.Geometry) == record
    transfer = doc.addObject("Implicit::NativeSolidFeaturePython", "Transfer")
    transfer.restorePropertyContent("Geometry", owner.dumpPropertyContent("Geometry"))
    assert native.dumps_mixed_solids(transfer.Geometry) == record
    assert not native.inspect_mixed_solids(transfer.Geometry)["solid_validated"]
    inline_xml = owner.Content
    element = ET.fromstring(inline_xml).find(".//NativeSolidGeometry")
    assert element is not None and element.attrib.get("inline") == "1"
    assert base64.b64decode("".join(element.itertext())).startswith(b"OCCT_IMPLICIT_SOLIDS 1 ")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("Persistence.xml", "<Content>" + inline_xml + "</Content>")
    transfer.restoreContent(bytearray(buffer.getvalue()))
    assert native.dumps_mixed_solids(transfer.Geometry) == record
    for target, source, dump in ((owner, obj, native.dumps_mixed_solids),
                                  (obj, owner, native.dumps_mixed)):
        before = dump(target.Geometry)
        try:
            target.restorePropertyContent("Geometry", source.dumpPropertyContent("Geometry"))
        except (RuntimeError, ValueError, TypeError, OSError):
            pass
        else:
            raise AssertionError("cross-representation property content was accepted")
        assert dump(target.Geometry) == before
    instance = doc.addObject("App::Link", "SolidInstance")
    instance.LinkedObject = owner
    instance.LinkPlacement = App.Placement(App.Vector(-3, 11, -5), App.Rotation(0, 0, 41))
    for include_source in (False, True):
        instance.LinkTransform = include_source
        pose = instance.LinkPlacement.multiply(owner.Placement) if include_source else instance.LinkPlacement
        whole_instance = instance.getSubObject("")
        assert whole_instance.getElementTypes() == TYPES
        for kind in TYPES:
            for index in range(1, geometry.countSubElements(kind) + 1):
                name = kind + str(index)
                expected = [pose.multVec(p) for p in geometry.getLinesFromSubElement(kind, index)[0]]
                compare(instance.getSubObject(name).getLines(.1)[0], expected)
                compare(whole_instance.getLinesFromSubElement(kind, index)[0], expected)
    parent = doc.addObject("App::Part", "SolidContainer")
    parent.addObject(owner)
    parent.Placement = App.Placement(App.Vector(2, 3, 4), App.Rotation(13, 0, 0))
    pose = parent.Placement.multiply(owner.Placement)
    nested = parent.getSubObject(owner.Name + ".")
    assert nested.getElementTypes() == TYPES
    for kind in TYPES:
        for index in range(1, geometry.countSubElements(kind) + 1):
            points = geometry.getLinesFromSubElement(kind, index)[0]
            selected = parent.getSubObject(owner.Name + "." + kind + str(index))
            compare(selected.getLines(.1)[0], [pose.multVec(p) for p in points])
    copied_doc = App.newDocument("NativeSolidCopy")
    copied = copied_doc.copyObject(owner, False)
    assert copied.getTypeIdOfProperty("Geometry") == "Implicit::PropertyNativeSolidGeometry"
    assert native.dumps_mixed_solids(copied.Geometry) == record
    App.closeDocument(copied_doc.Name)
    with tempfile.TemporaryDirectory(prefix="implicit-solid-property-") as directory:
        filename = os.path.join(directory, "solid.FCStd")
        names = owner.Name, transfer.Name
        doc.saveAs(filename)
        with zipfile.ZipFile(filename) as archive:
            payloads = [n for n in archive.namelist() if n.endswith(".nativesolid")]
            assert len(payloads) == 2
            assert all(archive.read(n).startswith(b"OCCT_IMPLICIT_SOLIDS 1 ") for n in payloads)
        build = native.build_mixed_solids
        def forbidden(*_args):
            raise AssertionError("FCStd restore attempted a numerical solid rebuild")
        native.build_mixed_solids = forbidden
        try:
            App.closeDocument(doc.Name)
            doc = App.openDocument(filename)
            owner, transfer = (doc.getObject(n) for n in names)
            assert native.dumps_mixed_solids(owner.Geometry) == record
            assert not native.inspect_mixed_solids(owner.Geometry)["solid_validated"]
            restored = Implicit.nativeGeometry(owner)
            assert restored.getElementName("Solid1", 1) == geometry.getElementName("Solid1", 1)
            assert all(owner.getSubObject(name, retType=1) == owner for name in references)
            for target, subnames in doc.getObject("SolidAttachment").References:
                assert all(target.getSubObject(name, retType=1) == target for name in subnames)
            check(owner, native.inspect_mixed_solids(owner.Geometry))
        finally:
            native.build_mixed_solids = build
        corrupted_file = os.path.join(directory, "corrupt.FCStd")
        with zipfile.ZipFile(filename) as source, zipfile.ZipFile(corrupted_file, "w") as target:
            for item in source.infolist():
                target.writestr(item, b"invalid solid topology" if item.filename.endswith(".nativesolid")
                               else source.read(item.filename))
        corrupted = App.openDocument(corrupted_file)
        assert corrupted.getObject(names[0]).Geometry is None
        App.closeDocument(corrupted.Name)
    App.closeDocument(doc.Name)
    for selected, points in retained:
        compare(selected.getLines(.1)[0], points)
    # Multiple native components must not be disguised as the source's one face.
    doc = App.newDocument("NativeSolidComponents")
    owner = doc.addObject("Implicit::NativeSolidFeaturePython", "Islands")
    owner.Geometry = first_handle
    old_geometry = Implicit.nativeGeometry(owner)
    stale = ";" + old_geometry.getElementName("NativeFace1", 1) + ".NativeFace1"
    field = native.gyroid(10, 1.45, (-5, -5, -5), (16, 16, 6))
    for box, resolution in ((Part.makeBox(13.24, 3.28, 2.75, App.Vector(-.31, -.37, 1.25)), 64),
                             (Part.makeBox(2, 2, 2, App.Vector(.3, .3, .3)), 32)):
        for operation in ("common", "box_minus_field"):
            source = native.mixed_box(field, box, operation)
            result = native.build_mixed_solids(source["boundary_handle"], .1, resolution)
            assert result["solid_validated"], result["reason"]
            owner.Geometry = result["solid_handle"]
            check(owner, result)
            assert owner.getSubObject(stale, retType=1) is None
            assert Implicit.nativeGeometry(owner).getElementName(stale) == ""
            if resolution == 64:
                assert Implicit.nativeGeometry(owner).countSubElements("NativeFace") == 2
    for operation in ("common", "box_minus_field"):
        source = native.mixed_box(native.gyroid(10, 2, (-5, -5, -5), (16, 16, 6)),
                                  Part.makeBox(3, 3, 3, App.Vector(-.31, -.37, 1.25)), operation)
        result = native.build_mixed_solids(source["boundary_handle"], .1, 4)
        assert result["solid_validated"], result["reason"]
        owner.Geometry = result["solid_handle"]
        actual = Implicit.nativeGeometry(owner)
        assert actual.countSubElements("NativeFace") == 0
        assert actual.countSubElements("Solid") == (1 if operation == "common" else 0)
        assert actual.BoundBox.isValid() is (operation == "common")
        query = Implicit.classifyNative(owner.getSubObject(""), (20, 20, 20))
        assert query["state"] == "outside" and query["placement_resolved"]
    # The shared native-owner invalidation path must clear the SOLID property,
    # preserving its representation kind instead of falling back to a boundary.
    owner.Geometry = first_handle
    assert owner.getSubObject(stale, retType=1) == owner
    broken = doc.addObject("Implicit::Feature", "BrokenInput")
    broken.Period = -1
    owner.addProperty("App::PropertyLink", "Input", "Test").Input = broken
    doc.recompute()
    assert not owner.isValid() and owner.Geometry is None
    assert Implicit.nativeGeometry(owner).getElementTypes() == TYPES
    assert owner.getSubObject("Solid1") is None
    App.closeDocument(doc.Name)
    print("native implicit native solid property smoke test passed", flush=True)


try:
    main()
except BaseException:
    traceback.print_exc()
    os._exit(1)
