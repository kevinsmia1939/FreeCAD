# SPDX-License-Identifier: LGPL-2.1-or-later
"""Scalar controls, spatial band gradients, smooth CSG and persistence."""
import json
import math
import os
import random
import tempfile
import FreeCAD as App
import Implicit


def set_graph(feature, root):
    Implicit.setFieldGraph(feature, json.dumps({"schema": 1, "root": root}))
    feature.Document.recompute()
    assert feature.isValid()


def gradient_check(feature, point):
    actual = Implicit.gradient(feature, *point)
    h = 1e-5
    for axis in range(3):
        low, high = list(point), list(point)
        low[axis] -= h
        high[axis] += h
        numeric = (Implicit.evaluate(feature, *high) - Implicit.evaluate(feature, *low)) / (2 * h)
        assert abs(actual[axis] - numeric) < 1e-7, (point, actual, numeric)


doc = App.newDocument("ScalarControls")
try:
    field = doc.addObject("Implicit::Feature", "Field")
    field.DomainMin, field.DomainMax = (-4, -4, -4), (4, 4, 4)
    set_graph(field, {"type": "constant", "value": -0.25})
    assert Implicit.evaluate(field, 3, 2, 1) == -0.25
    assert Implicit.gradient(field, 3, 2, 1) == (0, 0, 0)
    set_graph(field, {"type": "linear", "slope": [1, -2, 3], "intercept": 0.5})
    assert Implicit.evaluate(field, 1, 2, 3) == 6.5
    gradient_check(field, (1, 2, 3))
    sphere = {"type": "sphere", "center": [0, 0, 0], "radius": 2}
    set_graph(field, {"type": "variable_band", "field": sphere,
                      "width": {"type": "linear", "slope": [0.05, 0, 0], "intercept": 0.2}})
    assert Implicit.evaluate(field, 2.3, 0, 0) < 0
    assert Implicit.evaluate(field, -2.3, 0, 0) > 0
    gradient_check(field, (2.3, 0.2, 0.1))
    gradient_check(field, (1.5, 0.2, 0.1))
    set_graph(field, {"type": "variable_band", "field": sphere,
                      "width": {"type": "constant", "value": -0.1}})
    assert Implicit.evaluate(field, 2, 0, 0) > 0  # Negative widths define no interior.

    set_graph(field, {"type": "smooth_union", "left": sphere, "right": sphere, "blend": 0.4})
    assert math.isclose(Implicit.evaluate(field, 3, 0, 0), 0.9, abs_tol=1e-12)
    left, right = dict(sphere, center=[-1, 0, 0]), dict(sphere, center=[1, 0, 0])
    root = {"type": "smooth_union", "left": left, "right": right, "blend": 0.7}
    set_graph(field, root)
    rng = random.Random(17)
    points = [tuple(rng.uniform(-3, 3) for _ in range(3)) for _ in range(40)]
    for p, q in zip(points, points[1:]):
        gradient_check(field, p)
        assert math.dist(Implicit.gradient(field, *p), (0, 0, 0)) <= 1 + 1e-12
        assert abs(Implicit.evaluate(field, *p) - Implicit.evaluate(field, *q)) <= math.dist(p, q) + 1e-12
    mesh = Implicit.tessellateControlled(field, 0.5, 8, 32)
    assert mesh["tolerance_met"] and mesh["triangles"], mesh["history"]
    canonical = Implicit.getFieldGraph(field)
    expected = Implicit.evaluateBatch(field, points)
    with tempfile.TemporaryDirectory(prefix="implicit-scalars-") as directory:
        path = os.path.join(directory, "scalar.FCStd")
        doc.saveAs(path)
        App.closeDocument(doc.Name)
        doc = App.openDocument(path)
        field = doc.getObject("Field")
        assert Implicit.getFieldGraph(field) == canonical
        assert Implicit.evaluateBatch(field, points) == expected
    for invalid in (dict(root, blend=0), dict(root, blend=-1),
                    {"type": "linear", "slope": [1, 2], "intercept": 0},
                    {"type": "variable_band", "field": sphere, "width": 0.3},
                    {"type": "constant", "value": 1, "misspelled": 1}):
        try:
            Implicit.validateFieldGraph(json.dumps({"schema": 1, "root": invalid}))
        except RuntimeError:
            pass
        else:
            raise AssertionError("invalid scalar graph accepted")
    print("native implicit scalar smoke test passed")
finally:
    App.closeDocument(doc.Name)
