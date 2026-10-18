# SPDX-License-Identifier: LGPL-2.1-or-later
"""Owned native subobject geometry with explicit, once-applied placements."""
import os
import traceback
import FreeCAD as App
import Implicit
import ImplicitMixed
import Part


def compare(actual, expected):
    assert len(actual) == len(expected)
    assert all((a - b).Length < 1e-10 for a, b in zip(actual, expected))


def main():
    obj = ImplicitMixed.demo(open_contours=True)
    doc = obj.Document
    slot = doc.addObject("Implicit::NativeFeaturePython", "Snapshot")
    slot.Geometry = obj.Geometry
    local = Implicit.nativeGeometry(slot)
    slot.Placement = App.Placement(App.Vector(13, -4, 7), App.Rotation(App.Vector(1, 2, 3), 37))
    parent = doc.addObject("App::Part", "Container")
    parent.addObject(slot)
    parent.Placement = App.Placement(App.Vector(-6, 2, 1), App.Rotation(App.Vector(0, 1, 0), 19))
    retained = []
    for kind in local.getElementTypes():
        for index in range(1, local.countSubElements(kind) + 1):
            name = kind + str(index)
            mapped = ";" + local.getElementName(name, 1) + "." + name
            points, lines = local.getLinesFromSubElement(kind, index)
            selected = slot.getSubObject(mapped)
            assert selected.getElementTypes() == ["Element"]
            assert selected.countSubElements("Element") == 1
            assert selected.getElementName("Element1", 1) == local.getElementName(name, 1)
            placed, segments = selected.getLines(.1)
            assert segments == lines
            compare(placed, [slot.Placement.multVec(p) for p in points])
            compare(selected.getLinesFromSubElement("Element", 1)[0], placed)
            if kind == "Vertex":
                assert len(placed) == 1 and not segments
                sampled, normals = selected.getPoints(.1)
                compare(sampled, placed)
                assert not normals, "a topological vertex has no unique surface normal"
            assert selected.Placement == App.Placement()  # already pre-placed
            assert all(selected.BoundBox.isInside(p) for p in placed)
            if kind == "NativeFace":
                domain = local.BoundBox
                corners = [slot.Placement.multVec(App.Vector(x, y, z))
                           for x in (domain.XMin, domain.XMax)
                           for y in (domain.YMin, domain.YMax)
                           for z in (domain.ZMin, domain.ZMax)]
                for axis in ("x", "y", "z"):
                    low = getattr(selected.BoundBox, axis.upper() + "Min")
                    high = getattr(selected.BoundBox, axis.upper() + "Max")
                    assert abs(low - min(getattr(p, axis) for p in corners)) < 1e-10
                    assert abs(high - max(getattr(p, axis) for p in corners)) < 1e-10
            raw = slot.getSubObject(mapped, transform=False)
            compare(raw.getLines(.1)[0], points)
            nested = parent.getSubObject(slot.Name + "." + mapped)
            pose = parent.Placement.multiply(slot.Placement)
            compare(nested.getLines(.1)[0], [pose.multVec(p) for p in points])
            if index == 1:
                incoming = App.Placement(App.Vector(2, 3, 4), App.Rotation(0, 0, 17))
                extra = slot.getSubObject(mapped, matrix=incoming.toMatrix())
                combined = incoming.multiply(slot.Placement)
                compare(extra.getLines(.1)[0], [combined.multVec(p) for p in points])
            retained.append((selected, placed))
    selected = retained[0][0]  # Whole native face, not an exact topological point.
    for operation in (lambda: selected.getFaces(.1), lambda: selected.getPoints(.1)):
        try:
            operation()
        except RuntimeError:
            pass
        else:
            raise AssertionError("unsupported native surface sampling returned silently")
    conventional = doc.addObject("Part::Feature", "Conventional")
    for owner, prop in ((conventional, "Shape"), (slot, "Geometry")):
        try:
            setattr(owner, prop, selected)
        except TypeError:
            pass
        else:
            raise AssertionError("native selected geometry accepted as a Part shape/property snapshot")
    for scale in (App.Vector(2, 1, 1), App.Vector(-1, 1, 1)):
        matrix = App.Matrix()
        matrix.scale(scale)
        try:
            slot.getSubObject("Seam1", matrix=matrix)
        except NotImplementedError:
            pass
        else:
            raise AssertionError("native extraction accepted unqualified scale/reflection")
    for mutate in (lambda m: setattr(m, "A14", float("nan")),
                   lambda m: setattr(m, "A41", .1)):
        matrix = App.Matrix()
        mutate(matrix)
        try:
            slot.getSubObject("Seam1", matrix=matrix)
        except (ValueError, NotImplementedError):
            pass
        else:
            raise AssertionError("nonfinite/projective native placement accepted")
    for mutate in (lambda: selected.applyTranslation(App.Vector(1, 0, 0)),
                   lambda: selected.dumpContent()):
        try:
            mutate()
        except (NotImplementedError, RuntimeError):
            pass
        else:
            raise AssertionError("selected native geometry mutated or serialized independently")
    App.closeDocument(doc.Name)
    for selected, points in retained:
        compare(selected.getLines(.1)[0], points)
    print("native implicit element smoke test passed", flush=True)


try:
    main()
except BaseException:
    traceback.print_exc()
    os._exit(1)
