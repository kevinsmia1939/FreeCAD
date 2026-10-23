# SPDX-License-Identifier: LGPL-2.1-or-later
"""Normal process exit while private checked-display work is running."""
import os
import time
import traceback
import Part
import ImplicitOCCT as native

try:
    field = native.gyroid(10, 0, (0, 0, 0), (10, 10, 10))
    source = native.mixed_box(field, Part.makeBox(10, 10, 10), "common",
                              corner_policy="regularized")["boundary_handle"]
    job = native.start_surface_job(source, .1, 256, 200000, 400000, True)
    deadline = time.monotonic() + 20
    while True:
        status = native.native_job_status(job)
        if status["phase"] == "coverage" and status["state"] == "running":
            break
        assert status["state"] in ("queued", "running"), status
        assert time.monotonic() < deadline, status
        time.sleep(.005)
    # Keep the capsule alive and let the executor's normal shutdown cancel/join.
    print("native implicit surface job shutdown smoke test passed", flush=True)
except BaseException:
    traceback.print_exc()
    os._exit(1)
