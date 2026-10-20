# SPDX-License-Identifier: LGPL-2.1-or-later
"""Shared primitive edits, preserved expressions, peers, rollback and degeneracy."""
import os
import tempfile
import traceback
import FreeCAD as App
import ImplicitMixed
import ImplicitSolid
import ImplicitOCCT as native
from ImplicitSourceEdit import SourceEdits, rebuild


def main():
    doc = App.newDocument("NativeSourceParameters")
    doc.UndoMode = 1
    field = doc.addObject("Implicit::Feature", "Gyroid")
    field.Function, field.Period, field.IsoValue = "Gyroid", 10, 0
    field.DomainMin = (0, 0, 0)
    for name, axis in zip(("Length", "Width", "Height"), "xyz"):
        field.addProperty("App::PropertyLength", name)
        setattr(field, name, 10)
        field.setExpression("DomainMax." + axis, "DomainMin." + axis + " + " + name + " / (1 mm)")
    box = doc.addObject("Part::Box", "Box")
    box.Length = box.Width = box.Height = 10
    doc.recompute()
    source = ImplicitMixed.create(field, box, corner_policy="Regularized")
    peer_source = ImplicitMixed.create(field, box, operation="BoxMinusField", corner_policy="Regularized")
    solid, peer = ImplicitSolid.create(source), ImplicitSolid.create(peer_source)
    expressions = field.ExpressionEngine
    ctx = SourceEdits(solid)
    assert ctx.domain_mode() == "dimensions" and ctx.follows_box()
    assert not ctx.prepare(ctx.values(), True)[-1]
    values = dict(ctx.values(), Period=5, Length=5, Width=5, Height=5)
    plan = ctx.prepare(values, True)
    try:
        ctx.apply(plan, 0)
    except RuntimeError:
        pass
    else:
        raise AssertionError("shared edits entered an unowned transaction")
    transaction = App.setActiveTransaction("Scale shared inputs", True)
    affected = ctx.apply(plan, transaction)
    assert set(affected) == {source, peer_source}
    assert solid.Geometry is None and peer.Geometry is None
    assert field.ExpressionEngine == expressions
    rebuild(affected)
    doc.recompute()
    assert field.Period.Value == 5 and tuple(field.DomainMax) == (5, 5, 5)
    assert all(getattr(field, name).Value == 5 for name in ctx.names[2:])
    assert solid.SolidValidated and peer.SolidValidated
    assert str(source.Operation) == "Common" and str(peer_source.Operation) == "BoxMinusField"
    assert native.source_mixed_solids(solid.Geometry)["period"] == 5
    App.closeActiveTransaction(False, transaction)
    doc.undo(); doc.recompute()
    assert field.Period.Value == 10 and box.Length.Value == 10
    assert field.ExpressionEngine == expressions and solid.SolidValidated and peer.SolidValidated
    doc.redo(); doc.recompute()
    assert field.Period.Value == 5 and solid.SolidValidated and peer.SolidValidated
    original = native.dumps_mixed_solids(solid.Geometry)
    ctx = SourceEdits(solid)
    transaction = App.setActiveTransaction("Singular shared level", True)
    affected = ctx.apply(ctx.prepare(dict(ctx.values(), IsoValue=1.5), True), transaction)
    try:
        rebuild(affected)
    except ValueError:
        pass
    else:
        raise AssertionError("singular critical-level native solid was guessed valid")
    assert solid.Geometry is None and peer.Geometry is None
    assert not solid.SolidValidated and not peer.SolidValidated
    App.closeActiveTransaction(True, transaction)
    doc.recompute()
    assert field.IsoValue == 0 and native.dumps_mixed_solids(solid.Geometry) == original
    assert solid.SolidValidated and peer.SolidValidated
    for property_name, expression, change in (
            ("Period", "5 mm", {"Period": 6}),
            ("DomainMax.x", "DomainMin.x + Length / (1 mm) + 1", {})):
        doc.openTransaction("Custom expression guard")
        field.setExpression(property_name, expression)
        ctx = SourceEdits(solid)
        before = field.ExpressionEngine
        try:
            ctx.prepare(dict(ctx.values(), **change), True)
        except ValueError:
            pass
        else:
            raise AssertionError("custom expression was overwritten")
        assert field.ExpressionEngine == before
        doc.abortTransaction(); doc.recompute()
    ctx = SourceEdits(solid)
    doc.openTransaction("External input change")
    field.Period = 6
    try:
        ctx.prepare(ctx.values(), True)
    except ValueError:
        pass
    else:
        raise AssertionError("external shared edit was silently adopted")
    doc.abortTransaction(); doc.recompute()
    with tempfile.TemporaryDirectory(prefix="implicit-source-external-") as directory:
        doc.saveAs(os.path.join(directory, "source.FCStd"))
        external = App.newDocument("ExternalSourceConsumer")
        external.saveAs(os.path.join(directory, "consumer.FCStd"))
        link = external.addObject("App::Link", "SharedField")
        link.LinkedObject = field
        ctx = SourceEdits(solid)
        before = ctx.signature()
        try:
            ctx.prepare(dict(ctx.values(), Period=6), True)
        except ValueError as error:
            assert "Cross-document" in str(error)
        else:
            raise AssertionError("cross-document shared input was edited")
        assert ctx.signature() == before
        assert solid.Geometry is not None and peer.Geometry is not None
        App.closeDocument(external.Name)
        App.setActiveDocument(doc.Name)
    # Ordinary API-created fields do not have workbench dimension aliases.
    # getTypeIdOfProperty raises AttributeError for missing properties.
    plain_field = doc.addObject("Implicit::Feature", "PlainGyroid")
    plain_field.Function, plain_field.Period = "Gyroid", 10
    plain_field.DomainMin, plain_field.DomainMax = (0, 0, 0), (10, 10, 10)
    plain_box = doc.addObject("Part::Box", "PlainBox")
    plain_box.Length = plain_box.Width = plain_box.Height = 10
    doc.recompute()
    plain_source = ImplicitMixed.create(plain_field, plain_box, corner_policy="Regularized")
    plain_solid = ImplicitSolid.create(plain_source)
    plain_ctx = SourceEdits(plain_solid)
    assert plain_ctx.domain_mode() == "direct" and plain_ctx.follows_box()
    assert not plain_ctx.prepare(plain_ctx.values(), True)[-1]
    transaction = App.setActiveTransaction("Scale plain source", True)
    affected = plain_ctx.apply(plain_ctx.prepare(dict(plain_ctx.values(),
        Period=5, Length=5, Width=5, Height=5), True), transaction)
    rebuild(affected)
    doc.recompute()
    assert plain_solid.SolidValidated and tuple(plain_field.DomainMax) == (5, 5, 5)
    assert all(name not in plain_field.PropertiesList for name in plain_ctx.names[2:])
    App.closeActiveTransaction(True, transaction)
    doc.recompute()
    assert plain_solid.SolidValidated and plain_field.Period.Value == 10
    print("native implicit source parameters smoke test passed", flush=True)
    App.closeDocument(doc.Name)


try:
    main()
except BaseException:
    traceback.print_exc()
    os._exit(1)
