# SPDX-License-Identifier: LGPL-2.1-or-later
"""Native field queries, independent of disposable display meshes."""
import math
import FreeCAD as App
import Implicit


def rejected(call):
    try:
        call()
    except (RuntimeError, TypeError, ValueError, OverflowError):
        return
    raise AssertionError("invalid ray was accepted")


doc = App.newDocument("NativeRaySmoke")
try:
    sphere = doc.addObject("Implicit::Feature", "Sphere")
    sphere.Function = "Sphere"
    sphere.Radius = 2
    sphere.DomainMin = (-3, -3, -3)
    sphere.DomainMax = (3, 3, 3)
    doc.recompute()

    def ray(origin=(-5, 0, 0), direction=(4, 0, 0), low=0, high=10, samples=31, tol=1e-9):
        return Implicit.intersectRay(sphere, origin, direction, low, high, samples, tol)

    hits = ray()
    assert len(hits) == 2
    for hit, distance in zip(hits, (3, 7)):
        assert abs(hit["distance"] - distance) <= 1e-9
        assert hit["bracket_width"] <= 1e-9
        assert hit["residual"] <= 1e-9
        assert abs(math.dist(hit["point"], (0, 0, 0)) - 2) <= 1e-9
    assert len(ray(origin=(0, 0, 0))) == 1
    assert ray(origin=(-5, 4, 0)) == []  # Parallel slab miss.
    assert ray(direction=(-1, 0, 0)) == []
    assert len(ray(low=3, high=3)) == 1
    assert ray(low=4, high=4) == []
    assert len(ray(low=3, high=7, samples=4)) == 2  # Exact endpoint roots.
    assert len(ray(origin=(5, 0, 0), direction=(1, 0, 0), low=-10, high=0)) == 2
    assert ray(origin=(-5, 2, 0), samples=31) == []  # Unsampled tangency is missed.
    assert len(ray(origin=(-5, 2, 0), samples=32)) == 1  # Exact sampled tangency.
    sphere.InsideNegative = False
    sphere.Placement.Base = App.Vector(100, 0, 0)
    doc.recompute()
    assert ray() == hits  # Feature-local and independent of inside convention.
    sphere.DomainMin = (-1, -1, -1)
    sphere.DomainMax = (1, 1, 1)
    doc.recompute()
    assert ray() == []  # Clipping does not invent caps at the box boundary.

    for changes in ({"direction": (0, 0, 0)}, {"origin": (float("nan"), 0, 0)},
                    {"high": float("inf")}, {"low": 2, "high": 1},
                    {"samples": 0}, {"samples": -1}, {"samples": 65537},
                    {"tol": 0}, {"tol": float("nan")}):
        rejected(lambda changes=changes: ray(**changes))
    rejected(lambda: Implicit.intersectRay(doc, (0, 0, 0), (1, 0, 0), 0, 1))

    gyroid = doc.addObject("Implicit::Feature", "Gyroid")
    gyroid.Period = 10
    gyroid.DomainMin = (-12, -1, -1)
    gyroid.DomainMax = (12, 1, 1)
    doc.recompute()
    roots = Implicit.intersectRay(gyroid, (-12, 0, 0), (1, 0, 0), 0, 24, 127, 1e-9)
    assert len(roots) == 5
    for root, x in zip(roots, (-10, -5, 0, 5, 10)):
        assert abs(root["point"][0] - x) <= 1e-9
        assert root["residual"] <= 1e-9

    Implicit.setFieldGraph(sphere, '{"schema":1,"root":{"type":"band",'
                           '"halfWidth":0.25,"field":{"type":"sphere",'
                           '"center":[0,0,0],"radius":2}}}')
    sphere.DomainMin = (-3, -3, -3)
    sphere.DomainMax = (3, 3, 3)
    doc.recompute()
    roots = ray(samples=127)
    assert len(roots) == 4, roots
    for root, distance in zip(roots, (2.75, 3.25, 6.75, 7.25)):
        assert abs(root["distance"] - distance) <= 1e-9

    # A ray lying on a box face has no isolated-root interpretation.
    Implicit.setFieldGraph(sphere, '{"schema":1,"root":{"type":"box",'
                           '"center":[0,0,0],"halfSize":[1,1,1]}}')
    sphere.DomainMin = (-2, -2, -2)
    sphere.DomainMax = (2, 2, 2)
    doc.recompute()
    rejected(lambda: ray(origin=(-0.5, 1, 0), low=0, high=1, samples=4))
    print("native implicit ray smoke test passed")
finally:
    App.closeDocument(doc.Name)
