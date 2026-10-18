# SPDX-License-Identifier: LGPL-2.1-or-later
"""Native mapped references survive unchanged topology, never indexed retargeting."""
import os
import shutil
import tempfile
import traceback
import zipfile
import FreeCAD as App
import Implicit
import ImplicitMixed
import ImplicitOCCT as native


def main():
    obj = ImplicitMixed.demo(open_contours=True)
    doc = obj.Document
    doc.UndoMode = 1
    slot = doc.addObject("Implicit::NativeFeaturePython", "Snapshot")
    slot.Geometry = obj.Geometry
    initial = slot.Geometry
    geometry = Implicit.nativeGeometry(slot)
    mapped = {}
    for kind in geometry.getElementTypes():
        for index in range(1, geometry.countSubElements(kind) + 1):
            name = kind + str(index)
            identity = geometry.getElementName(name, 1)
            assert identity.startswith("ImplicitV1_"), identity
            reference = ";" + identity + "." + name
            assert geometry.getElementName(reference) == name
            assert slot.getSubObject(reference, retType=1) == slot
            mapped[name] = reference
    assert slot.getSubObject("Cap999999", retType=1) is None
    link = doc.addObject("App::FeaturePython", "Attachment")
    link.addProperty("App::PropertyLinkSub", "Reference")
    link.Reference = (slot, ["Cap1"])
    link.addProperty("App::PropertyLinkSubList", "References")
    link.References = [(slot, ["Cap1", "Seam1", "Edge1", "Vertex1"])]
    slot_name, link_name, obj_name = slot.Name, link.Name, obj.Name
    with tempfile.TemporaryDirectory(prefix="implicit-reference-") as directory:
        filename = os.path.join(directory, "reference.FCStd")
        doc.saveAs(filename)
        with zipfile.ZipFile(filename) as archive:
            assert b"ImplicitV1_" in archive.read("Document.xml")
        App.closeDocument(doc.Name)
        doc = App.openDocument(filename)
        slot, link = doc.getObject(slot_name), doc.getObject(link_name)
        doc.recompute()
        restored = Implicit.nativeGeometry(slot)
        for name, reference in mapped.items():
            assert restored.getElementName(reference) == name
            assert slot.getSubObject(reference, retType=1) == slot
        copied_doc = App.newDocument("CopiedNativeReference")
        copied_link = copied_doc.copyObject(link, True)
        copied_slot, copied_names = copied_link.Reference
        assert copied_slot.Document == copied_doc and copied_slot != slot
        assert copied_slot.getSubObject(mapped["Cap1"], retType=1) == copied_slot
        assert copied_slot.getSubObject(copied_names[0], retType=1) == copied_slot
        App.closeDocument(copied_doc.Name)
        # New native geometry must not reinterpret an old mapped reference as
        # a current Cap1 merely because its trailing fallback index still fits.
        obj = doc.getObject(obj_name)
        obj.Operation = "BoxMinusField"
        doc.recompute()
        doc.openTransaction("Replace referenced native geometry")
        slot.Geometry = obj.Geometry
        doc.commitTransaction()
        doc.recompute()
        assert slot.getSubObject(mapped["Cap1"], retType=1) is None
        assert Implicit.nativeGeometry(slot).getElementName(mapped["Cap1"]) == ""
        assert slot.getSubObject(link.Reference[1][0], retType=1) is None, link.Reference
        for target, names in link.References:
            assert all(target.getSubObject(name, retType=1) is None for name in names)
        missing_file = os.path.join(directory, "missing.FCStd")
        doc.save()
        shutil.copyfile(filename, missing_file)
        missing = App.openDocument(missing_file)
        missing_slot, missing_link = missing.getObject(slot_name), missing.getObject(link_name)
        assert missing_slot.getSubObject(mapped["Cap1"], retType=1) is None
        assert missing_slot.getSubObject(missing_link.Reference[1][0], retType=1) is None
        for target, names in missing_link.References:
            assert all(target.getSubObject(name, retType=1) is None for name in names)
        App.closeDocument(missing.Name)
        doc.undo()
        assert slot.getSubObject(mapped["Cap1"], retType=1) == slot
        doc.redo()
        assert slot.getSubObject(mapped["Cap1"], retType=1) is None
        # Exact topology restoration recovers references, without a guessed
        # nearest-cap/edge match or geometric tolerance search.
        slot.Geometry = native.dumps_mixed(initial)
        assert slot.getSubObject(mapped["Cap1"], retType=1) == slot
        assert slot.getSubObject(link.Reference[1][0], retType=1) == slot
        for target, names in link.References:
            assert all(target.getSubObject(name, retType=1) == slot for name in names)
        slot.Geometry = None
        assert slot.getSubObject(mapped["Cap1"], retType=1) is None
        assert slot.getSubObject("Cap1", retType=1) is None
        assert slot.getSubObject(link.Reference[1][0], retType=1) is None
    App.closeDocument(doc.Name)
    assert geometry.getElementName(mapped["Cap1"]) == "Cap1"
    print("native implicit reference smoke test passed", flush=True)


try:
    main()
except BaseException:
    traceback.print_exc()
    os._exit(1)
