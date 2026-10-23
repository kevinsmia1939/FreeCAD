# SPDX-License-Identifier: LGPL-2.1-or-later
"""Display-only jobs share native scheduling and preserve exact checked buffers."""
import gc
import os
import time
import traceback
import Part
import ImplicitOCCT as native


def wait(job, predicate=lambda s: s["state"] in ("ready", "failed", "cancelled")):
    deadline = time.monotonic() + 90
    ticks = 0
    while time.monotonic() < deadline:
        status = native.native_job_status(job)
        if predicate(status):
            return status, ticks
        time.sleep(.005)
        ticks += 1
    raise AssertionError(("display job timed out", status))


def unavailable(job):
    try:
        native.take_surface_job(job)
    except RuntimeError:
        return
    raise AssertionError("unavailable display result was returned")


def main():
    field = native.gyroid(10, 0, (0, 0, 0), (10, 10, 10))
    source = native.mixed_box(field, Part.makeBox(10, 10, 10), "common",
                              corner_policy="regularized")["boundary_handle"]
    record = native.dumps_mixed(source)
    copied = native.loads_mixed(record)["boundary_handle"]
    for checked in (False, True):
        job = native.start_surface_job(source, .1, 256, 200000, 400000, checked)
        status, ticks = wait(job)
        assert status["state"] == "ready", status
        assert ticks > 10, "Python did not execute during display generation"
        try:
            native.take_solid_job(job)
        except TypeError:
            pass
        else:
            raise AssertionError("display result was mistaken for native solid geometry")
        assert native.native_job_status(job)["state"] == "ready"
        result = native.take_surface_job(job)
        assert result["input_record"] == record
        assert result["input_settings"] == (.1, 256, 200000, 400000, checked, 14,
                                             2000000, 1000000, 2000000, 50000000)
        synchronous = (native.tessellate_mixed_checked if checked else native.tessellate_mixed)(copied)
        assert result["surface"] == synchronous, "worker display differs from the same private-source calculation"
        assert not result["surface"]["solid_validated"]
        assert not result["surface"]["surface_coverage_verified"]
        if checked:
            checks = result["surface"]["display_checks"]
            assert checks["boundary_proximity_resolved"] and checks["triangle_contacts_clear"]
            assert checks["boundary_to_mesh_bound"] <= .1 and checks["mesh_to_boundary_bound"] <= .1
        unavailable(job)

    # Both operation types use the same worker and queue capacity.
    running = native.start_surface_job(source, .1, 256, 200000, 400000, True)
    wait(running, lambda s: s["state"] == "running")
    queued = native.start_solid_job(source)
    try:
        native.take_surface_job(queued)
    except TypeError:
        pass
    else:
        raise AssertionError("solid job accepted as display job")
    try:
        native.start_surface_job(source)
    except RuntimeError as error:
        assert "queue is full" in str(error)
    else:
        raise AssertionError("solid/display jobs exceeded their shared queue limit")
    native.cancel_native_job(queued)
    native.cancel_native_job(running)
    assert wait(running)[0]["state"] == "cancelled"

    for phase in ("coverage", "contact_audit"):
        job = native.start_surface_job(source, .1, 256, 200000, 400000, True)
        status, _ = wait(job, lambda s: s["phase"] == phase or s["state"] in ("ready", "failed"))
        assert status["state"] == "running" and status["phase"] == phase, status
        native.cancel_native_job(job)
        assert wait(job)[0]["state"] == "cancelled"
        unavailable(job)
    limited = native.start_surface_job(source, .1, 256, 200000, 400000, True, 14, 1)
    assert wait(limited)[0]["state"] == "failed"
    unavailable(limited)
    assert native.dumps_mixed(source) == record
    other = native.mixed_box(field, Part.makeBox(10, 10, 10), "box_minus_field",
                             corner_policy="regularized")["boundary_handle"]
    other_record = native.dumps_mixed(other)
    job = native.start_surface_job(other)
    assert wait(job)[0]["state"] == "ready"
    cut = native.take_surface_job(job)
    assert cut["input_record"] == other_record
    assert cut["surface"] == native.tessellate_mixed(native.loads_mixed(other_record)["boundary_handle"])
    del other
    # Independent source lifetime; cancelling a ready job discards the candidate.
    job = native.start_surface_job(source)
    del source, copied, field
    gc.collect()
    assert wait(job)[0]["state"] == "ready"
    native.cancel_native_job(job)
    assert native.native_job_status(job)["state"] == "cancelled"
    unavailable(job)
    print("native implicit surface jobs smoke test passed", flush=True)


try:
    main()
except BaseException:
    traceback.print_exc()
    os._exit(1)
