# SPDX-License-Identifier: LGPL-2.1-or-later
"""Normal process exit while private source tracing is running."""
import os
import time
import traceback
import Part
import ImplicitOCCT as native

try:
    field = native.gyroid(10, 0, (0, 0, 0), (10, 10, 10))
    job = native.start_boundary_job(field, Part.makeBox(10, 10, 10), corner_policy="regularized")
    deadline = time.monotonic() + 20
    while True:
        status = native.native_job_status(job)
        if status["state"] == "running" and status["checkpoints"] >= 100:
            break
        assert status["state"] in ("queued", "running"), status
        assert time.monotonic() < deadline, status
        time.sleep(.0001)
    print("native implicit boundary job shutdown smoke test passed", flush=True)
except BaseException:
    traceback.print_exc()
    os._exit(1)
