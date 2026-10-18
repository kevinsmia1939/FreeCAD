# SPDX-License-Identifier: LGPL-2.1-or-later
"""Native whole/subelement geometry through rigid App::Link paths."""
import os
import tempfile
import traceback
import FreeCAD as App
import Implicit
import ImplicitMixed


def compare(actual, expected):
    assert len(actual) == len(expected)
    assert all((a - b).Length < 1e-10 for a, b in zip(actual, expected))


def main():
    obj = ImplicitMixed.demo(open_contours=True)
    doc = obj.Document
    slot = doc.addObject("Implicit::NativeFeaturePython", "Snapshot")
    slot.Geometry = obj.Geometry
    slot.Placement = App.Placement(App.Vector(7, -2, 4), App.Rotation(App.Vector(1, 2, 0), 29))
    local = Implicit.nativeGeometry(slot)
    points, lines = local.getLines(.1)
    direct = slot.getSubObject("")
    assert direct.getElementTypes() == local.getElementTypes()
    compare(direct.getLines(.1)[0], [slot.Placement.multVec(p) for p in points])
    assert direct.getLines(.1)[1] == lines
    link = doc.addObject("App::Link", "Instance")
    link.LinkedObject = slot
    placement = App.Placement(App.Vector(-3, 11, -5), App.Rotation(App.Vector(0, 0, 1), 41))
    for include_source in (False, True):
        link.LinkTransform = include_source
        link.LinkPlacement = placement
        doc.recompute()
        pose = placement.multiply(slot.Placement) if include_source else placement
        whole = link.getSubObject("")
        assert whole is not None
        compare(whole.getLines(.1)[0], [pose.multVec(p) for p in points])
        assert whole.Placement == App.Placement()
        for kind in local.getElementTypes():
            assert whole.countSubElements(kind) == local.countSubElements(kind)
            for index in range(1, local.countSubElements(kind) + 1):
                name = kind + str(index)
                mapped = ";" + local.getElementName(name, 1) + "." + name
                original, _ = local.getLinesFromSubElement(kind, index)
                selected = link.getSubObject(mapped)
                compare(selected.getLines(.1)[0], [pose.multVec(p) for p in original])
                compare(whole.getLinesFromSubElement(kind, index)[0], selected.getLines(.1)[0])
    # Whole-object extraction through a transformed container uses the same
    # placement chain, without modifying the authoritative source snapshot.
    parent = doc.addObject("App::Part", "Container")
    parent.addObject(link)
    parent.Placement = App.Placement(App.Vector(2, 3, 4), App.Rotation(13, 0, 0))
    nested = parent.getSubObject(link.Name + ".")
    pose = parent.Placement.multiply(placement).multiply(slot.Placement)
    compare(nested.getLines(.1)[0], [pose.multVec(p) for p in points])
    sublink = doc.addObject("App::Link", "SelectedInstance")
    mapped = ";" + local.getElementName("Cap1", 1) + ".Cap1"
    sublink.LinkedObject = (slot, [mapped])
    sublink.LinkTransform = True
    sublink.LinkPlacement = placement
    selected = sublink.getSubObject("")
    cap_points, _ = local.getLinesFromSubElement("Cap", 1)
    compare(selected.getLines(.1)[0], [placement.multiply(slot.Placement).multVec(p) for p in cap_points])
    names = slot.Name, link.Name, parent.Name, sublink.Name
    with tempfile.TemporaryDirectory(prefix="implicit-link-") as directory:
        filename = os.path.join(directory, "links.FCStd")
        doc.saveAs(filename)
        App.closeDocument(doc.Name)
        doc = App.openDocument(filename)
        slot, link, parent, sublink = [doc.getObject(name) for name in names]
        compare(parent.getSubObject(link.Name + ".").getLines(.1)[0], [pose.multVec(p) for p in points])
        compare(sublink.getSubObject("").getLines(.1)[0], selected.getLines(.1)[0])
        # External-document maps are re-tagged by App::Link on the returned
        # snapshot. The source property/map must remain unchanged.
        external = App.newDocument("ExternalNativeInstance")
        external_link = external.addObject("App::Link", "Instance")
        external_file = os.path.join(directory, "external.FCStd")
        external.saveAs(external_file)  # App::XLink requires a saved owner document.
        external_link.LinkedObject = slot
        external_link.LinkTransform = True
        external_link.LinkPlacement = placement
        external_pose = placement.multiply(slot.Placement)
        for name, original in (("", points), (mapped, cap_points)):
            result = external_link.getSubObject(name)
            compare(result.getLines(.1)[0], [external_pose.multVec(p) for p in original])
        assert Implicit.nativeGeometry(slot).getElementName("Cap1", 1) == local.getElementName("Cap1", 1)
        external.save()
        App.closeDocument(external.Name)
        external = App.openDocument(external_file)
        external_link = external.getObject("Instance")
        compare(external_link.getSubObject(mapped).getLines(.1)[0],
                [external_pose.multVec(p) for p in cap_points])
        App.closeDocument(external.Name)
        link.Scale = 2
        for name in ("", "Seam1"):
            try:
                link.getSubObject(name)
            except NotImplementedError:
                pass
            else:
                raise AssertionError("scaled native link extraction accepted without policy")
        slot.Geometry = None
        assert slot.getSubObject("") is None
        assert sublink.getSubObject("") is None
    App.closeDocument(doc.Name)
    compare(direct.getLines(.1)[0], [App.Placement(App.Vector(7, -2, 4),
        App.Rotation(App.Vector(1, 2, 0), 29)).multVec(p) for p in points])
    print("native implicit link smoke test passed", flush=True)


try:
    main()
except BaseException:
    traceback.print_exc()
    os._exit(1)
