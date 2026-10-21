# SPDX-License-Identifier: LGPL-2.1-or-later
"""Background solid ownership, cancellation, bounded scheduling and Python responsiveness."""
import gc
import os
import time
import traceback
import Part
import ImplicitOCCT as native


def wait(job, predicate=lambda status: status["state"] in ("ready", "failed", "cancelled")):
    deadline = time.monotonic() + 90
    pulses = 0
    while time.monotonic() < deadline:
        status = native.solid_job_status(job)
        if predicate(status):
            return status, pulses
        pulses += 1
        time.sleep(.005)
    raise AssertionError(("job timed out", status))


def unavailable(job):
    try:
        native.take_solid_job(job)
    except RuntimeError:
        return
    raise AssertionError("unavailable job returned a result")


def main():
    field = native.gyroid(10, 0, (0, 0, 0), (10, 10, 10))
    source = native.mixed_box(field, Part.makeBox(10, 10, 10), "common",
                              corner_policy="regularized")["boundary_handle"]
    record = native.dumps_mixed(source)
    job = native.start_solid_job(source)
    status, pulses = wait(job)
    assert status["state"] == "ready", status
    assert pulses > 10, ("Python did not run during construction", pulses)
    result = native.take_solid_job(job)
    assert result["solid_validated"] and result["native_solid_constructed"]
    assert result["input_record"] == record
    assert result["input_settings"] == (.1, 32, 16, 4000000, 2000000, 2000000,
                                        2000000, 8000000)
    assert result["surface"] and not result["surface_error"]
    assert native.inspect_mixed_solids(result["solid_handle"])["solid_validated"]
    synchronous = native.build_mixed_solids(source)
    assert native.dumps_mixed_solids(result["solid_handle"]) == native.dumps_mixed_solids(
        synchronous["solid_handle"])
    assert native.solid_job_status(job)["state"] == "consumed"
    unavailable(job)
    assert native.dumps_mixed(source) == record

    # Observe actual work before cancelling; the second request remains queued.
    running = native.start_solid_job(source)
    wait(running, lambda s: s["state"] == "running" and s["checkpoints"] > 100)
    queued = native.start_solid_job(source)
    assert native.solid_job_status(queued)["state"] == "queued"
    try:
        native.start_solid_job(source)
    except RuntimeError as error:
        assert "queue is full" in str(error)
    else:
        raise AssertionError("unbounded worker queue")
    native.cancel_solid_job(queued)
    assert wait(queued)[0]["state"] == "cancelled"
    unavailable(queued)
    native.cancel_solid_job(running)
    assert wait(running)[0]["state"] == "cancelled"
    unavailable(running)

    # Dropped handles cancel queued jobs and release the bounded queue slot.
    running = native.start_solid_job(source)
    wait(running, lambda s: s["state"] == "running")
    dropped = native.start_solid_job(source)
    del dropped
    gc.collect()
    replacement = native.start_solid_job(source)
    native.cancel_solid_job(replacement)
    native.cancel_solid_job(running)
    assert wait(running)[0]["state"] == "cancelled"

    failed = native.start_solid_job(source, .1, 32, 16, 1)
    assert wait(failed)[0]["state"] == "failed"
    assert native.solid_job_status(failed)["error"]
    unavailable(failed)
    retry = native.start_solid_job(source)
    assert wait(retry)[0]["state"] == "ready"
    native.cancel_solid_job(retry)
    assert native.solid_job_status(retry)["state"] == "cancelled"
    unavailable(retry)
    assert native.dumps_mixed(source) == record

    # Later phase cancellation must propagate through nested numerical calls,
    # not be swallowed as an ordinary unresolved/display failure.
    for phase in ("geometry", "meshing"):
        job = native.start_solid_job(source)
        status, _ = wait(job, lambda s: s["phase"] == phase or s["state"] in ("ready", "failed"))
        assert status["state"] == "running" and status["phase"] == phase, status
        native.cancel_solid_job(job)
        assert wait(job)[0]["state"] == "cancelled"
        unavailable(job)
        assert native.dumps_mixed(source) == record

    # The worker owns its source independently of every caller-side handle.
    other = native.mixed_box(field, Part.makeBox(10, 10, 10), "box_minus_field",
                            corner_policy="regularized")["boundary_handle"]
    other_record = native.dumps_mixed(other)
    job = native.start_solid_job(other)
    del other, source, field
    gc.collect()
    assert wait(job)[0]["state"] == "ready"
    other_result = native.take_solid_job(job)
    assert other_result["solid_validated"] and other_result["input_record"] == other_record
    print("native implicit solid jobs smoke test passed", flush=True)


try:
    main()
except BaseException:
    traceback.print_exc()
    os._exit(1)
