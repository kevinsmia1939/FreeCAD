# SPDX-License-Identifier: LGPL-2.1-or-later
"""Live solid dependencies, persistent actual topology and explicit repair."""
import os
import tempfile
import traceback
import zipfile
import FreeCAD as App
import Implicit
import ImplicitMixed
import ImplicitSolid
import ImplicitOCCT as native


def check(obj, validated=True):
    report = native.inspect_mixed_solids(obj.Geometry)
    assert obj.SolidValidated is validated and report["solid_validated"] is validated
    assert obj.SolidCount == report["solid_count"]
    assert obj.ShellCount == report["shell_count"]
    assert obj.NativeFaceCount == report["implicit_face_count"]
    assert Implicit.nativeGeometry(obj).countSubElements("Solid") == obj.SolidCount
    geometry = Implicit.nativeGeometry(obj)
    assert len(report["seam_edges"]) == geometry.countSubElements("Seam")
    for index, edge in enumerate(report["seam_edges"], 1):
        seam_points, seam_lines = geometry.getLinesFromSubElement("Seam", index)
        edge_points, edge_lines = geometry.getLinesFromSubElement("Edge", edge + 1)
        assert seam_lines == edge_lines
        assert len(seam_points) == len(edge_points)
        assert all((p - q).Length < 1e-12 for p, q in zip(seam_points, edge_points))
    source = native.source_mixed_solids(obj.Geometry)
    assert native.dumps_mixed(source["boundary_handle"]) == native.dumps_mixed(obj.Source.Geometry)


def main():
    candidate = {"vertices": [(0, 0, 0), (.2, 0, 0), (0, .2, 0)],
                 "implicit_triangles": [(0, 1, 2)]}
    domain = ((-1, -1, -1), (1, 1, 1))
    assert ImplicitSolid.component_triangles(candidate, [domain]) == [[(0, 1, 2)]]
    for domains in ([], [domain, domain], [domain, ((2, 2, 2), (3, 3, 3))],
                    [((-.1, -.1, -.1), (.1, .1, .1))]):
        try:
            ImplicitSolid.component_triangles(candidate, domains)
        except ValueError:
            pass
        else:
            raise AssertionError("ambiguous/crossing/missing component display was accepted")
    boundary = ImplicitMixed.demo(open_contours=True)
    doc = boundary.Document
    doc.UndoMode = 1
    doc.openTransaction("Unrelated user transaction")
    transaction = App.getActiveTransaction()
    try:
        ImplicitSolid.create(boundary)
    except RuntimeError:
        pass
    else:
        raise AssertionError("solid creation entered an unrelated active transaction")
    assert App.getActiveTransaction() == transaction
    doc.abortTransaction()
    obj = ImplicitSolid.create(boundary)
    check(obj)
    assert obj.TypeId == "Implicit::NativeSolidFeaturePython" and "Shape" not in obj.PropertiesList
    first = native.dumps_mixed_solids(obj.Geometry)
    build = native.build_mixed_solids
    def forbidden(*_args):
        raise AssertionError("unchanged/restore path attempted numerical solid rebuilding")
    native.build_mixed_solids = forbidden
    try:
        obj.touch()
        doc.recompute()
        check(obj)
        assert native.dumps_mixed_solids(obj.Geometry) == first
        parent = doc.addObject("App::Part", "ResultContainer")
        parent.Placement = App.Placement(App.Vector(3, 4, 5), App.Rotation(31, 7, 11))
        parent.addObject(obj)
        boundary.Placement = App.Placement(App.Vector(-2, 6, -4), App.Rotation(13, 29, 5))
        doc.recompute()
        assert obj.getGlobalPlacement().isSame(boundary.getGlobalPlacement(), 1e-10), (
            parent.Group, obj.getGlobalPlacement(), boundary.getGlobalPlacement(),
            boundary.Field.getGlobalPlacement(), boundary.Box.getGlobalPlacement(), obj.BackendStatus)
        # Independent output positioning is explicit, never mixed into the math.
        obj.FollowSourcePlacement = False
        own_pose = App.Placement(App.Vector(8, -1, 3), App.Rotation(23, 0, 17))
        obj.Placement = own_pose
        doc.recompute()
        assert obj.Placement.isSame(own_pose, 1e-10)
        check(obj)
        with tempfile.TemporaryDirectory(prefix="implicit-live-solid-") as directory:
            filename = os.path.join(directory, "live.FCStd")
            names = obj.Name, boundary.Name
            doc.saveAs(filename)
            App.closeDocument(doc.Name)
            doc = App.openDocument(filename)
            obj, boundary = (doc.getObject(name) for name in names)
            check(obj, False)
            assert native.dumps_mixed_solids(obj.Geometry) == first
            assert obj.Placement.isSame(own_pose, 1e-10)
            obj.touch()
            doc.recompute()
            check(obj, False)
            corrupt_path = os.path.join(directory, "corrupt.FCStd")
            with zipfile.ZipFile(filename) as source, zipfile.ZipFile(corrupt_path, "w") as target:
                for item in source.infolist():
                    target.writestr(item, b"invalid" if item.filename.endswith(".nativesolid")
                                   else source.read(item.filename))
            corrupt = App.openDocument(corrupt_path)
            broken = corrupt.getObject(names[0])
            assert broken.Geometry is None and broken.Proxy._restore_failed
            try:
                broken.Proxy.execute(broken)
            except RuntimeError:
                pass
            else:
                raise AssertionError("corruption silently rebuilt the solid")
            assert broken.Geometry is None
            App.closeDocument(corrupt.Name)
    finally:
        native.build_mixed_solids = build
    # Rechecking creates a NEW qualified result; loaded snapshot stays unverified.
    loaded = obj.Geometry
    obj.Proxy.rebuild(obj)
    doc.recompute()
    check(obj)
    assert not native.inspect_mixed_solids(loaded)["solid_validated"]
    doc.openTransaction("Change solid source operation")
    boundary.Operation = "BoxMinusField"
    doc.recompute()
    doc.commitTransaction()
    check(obj)
    second = native.dumps_mixed_solids(obj.Geometry)
    assert second != first
    doc.undo()
    doc.recompute()
    check(obj)
    assert native.dumps_mixed_solids(obj.Geometry) == first
    doc.redo()
    doc.recompute()
    check(obj)
    assert native.dumps_mixed_solids(obj.Geometry) == second
    obj.MaximumGeometryCells = 1
    try:
        obj.Proxy.execute(obj)
    except ValueError:
        pass
    else:
        raise AssertionError("exhausted solid budget published geometry")
    assert obj.Geometry is None and obj.Proxy._solid is None and not obj.SolidValidated
    obj.MaximumGeometryCells = 2000000
    doc.recompute()
    check(obj)
    # A valid but mismatching actual result cannot hide behind unchanged inputs.
    obj.Geometry = native.loads_mixed_solids(first)["solid_handle"]
    try:
        obj.Proxy.execute(obj)
    except ValueError:
        pass
    else:
        raise AssertionError("mismatching stored source/result was accepted")
    assert obj.Geometry is None and obj.Proxy._restore_failed
    obj.Proxy.rebuild(obj)
    doc.recompute()
    check(obj)
    # Upstream C++ failure skips Python execution; the core hook must clear both.
    boundary.Field.Period = -1
    doc.recompute()
    assert boundary.Geometry is None and obj.Geometry is None and not obj.SolidValidated
    assert obj.Proxy._solid is None and not obj.isValid()
    App.closeDocument(doc.Name)
    print("native implicit live solid smoke test passed", flush=True)


try:
    main()
except BaseException:
    traceback.print_exc()
    os._exit(1)
