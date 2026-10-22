# SPDX-License-Identifier: LGPL-2.1-or-later
"""Transactional peer publication, cancellation and stale-input protection."""
import os
import time
import traceback
import FreeCAD as App
import ImplicitMixed
import ImplicitSolid
from ImplicitSolidBatch import SolidBatch
import ImplicitOCCT as native


def finish(batch):
    deadline = time.monotonic() + 90
    while batch.step() == "pending":
        assert time.monotonic() < deadline
        # No owner may expose a provisional subset of the batch.
        assert all(obj.Geometry is None for obj in batch.objects)
        time.sleep(.005)
    return batch.state


def main():
    source = ImplicitMixed.demo()
    doc = source.Document
    doc.UndoMode = 1
    owners = [ImplicitSolid.create(source), ImplicitSolid.create(source)]
    original = [native.dumps_mixed_solids(obj.Geometry) for obj in owners]
    # Compiled native geometry owners have no Python recipe/Proxy property.
    static = doc.addObject("Implicit::NativeFeature", "CompiledBoundary")
    static.Geometry = source.Geometry
    static_solid = ImplicitSolid.create(static)
    build = native.build_mixed_solids

    def forbidden(*_args):
        raise AssertionError("pending/finished batch recompute used the synchronous builder")

    native.build_mixed_solids = forbidden
    try:
        transaction = App.setActiveTransaction("Compiled source preview", True)
        batch = SolidBatch([static_solid], transaction)
        assert finish(batch) == "ready", batch.error
        assert static_solid.SolidValidated
        App.closeActiveTransaction(False, transaction)
        transaction = App.setActiveTransaction("Batch preview", True)
        batch = SolidBatch(owners, transaction)
        doc.recompute()  # Pending owners must not start synchronous work.
        assert finish(batch) == "ready", batch.error
        assert all(obj.SolidValidated for obj in owners)
        doc.recompute()
        assert [native.dumps_mixed_solids(obj.Geometry) for obj in owners] == original
        App.closeActiveTransaction(False, transaction)
        doc.undo(); doc.recompute()
        assert [native.dumps_mixed_solids(obj.Geometry) for obj in owners] == original
        doc.redo(); doc.recompute()

        transaction = App.setActiveTransaction("Cancel peers", True)
        batch = SolidBatch(owners, transaction)
        batch.cancel()
        assert batch.state == "cancelled" and all(obj.Geometry is None for obj in owners)
        App.closeActiveTransaction(True, transaction)
        doc.recompute()
        assert [native.dumps_mixed_solids(obj.Geometry) for obj in owners] == original

        transaction = App.setActiveTransaction("Failed peer", True)
        owners[1].MaximumGeometryCells = 1
        batch = SolidBatch(owners, transaction)
        assert finish(batch) == "failed"
        assert all(obj.Geometry is None and not obj.SolidValidated for obj in owners)
        App.closeActiveTransaction(True, transaction)
        doc.recompute()

        transaction = App.setActiveTransaction("Dirty source", True)
        batch = SolidBatch(owners, transaction)
        source.Box.Length = source.Box.Length.Value + .01
        assert finish(batch) == "failed" and "inputs changed" in batch.error
        App.closeActiveTransaction(True, transaction)
        doc.recompute()

        transaction = App.setActiveTransaction("Lost transaction", True)
        batch = SolidBatch(owners, transaction)
        App.closeActiveTransaction(True, transaction)
        external = App.setActiveTransaction("Unrelated label", True)
        owners[0].Label = "External label"
        restored = owners[0].Geometry
        assert finish(batch) == "failed"
        assert App.getActiveTransaction()[1] == external
        assert owners[0].Label == "External label" and owners[0].Geometry is not None
        assert native.dumps_mixed_solids(owners[0].Geometry) == native.dumps_mixed_solids(restored)
        App.closeActiveTransaction(True, external)
        doc.recompute()

        transaction = App.setActiveTransaction("Deleted batch owner", True)
        names = [obj.Name for obj in owners]
        batch = SolidBatch(owners, transaction)
        doc.removeObject(names[1])
        assert finish(batch) == "failed"
        assert owners[0].Geometry is None
        App.closeActiveTransaction(True, transaction)
        owners = [doc.getObject(name) for name in names]
        doc.recompute()
        assert all(obj.Geometry is not None for obj in owners)
    finally:
        native.build_mixed_solids = build
        App.closeDocument(doc.Name)
    print("native implicit solid batch smoke test passed", flush=True)


try:
    main()
except BaseException:
    traceback.print_exc()
    os._exit(1)
