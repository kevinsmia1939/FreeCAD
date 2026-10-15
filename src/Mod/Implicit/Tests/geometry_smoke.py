# SPDX-License-Identifier: LGPL-2.1-or-later
"""Local native projection and sampled extraction-quality contracts."""
import math
import random
import FreeCAD as App
import Implicit


def reject(call):
    try:
        call()
    except (RuntimeError, ValueError, TypeError, OverflowError):
        return
    raise AssertionError("invalid query accepted")


doc = App.newDocument("GeometryQueries")
try:
    sphere = doc.addObject("Implicit::Feature", "Sphere")
    sphere.Function = "Sphere"
    sphere.Radius = 2
    sphere.DomainMin = (-4, -4, -4)
    sphere.DomainMax = (4, 4, 4)
    doc.recompute()
    rng = random.Random(42)
    for _ in range(60):
        seed = tuple(rng.uniform(-3, 3) for _ in range(3))
        length = math.dist(seed, (0, 0, 0))
        result = Implicit.project(sphere, seed)
        assert result["converged"], (seed, result)
        assert result["status"] == "converged"
        expected = tuple(2 * v / length for v in seed)
        assert math.dist(result["point"], expected) < 1e-7, result
        assert result["residual"] <= 1e-9 and result["stationarity"] <= 1e-7
        assert abs(result["distance"] - abs(length - 2)) < 1e-7
    critical = Implicit.project(sphere, (0, 0, 0))
    assert not critical["converged"] and critical["status"] == "critical_point"
    exact = Implicit.project(sphere, (2, 0, 0))
    assert exact["converged"] and exact["iterations"] == 0
    original = Implicit.project(sphere, (3, 1, 0))
    sphere.Placement.Base = (100, 0, 0)
    sphere.InsideNegative = False
    doc.recompute()
    assert Implicit.project(sphere, (3, 1, 0)) == original
    for args in (((5, 0, 0),), ((float("nan"), 0, 0),),
                 ((3, 0, 0), 0), ((3, 0, 0), 1e-7, -1),
                 ((3, 0, 0), 1e-7, 1e-9, 0), ((3, 0, 0), 1e-7, 1e-9, 257),
                 ((3, 0, 0), 1e-7, 1e-9, 64, float("inf"))):
        reject(lambda args=args: Implicit.project(sphere, *args))

    coarse = Implicit.inspectTessellation(sphere, 8)
    fine = Implicit.inspectTessellation(sphere, 32)
    adaptive = Implicit.inspectTessellation(sphere, 32, True)
    for report in (coarse, fine, adaptive):
        assert report["triangles"] > 0
        assert report["max_vertex_residual"] < 1e-6
        assert report["boundary_edges"] == 0, report
        assert report["non_manifold_edges"] == 0
        assert report["inconsistent_edges"] == 0
        assert report["degenerate_triangles"] == 0
    assert fine["max_centroid_residual"] < coarse["max_centroid_residual"] / 3
    assert fine["max_edge_midpoint_residual"] < coarse["max_edge_midpoint_residual"] / 3
    assert adaptive == fine
    reject(lambda: Implicit.inspectTessellation(sphere, 17, True))
    reject(lambda: Implicit.inspectTessellation(sphere, -1))
    reject(lambda: Implicit.inspectTessellation(sphere, 2**32 + 8))
    sphere.DomainMin = (-1, -1, -1)
    sphere.DomainMax = (1, 1, 1)
    doc.recompute()
    failure = Implicit.project(sphere, (0.5, 0.1, 0.1))
    assert not failure["converged"], failure
    assert all(-1 <= x <= 1 for x in failure["point"])
    empty = Implicit.inspectTessellation(sphere, 8)
    assert empty["triangles"] == 0 and empty["max_centroid_residual"] == 0
    sphere.DomainMin = (-1, -3, -3)
    sphere.DomainMax = (1, 3, 3)
    doc.recompute()
    assert Implicit.inspectTessellation(sphere, 16)["boundary_edges"] > 0

    gyro = doc.addObject("Implicit::Feature", "Gyroid")
    gyro.Period = 10
    doc.recompute()
    for seed in ((0.2, 0.3, 0.4), (1, 1.5, 1.2), (-0.3, 0.5, 0.1)):
        result = Implicit.project(gyro, seed)
        assert result["converged"], result
        assert result["residual"] <= 1e-9 and result["stationarity"] <= 1e-7
    limited = Implicit.project(gyro, (1, 1.5, 1.2), 1e-14, 1e-14, 1)
    assert not limited["converged"] and limited["status"] == "iteration_limit", limited
    gyro.Period = 1e14
    doc.recompute()
    scaled = Implicit.project(gyro, (1, 1, 1))
    assert not (scaled["converged"] and scaled["iterations"] == 0), scaled
    print("native implicit geometry smoke test passed")
finally:
    App.closeDocument(doc.Name)
