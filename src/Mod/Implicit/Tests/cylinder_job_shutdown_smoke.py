# SPDX-License-Identifier: LGPL-2.1-or-later
"""Normal runtime shutdown cancels and joins outstanding cylinder work."""
import math
import os
import time
import traceback
import Implicit
import ImplicitOCCT as native
try:
    source=native.gyroid(10,.21,(-10,-10,-10),(10,10,10))
    geometry=native.check_cylinder_shell_geometry(source,(0,0,0),(0,0,1),(1,0,0),
        .5,(.27,.27+2*math.pi),(-1.7,1.3))
    solid=native.build_cylinder_solid(geometry["geometry_handle"])
    record=native.dumps_cylinder_solid(solid["solid_handle"])
    running=Implicit.submitCylinderJob(record,64)
    deadline=time.monotonic()+30
    while time.monotonic()<deadline:
        status=native.native_job_status(running)
        if status["state"]=="running" and status["checkpoints"]>100:
            break
        time.sleep(.005)
    else:
        raise AssertionError(status)
    queued=Implicit.submitCylinderJob(record,6)
    assert native.native_job_status(queued)["state"]=="queued"
    print("native cylinder job shutdown smoke test passed",flush=True)
except BaseException:
    traceback.print_exc()
    os._exit(1)
