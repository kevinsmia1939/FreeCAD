# SPDX-License-Identifier: LGPL-2.1-or-later
"""Fixed-normal chart generation rejects missing, ambiguous or folded samples."""
import math
import FreeCAD as App
import Implicit


def rejected(call):
    try:
        call()
    except (RuntimeError, TypeError, ValueError, OverflowError):
        return
    raise AssertionError("invalid chart accepted")


doc = App.newDocument("ChartSmoke")
try:
    field = doc.addObject("Implicit::Feature", "Sphere")
    field.Function = "Sphere"
    field.Radius = 2
    field.DomainMin, field.DomainMax = (-3, -3, -3), (3, 3, 3)
    doc.recompute()
    chart = Implicit.sampleChart(field, (0, 0, 2.2), 1.2, 1.2, 0.75)
    assert len(chart["points"]) == 9 and all(len(row) == 9 for row in chart["points"])
    assert chart["max_residual"] < 1e-9
    assert chart["minimum_alignment"] > 0.8
    assert math.dist(chart["center"], (0, 0, 2)) < 1e-8
    for row in chart["points"]:
        for p in row:
            assert abs(math.dist(p, (0, 0, 0)) - 2) < 1e-9
            assert p[2] > 1.8
    field.Placement.Base = (100, 0, 0)
    doc.recompute()
    assert Implicit.sampleChart(field, (0, 0, 2.2), 1.2, 1.2, 0.75) == chart
    rejected(lambda: Implicit.sampleChart(field, (0, 0, 0), 1, 1, 1))
    rejected(lambda: Implicit.sampleChart(field, (0, 0, 2), 1, 1, 5))  # Both sphere sides.
    rejected(lambda: Implicit.sampleChart(field, (0, 0, 2), 5, 5, 0.75))  # Outside graph chart.
    rejected(lambda: Implicit.sampleChart(field, (0, 0, 2), 1, 1, 0.75, 3))
    rejected(lambda: Implicit.sampleChart(field, (0, 0, 2), -1, 1, 0.75))
    rejected(lambda: Implicit.sampleChart(field, (0, 0, 2), 1, 1, 0.75, 33, 4096))
    token = Implicit.newCancellationToken()
    Implicit.cancel(token)
    rejected(lambda: Implicit.sampleChart(field, (0, 0, 2), 1, 1, 0.75, 9, 128, 1e-9, 0.2, token))
    field.Function = "Gyroid"
    field.Period = 10
    doc.recompute()
    gyro = Implicit.sampleChart(field, (0, 0, 0), 1, 1, 0.5)
    assert gyro["max_residual"] < 1e-8 and gyro["minimum_alignment"] > 0.9
    print("native implicit chart smoke test passed")
finally:
    App.closeDocument(doc.Name)
