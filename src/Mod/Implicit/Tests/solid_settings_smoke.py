# SPDX-License-Identifier: LGPL-2.1-or-later
"""Independent live geometry depth, legacy fingerprints and large-model restore."""
import hashlib
import json
import os
import tempfile
import traceback
import zipfile
import FreeCAD as App
import ImplicitMixed
import ImplicitSolid
import ImplicitOCCT as native


def main():
    source = ImplicitMixed.demo()
    doc = source.Document
    obj = ImplicitSolid.create(source)
    assert obj.MaximumGeometryDepth == -1
    record, settings, fingerprint = obj.Proxy._inputs(obj)
    assert len(settings) == 8
    legacy = hashlib.sha256(json.dumps((hashlib.sha256(record.encode()).hexdigest(), settings),
                                      allow_nan=False).encode()).hexdigest()
    assert fingerprint == legacy == obj.InputFingerprint
    geometry = native.dumps_mixed_solids(obj.Geometry)
    name = obj.Name
    # Real legacy-like FCStd fixture: property absent, old fingerprint retained.
    obj.removeProperty("MaximumGeometryDepth")
    with tempfile.TemporaryDirectory(prefix="implicit-solid-settings-") as directory:
        path = os.path.join(directory, "legacy.FCStd")
        doc.saveAs(path)
        with zipfile.ZipFile(path) as archive:
            assert 'name="MaximumGeometryDepth"' not in archive.read("Document.xml").decode()
        build = native.build_mixed_solids
        def forbidden(*_args):
            raise AssertionError("unchanged legacy restore rebuilt native solids")
        native.build_mixed_solids = forbidden
        try:
            App.closeDocument(doc.Name)
            doc = App.openDocument(path)
            doc.recompute()
            obj = doc.getObject(name)
            assert obj.MaximumGeometryDepth == -1 and obj.InputFingerprint == legacy
            assert native.dumps_mixed_solids(obj.Geometry) == geometry
            assert not obj.SolidValidated
        finally:
            native.build_mixed_solids = build
    calls = []
    def observed(*args):
        calls.append(args[1:])
        return build(*args)
    native.build_mixed_solids = observed
    try:
        obj.MaximumGeometryDepth = 18
        obj.Proxy.execute(obj)
        assert obj.SolidValidated and obj.GeometricTolerance.Value == .1
        assert len(calls[-1]) == 9 and calls[-1][-1] == 18
        assert obj.InputFingerprint != legacy
        obj.MaximumGeometryDepth = -1
        obj.Proxy.execute(obj)
        assert len(calls[-1]) == 8 and obj.InputFingerprint == legacy
    finally:
        native.build_mixed_solids = build
    for invalid in (-2, 0, 25):
        obj.MaximumGeometryDepth = invalid
        try:
            obj.Proxy.execute(obj)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid independent geometry depth accepted")
        assert obj.Geometry is None and not obj.SolidValidated
    App.closeDocument(doc.Name)
    doc = App.newDocument("LargeLiveSolidSettings")
    field = doc.addObject("Implicit::Feature", "Gyroid")
    field.Function, field.Period, field.IsoValue = "Gyroid", 20, 0
    field.DomainMin, field.DomainMax = (-20, -20, 20), (0, 0, 40)
    box = doc.addObject("Part::Box", "Box")
    box.Length = box.Width = box.Height = 20
    box.Placement.Base = (-20, -20, 20)
    doc.recompute()
    source = ImplicitMixed.create(field, box, corner_policy="Regularized")
    count = len(doc.Objects)
    try:
        ImplicitSolid.create(source)
    except RuntimeError:
        pass
    else:
        raise AssertionError("large model unexpectedly qualified at shared default depth")
    assert len(doc.Objects) == count  # Atomic create failure, not a half-built owner.
    obj = ImplicitSolid.create(source, maximum_geometry_depth=18)
    assert obj.MaximumDepth == 16 and obj.MaximumGeometryDepth == 18
    assert obj.SolidValidated and obj.GeometricTolerance.Value == .1
    assert native.inspect_mixed_solids(obj.Geometry)["geometry"]["boundary_bound"] <= .1
    name, fingerprint = obj.Name, obj.InputFingerprint
    geometry = native.dumps_mixed_solids(obj.Geometry)
    with tempfile.TemporaryDirectory(prefix="implicit-large-solid-settings-") as directory:
        path = os.path.join(directory, "large.FCStd")
        doc.saveAs(path)
        native.build_mixed_solids = forbidden
        try:
            App.closeDocument(doc.Name)
            doc = App.openDocument(path)
            doc.recompute()
            obj = doc.getObject(name)
            assert obj.MaximumGeometryDepth == 18 and obj.InputFingerprint == fingerprint
            assert native.dumps_mixed_solids(obj.Geometry) == geometry
            assert not obj.SolidValidated
        finally:
            native.build_mixed_solids = build
    App.closeDocument(doc.Name)
    print("native implicit solid settings smoke test passed", flush=True)


try:
    main()
except BaseException:
    traceback.print_exc()
    os._exit(1)
