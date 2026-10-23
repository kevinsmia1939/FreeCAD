# SPDX-License-Identifier: LGPL-2.1-or-later
"""Private source tracing, worker kind/queue guards and cooperative cancellation."""
import os
import time
import traceback
import Part
import FreeCAD as App
import ImplicitOCCT as native
from _ImplicitOCCT import start_boundary_job as raw_start


def wait(job, predicate=lambda s: s["state"] in ("ready", "failed", "cancelled")):
    deadline = time.monotonic() + 60
    ticks = 0
    while time.monotonic() < deadline:
        status = native.native_job_status(job)
        if predicate(status):
            return status, ticks
        time.sleep(.0005)
        ticks += 1
    raise AssertionError(("boundary job timed out", status))


def unavailable(job):
    try:
        native.take_boundary_job(job)
    except RuntimeError:
        return
    raise AssertionError("Unavailable boundary result returned")


def main():
    field = native.gyroid(10, 0, (0, 0, 0), (10, 10, 10))
    box = Part.makeBox(10, 10, 10)
    field_record, box_record = native.dumps(field), box.exportBrepToString()
    for operation in ("common", "box_minus_field"):
        job = native.start_boundary_job(field, box, operation, corner_policy="regularized")
        status, ticks = wait(job)
        assert status["state"] == "ready", status
        assert ticks > 0, "Python did not run during boundary preparation"
        total = status["checkpoints"]
        assert total > 20
        for wrong in (native.take_solid_job, native.take_surface_job):
            try:
                wrong(job)
            except TypeError:
                pass
            else:
                raise AssertionError("Wrong-kind take accepted a boundary job")
            assert native.native_job_status(job)["state"] == "ready"
        result = native.take_boundary_job(job)
        assert result["input_field"] == field_record and result["input_box"] == box_record
        assert result["input_settings"] == (operation, .1, 512, "regularized")
        reference = native.mixed_box(native.loads(field_record), box, operation,
                                     corner_policy="regularized")
        assert native.dumps_mixed(result["boundary_handle"]) == native.dumps_mixed(reference["boundary_handle"])
        assert result["seam_bound_verified"] == reference["seam_bound_verified"]
        unavailable(job)

        cancelled = native.start_boundary_job(field, box, operation, corner_policy="regularized")
        status, _ = wait(cancelled, lambda s: s["state"] in ("ready", "failed", "cancelled")
                         or s["checkpoints"] >= total // 4)
        assert status["state"] == "running", status
        native.cancel_native_job(cancelled)
        assert wait(cancelled)[0]["state"] == "cancelled"
        unavailable(cancelled)
        assert native.dumps(field) == field_record and box.exportBrepToString() == box_record
        retry = native.start_boundary_job(field, box, operation, corner_policy="regularized")
        assert wait(retry)[0]["state"] == "ready"
        assert native.dumps_mixed(native.take_boundary_job(retry)["boundary_handle"]) == native.dumps_mixed(reference["boundary_handle"])

    # The worker owns records, never the original mutable Part object.
    private = native.start_boundary_job(field, box, corner_policy="regularized")
    box.translate((1, 0, 0))
    del field, box
    assert wait(private)[0]["state"] == "ready"
    result = native.take_boundary_job(private)
    assert result["input_field"] == field_record and result["input_box"] == box_record

    # Saturation is shared across job kinds; cancelled queued work is removable.
    source = result["boundary_handle"]
    active = native.start_surface_job(source, .1, 256, 200000, 400000, True)
    wait(active, lambda s: s["state"] == "running")
    original = Part.Shape(); original.importBrepFromString(box_record)
    queued = native.start_boundary_job(native.loads(field_record), original, corner_policy="regularized")
    try:
        native.start_solid_job(source)
    except RuntimeError as error:
        assert "queue is full" in str(error)
    else:
        raise AssertionError("Mixed worker queue was unbounded")
    native.cancel_native_job(queued)
    assert wait(queued)[0]["state"] == "cancelled"
    native.cancel_native_job(active)
    assert wait(active)[0]["state"] == "cancelled"

    malformed = raw_start(native.loads(field_record), "bad B-Rep snapshot", "common")
    assert wait(malformed)[0]["state"] == "failed"
    unavailable(malformed)
    unsupported = native.start_boundary_job(native.loads(field_record), Part.makeCylinder(2, 5))
    assert wait(unsupported)[0]["state"] == "failed"
    unavailable(unsupported)
    rejected = native.start_boundary_job(native.loads(field_record), original)  # strict corners reject
    assert wait(rejected)[0]["state"] == "failed"
    unavailable(rejected)
    strict_field = native.gyroid(10, 1.45, (-5, -5, -5), (6, 6, 6))
    strict_box = Part.makeBox(3.24, 3.28, 2.75, App.Vector(-.31, -.37, 1.25))
    for operation in ("common", "box_minus_field"):
        job = native.start_boundary_job(strict_field, strict_box, operation)
        status, _ = wait(job)
        assert status["state"] == "ready", (operation, status)
        result = native.take_boundary_job(job)
        reference = native.mixed_box(strict_field, strict_box, operation)
        assert native.dumps_mixed(result["boundary_handle"]) == native.dumps_mixed(reference["boundary_handle"])
        assert not result["solid_validated"]
        assert result["input_settings"] == (operation, .1, 512, "reject")
    for settings in ({"operation": "fuse"}, {"corner_policy": "guess"},
                     {"tolerance": float("nan")}, {"maximum_cells": 3}):
        try:
            native.start_boundary_job(strict_field, strict_box, **settings)
        except ValueError:
            pass
        else:
            raise AssertionError(("Invalid boundary job settings accepted", settings))
    print("native implicit boundary jobs smoke test passed", flush=True)


try:
    main()
except BaseException:
    traceback.print_exc()
    os._exit(1)
