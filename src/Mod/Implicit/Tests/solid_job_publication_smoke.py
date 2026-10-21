# SPDX-License-Identifier: LGPL-2.1-or-later
"""GUI-thread publication prerequisite: transactions and stale-source rejection."""
import os
import time
import traceback
import FreeCAD as App
import ImplicitMixed
import ImplicitSolid
import ImplicitOCCT as native


def main():
    source = ImplicitMixed.demo()
    doc = source.Document
    doc.UndoMode = 1
    job = native.start_solid_job(source.Geometry)
    deadline = time.monotonic() + 90
    while native.solid_job_status(job)["state"] in ("queued", "running"):
        assert time.monotonic() < deadline
        time.sleep(.01)
    assert native.solid_job_status(job)["state"] == "ready", native.solid_job_status(job)
    completed = native.take_solid_job(job)
    original = native.build_mixed_solids

    def forbidden(*_args):
        raise AssertionError("publication rebuilt the completed native solid")

    native.build_mixed_solids = forbidden
    try:
        count = len(doc.Objects)

        def rejected(**kwargs):
            try:
                ImplicitSolid._create(source, completed=completed, **kwargs)
            except (ValueError, RuntimeError):
                pass
            else:
                raise AssertionError("stale or externally transacted publication succeeded")
            assert len(doc.Objects) == count

        rejected(tolerance=.2)
        rejected(maximum_geometry_depth=18)
        doc.openTransaction("Unrelated edit")
        rejected()
        assert App.getActiveTransaction()
        doc.abortTransaction()
        # The serialized boundary has not changed yet: dependency dirtiness
        # must still prevent publication of the old mathematical result.
        length = source.Box.Length.Value
        source.Box.Length = length + .01
        assert native.dumps_mixed(source.Geometry) == completed["input_record"]
        rejected()
        source.Box.Length = length
        doc.recompute()
        obj = ImplicitSolid._create(source, completed=completed)
        assert obj.SolidValidated and obj.Geometry is not None
        assert native.dumps_mixed_solids(obj.Geometry) == native.dumps_mixed_solids(
            completed["solid_handle"])
        name = obj.Name
        doc.undo()
        assert doc.getObject(name) is None
        doc.redo()
        obj = doc.getObject(name)
        assert obj is not None and obj.Geometry is not None
        doc.recompute()
    finally:
        native.build_mixed_solids = original
        App.closeDocument(doc.Name)
    print("native implicit solid job publication smoke test passed", flush=True)


try:
    main()
except BaseException:
    traceback.print_exc()
    os._exit(1)
