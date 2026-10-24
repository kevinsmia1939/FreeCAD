# SPDX-License-Identifier: LGPL-2.1-or-later
"""Live whole-object instances use effective placements and preserve source B-Reps."""
import os
import tempfile
import traceback
import FreeCAD as App
import Part
import ImplicitMixed
import ImplicitSolid
import ImplicitOCCT as native
from ImplicitOperands import resolve, primitive_field, box_shape
from ImplicitSourceEdit import SourceEdits, sources_for


def rejected(call):
    try:
        call()
    except ValueError:
        return
    raise AssertionError("Unsupported instance was accepted")


def main():
    doc = App.newDocument("OperandInstances")
    doc.UndoMode = 1
    field = doc.addObject("Implicit::Feature", "Gyroid")
    field.Function, field.Period = "Gyroid", 10
    field.DomainMin, field.DomainMax = (0, 0, 0), (20, 20, 20)
    field_link = doc.addObject("App::Link", "FieldInstance")
    field_link.setLink(field)
    box = doc.addObject("Part::Box", "Box")
    box.Length = box.Width = box.Height = 10
    box.Placement.Base = (.31, .37, 0)
    box_link = doc.addObject("App::Link", "BoxInstance")
    box_link.setLink(box)
    box_link.LinkTransform = True
    container = doc.addObject("App::Part", "Container")
    container.Placement.Base = (1, 2, 0)
    container.addObject(box_link)
    doc.recompute()
    original = box.Shape.exportBrepToString()
    assert primitive_field(field_link) is field
    assert box_shape(box_link).BoundBox.XMin == 1.31
    assert box.Shape.exportBrepToString() == original
    source = ImplicitMixed.create(field_link, box_link, corner_policy="Regularized")
    # Migrate legacy dynamic local-scope recipe links without changing their
    # logical fingerprint or discarding the authoritative stored topology.
    fingerprint = source.InputFingerprint
    record = native.dumps_mixed(source.Geometry)
    for name in ("Field", "Box"):
        operand = getattr(source, name)
        source.removeProperty(name)
        source.addProperty("App::PropertyLink", name, "Native mixed boundary")
        setattr(source, name, operand)
    source.Proxy._ensure_geometry(source)
    assert all(source.getTypeIdOfProperty(name) == "App::PropertyLinkGlobal" for name in ("Field", "Box"))
    assert source.InputFingerprint == fingerprint and native.dumps_mixed(source.Geometry) == record
    for mode, api_mode in (("Common", "common"), ("BoxMinusField", "box_minus_field")):
        source.Operation = mode
        doc.recompute()
        assert source.Geometry is not None and source.isValid(), source.BackendStatus
        face = native.gyroid(10, 0, (0, 0, 0), (20, 20, 20), .1)
        reference = Part.makeBox(10, 10, 10)
        reference.Placement.Base = (1.31, 2.37, 0)
        expected = native.mixed_box(face, reference, api_mode, .1, 512, corner_policy="regularized")
        assert native.dumps_mixed(source.Geometry) == native.dumps_mixed(expected["boundary_handle"])
    assert box.Shape.exportBrepToString() == original
    # LinkTransform controls target placement; target containers are not part of
    # an instance's placement path. A nested alias adds its own translation once.
    box_link.LinkTransform = False
    doc.recompute()
    assert box_shape(box_link).BoundBox.XMin == 1
    nested = doc.addObject("App::Link", "NestedBox")
    nested.setLink(box_link); nested.LinkTransform = True
    nested.LinkPlacement.Base = (3, 4, 0)
    doc.recompute()
    assert box_shape(nested).BoundBox.XMin == 3
    box_link.LinkTransform = True
    doc.recompute()
    assert box_shape(nested).BoundBox.XMin == 3.31
    assert box.Shape.exportBrepToString() == original
    # Direct container-owned boxes use world placement too.
    container.addObject(box)
    doc.recompute()
    assert box_shape(box).BoundBox.XMin == 1.31
    assert box_shape(box_link).BoundBox.XMin == 1.31
    source.Operation = "Common"
    doc.recompute()
    solid = ImplicitSolid.create(source)
    assert solid.SolidValidated, solid.BackendStatus
    edit = SourceEdits(solid)
    assert edit.field is field and edit.box is box
    assert edit.bounds()[0] == (1.31, 2.37, 0)
    peer = ImplicitMixed.create(field, nested, corner_policy="Regularized")
    assert set(sources_for(source, field, box)) == {source, peer}
    values = edit.values(); values["Length"] = 9
    doc.openTransaction("Edit linked primitive")
    plan = edit.prepare(values, False)
    affected = edit.apply(plan, App.getActiveTransaction()[1])
    assert set(affected) == {source, peer}
    assert box.Length.Value == 9 and field_link.getLinkedObject(True) is field
    assert source.Geometry is None and solid.Geometry is None and peer.Geometry is None
    doc.abortTransaction(); doc.recompute()
    assert box.Length.Value == 10 and solid.Geometry is not None
    # Transforms outside this resolver's contract fail rather than disappearing.
    field_link.LinkPlacement.Base = (1e-15, 0, 0)
    rejected(lambda: primitive_field(field_link))
    field_link.LinkPlacement = App.Placement()
    box_link.Scale = 2
    rejected(lambda: box_shape(box_link))
    box_link.Scale = 1
    box_link.LinkedObject = (box, ["Face1"])
    rejected(lambda: box_shape(box_link))
    box_link.setLink(box)
    doc.recompute()
    field.Placement.Base = (2, 0, 0)
    field_link.LinkTransform = False
    assert primitive_field(field_link) is field
    field_link.LinkTransform = True
    rejected(lambda: primitive_field(field_link))
    field.Placement = App.Placement()
    container.Placement = App.Placement(App.Vector(1, 2, 0), App.Rotation(0, 0, 1))
    rejected(lambda: box_shape(box_link))
    container.Placement = App.Placement(App.Vector(1, 2, 0), App.Rotation())
    with tempfile.TemporaryDirectory(prefix="implicit-external-") as folder:
        doc.recompute()
        doc.saveAs(os.path.join(folder, "owner.FCStd"))
        external = App.newDocument("ExternalOperand")
        external_box = external.addObject("Part::Box", "ExternalBox")
        external.recompute()
        external.saveAs(os.path.join(folder, "external.FCStd"))
        external_link = doc.addObject("App::Link", "ExternalInstance"); external_link.setLink(external_box)
        rejected(lambda: box_shape(external_link))
        doc.removeObject(external_link.Name); App.closeDocument(external.Name)
    App.setActiveDocument(doc.Name)
    doc.recompute()
    # Save/reopen reuses unchanged topology and keeps proof provenance explicit.
    names = source.Name, solid.Name
    with tempfile.TemporaryDirectory(prefix="implicit-instances-") as folder:
        filename = os.path.join(folder, "instances.FCStd")
        doc.saveAs(filename)
        App.closeDocument(doc.Name)
        doc = App.openDocument(filename)
        restored_source, restored_solid = [doc.getObject(name) for name in names]
        original_builder = native.mixed_box
        def forbidden(*args, **kwargs):
            raise AssertionError("Unchanged restored instances were numerically retraced")
        native.mixed_box = forbidden
        try:
            doc.recompute()
            assert restored_source.Geometry is not None and restored_solid.Geometry is not None
            assert not restored_source.SeamBoundVerified and not restored_solid.SolidValidated
        finally:
            native.mixed_box = original_builder
    App.closeDocument(doc.Name)
    print("native implicit operand instances smoke test passed", flush=True)


try:
    main()
except BaseException:
    traceback.print_exc()
    raise
