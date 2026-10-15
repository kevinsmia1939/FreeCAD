# SPDX-License-Identifier: LGPL-2.1-or-later
"""Field-bound refinement is not a surface coverage or solid certificate."""
import math
import FreeCAD as App
import Implicit


def rejected(call):
    try:
        call()
    except (RuntimeError, ValueError, TypeError, OverflowError):
        return
    raise AssertionError("invalid controlled extraction accepted")


doc = App.newDocument("ControlledExtraction")
try:
    field = doc.addObject("Implicit::Feature", "Sphere")
    field.Function = "Sphere"
    field.Radius = 2
    field.DomainMin = (-3, -3, -3)
    field.DomainMax = (3, 3, 3)
    doc.recompute()
    result = Implicit.tessellateControlled(field, 0.4, 4, 32)
    assert result["tolerance_met"] and result["status"] == "field_bound_met", result["history"]
    assert not result["surface_coverage_verified"]
    assert len(result["history"]) > 1
    assert result["quality"]["max_triangle_residual_bound"] <= 0.4
    for triangle in result["triangles"][::7]:
        vertices = [result["vertices"][i] for i in triangle]
        for weights in ((0.2, 0.3, 0.5), (0.1, 0.8, 0.1), (0, 0.5, 0.5)):
            point = tuple(sum(w * p[axis] for w, p in zip(weights, vertices)) for axis in range(3))
            assert abs(Implicit.evaluate(field, *point)) <= result["quality"]["max_triangle_residual_bound"]
    failed = Implicit.tessellateControlled(field, 1e-12, 4, 8)
    assert not failed["tolerance_met"] and failed["status"] == "resolution_limit"
    assert [step["resolution"] for step in failed["history"]] == [4, 8]
    assert failed["quality"]["max_triangle_residual_bound"] > 1e-12
    field.Radius = 20
    doc.recompute()
    empty = Implicit.tessellateControlled(field, 1, 4, 8)
    assert empty["status"] == "empty_unverified" and not empty["tolerance_met"]
    assert empty["triangles"] == [] and len(empty["history"]) == 2
    field.Function = "Gyroid"
    field.Period = 10
    doc.recompute()
    gyro = Implicit.tessellateControlled(field, 1, 8, 32)
    assert gyro["tolerance_met"], gyro["history"]
    assert gyro["quality"]["max_triangle_residual_bound"] <= 1
    token = Implicit.newCancellationToken()
    Implicit.cancel(token)
    rejected(lambda: Implicit.tessellateControlled(field, 1, 8, 32, token))
    for args in ((0,), (float("nan"),), (1, 3, 8), (1, 8, 4), (1, -1, 8), (1, 8, 128)):
        rejected(lambda args=args: Implicit.tessellateControlled(field, *args))
    print("native implicit controlled smoke test passed")
finally:
    App.closeDocument(doc.Name)
