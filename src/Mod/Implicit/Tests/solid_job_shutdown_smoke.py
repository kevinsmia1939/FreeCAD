# SPDX-License-Identifier: LGPL-2.1-or-later
"""Normal process shutdown while native work is active (CTest bounds exit time)."""
import os
import time
import traceback
import Part
import ImplicitOCCT as native

try:
    field = native.gyroid(10, 0, (0, 0, 0), (10, 10, 10))
    source = native.mixed_box(field, Part.makeBox(10, 10, 10), "common",
                              corner_policy="regularized")["boundary_handle"]
    active = native.start_solid_job(source)
    deadline = time.monotonic() + 10
    while True:
        status = native.solid_job_status(active)
        if status["state"] == "running" and status["checkpoints"] > 100:
            break
        assert time.monotonic() < deadline, status
        time.sleep(.001)
    queued = native.start_solid_job(source)
    assert native.solid_job_status(queued)["state"] == "queued"
    # Deliberately retain both handles; no explicit cancellation or os._exit.
    print("native implicit solid job shutdown smoke test passed", flush=True)
except BaseException:
    traceback.print_exc()
    os._exit(1)
