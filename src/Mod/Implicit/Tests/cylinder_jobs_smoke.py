# SPDX-License-Identifier: LGPL-2.1-or-later
"""Private cylinder work shares the bounded native queue across both modules."""
import gc
import math
import os
import struct
import time
import traceback
import FreeCAD as App
import Part
import Implicit
import ImplicitOCCT as native


def wait(job, predicate=lambda s: s["state"] in ("ready", "failed", "cancelled")):
    deadline = time.monotonic()+90
    pulses = 0
    while time.monotonic() < deadline:
        status = native.native_job_status(job)
        if predicate(status):
            return status, pulses
        time.sleep(.005)
        pulses += 1
    raise AssertionError(("cylinder worker timed out", status))


def unavailable(job):
    try:
        Implicit.takeCylinderJob(job)
    except RuntimeError:
        return
    raise AssertionError("Unavailable cylinder result returned")


def main():
    field = native.gyroid(10, .21, (-10,-10,-10), (10,10,10))
    records = []
    for negative in (True, False):
        geometry = native.check_cylinder_shell_geometry(field, (0,0,0), (0,0,1), (1,0,0),
            .5, (.27,.27+2*math.pi), (-1.7,1.3), negative=negative)
        solid = native.build_cylinder_solid(geometry["geometry_handle"])
        assert solid["solid_validated"], solid["solid_reason"]
        records.append(native.dumps_cylinder_solid(solid["solid_handle"]))
    doc = App.newDocument("CylinderJobs")
    doc.UndoMode = 1
    obj = doc.addObject("Implicit::NativeCylinderFeature", "Cylinder")
    obj.Geometry = records[0]
    assert obj.GeometryState == "Unverified"
    job = Implicit.submitCylinderJob(obj, 6)
    status, pulses = wait(job)
    assert status["state"] == "ready", status
    assert pulses > 10, ("Python did not execute during cylinder work", pulses)
    for wrong in (native.take_solid_job, native.take_surface_job):
        try:
            wrong(job)
        except TypeError:
            pass
        else:
            raise AssertionError("Cylinder job consumed as another job kind")
    assert native.native_job_status(job)["state"] == "ready"
    result = Implicit.takeCylinderJob(job)
    assert result["input_record"] == records[0] and result["resolution"] == 6
    assert obj.GeometryState == "Unverified", "Worker changed the live document"
    assert native.inspect_qualified_stored_cylinder_solid(result["geometry_handle"])["solid_validated"]
    assert result["preview"]["surface_distance_verified"]
    assert result["preview"]["surface_distance_bound"] <= .1
    assert native.classify_cylinder_material(result["geometry_handle"], (0,0,-.5))["mathematical_state"] == "IN"
    doc.openTransaction("Adopt explicit cylinder result")
    obj.Geometry = result["geometry_handle"]
    doc.commitTransaction()
    synchronous = Implicit.cylinderPreview(obj, 6)
    candidate = result["preview"]
    for key in ("triangles", "native_faces", "native_edges", "native_vertex_count"):
        assert candidate[key] == synchronous[key], key
    upload = lambda rows: [tuple(struct.unpack('f',struct.pack('f',v))[0] for v in row) for row in rows]
    assert upload(candidate["points"]) == upload(synchronous["points"])
    assert upload(candidate["corner_normals"]) == upload(synchronous["corner_normals"])
    assert native.native_job_status(job)["state"] == "consumed"
    unavailable(job)
    doc.undo()
    assert obj.GeometryState == "Unverified"
    doc.redo()
    assert obj.GeometryState == "Ready"
    # Submission freezes the record. Neither an edit nor taking the result
    # authorizes replacing a more recent document owner.
    frozen = native.dumps_cylinder_solid(obj.Geometry)
    job = Implicit.submitCylinderJob(obj, 6)
    obj.Geometry = records[1]
    assert wait(job)[0]["state"] == "ready"
    changed = Implicit.takeCylinderJob(job)
    assert changed["input_record"] == frozen
    assert obj.GeometryState == "Unverified"
    assert not native.inspect_stored_cylinder_solid(obj.Geometry)["negative"]
    assert native.inspect_qualified_stored_cylinder_solid(changed["geometry_handle"])["negative"]
    # A worker request owns only serialized data, independent of the source document.
    job = Implicit.submitCylinderJob(obj, 6)
    App.closeDocument(doc.Name)
    assert wait(job)[0]["state"] == "ready"
    positive = Implicit.takeCylinderJob(job)
    assert native.classify_cylinder_material(positive["geometry_handle"], (0,0,-.5))["mathematical_state"] == "OUT"

    box_field = native.gyroid(10,0,(0,0,0),(10,10,10))
    boundary = native.mixed_box(box_field,Part.makeBox(10,10,10),"common",
                                corner_policy="regularized")["boundary_handle"]
    # Queue capacity is shared with _ImplicitOCCT's box-display API.
    running = Implicit.submitCylinderJob(records[0],64)
    wait(running,lambda s: s["state"] == "running" and s["checkpoints"] > 100)
    queued = native.start_surface_job(boundary)
    assert native.native_job_status(queued)["state"] == "queued"
    try:
        Implicit.submitCylinderJob(records[0],6)
    except RuntimeError as error:
        assert "queue is full" in str(error)
    else:
        raise AssertionError("Modules used independent worker queues")
    native.cancel_native_job(queued)
    native.cancel_native_job(running)
    assert wait(running)[0]["state"] == "cancelled"
    unavailable(running)
    # Model builds preempt the new cylinder presentation jobs, including queued ones.
    running = Implicit.submitCylinderJob(records[0],64)
    wait(running,lambda s: s["state"] == "running" and s["checkpoints"] > 100)
    queued = Implicit.submitCylinderJob(records[0],6)
    model = native.start_solid_job(boundary,.1,32,16,1)
    assert wait(running)[0]["state"] == "cancelled"
    assert wait(queued)[0]["state"] == "cancelled"
    assert wait(model)[0]["state"] == "failed"  # Deliberate model cell budget.
    # Dropped handles cancel queued requests and free their serialized payload.
    running = Implicit.submitCylinderJob(records[0],64)
    wait(running,lambda s: s["state"] == "running" and s["checkpoints"] > 100)
    dropped = Implicit.submitCylinderJob(records[0],6)
    del dropped
    gc.collect()
    replacement = Implicit.submitCylinderJob(records[0],6)
    native.cancel_native_job(replacement)
    native.cancel_native_job(running)
    assert wait(running)[0]["state"] == "cancelled"
    # Cancel a completed candidate before adoption; no geometry escapes.
    job = Implicit.submitCylinderJob(records[0],6)
    assert wait(job)[0]["state"] == "ready"
    native.cancel_native_job(job)
    assert native.native_job_status(job)["state"] == "cancelled"
    unavailable(job)
    failed = Implicit.submitCylinderJob("invalid",6)
    status, _ = wait(failed)
    assert status["state"] == "failed" and status["error"]
    unavailable(failed)
    for source, resolution in ((records[0],1),(records[0],65),("",6),("x"*(16*1024*1024+1),6)):
        try:
            Implicit.submitCylinderJob(source,resolution)
        except ValueError:
            pass
        else:
            raise AssertionError("Invalid request reached the worker")
    print("native cylinder jobs smoke test passed",flush=True)


try:
    main()
except BaseException:
    traceback.print_exc()
    os._exit(1)
