# SPDX-License-Identifier: LGPL-2.1-or-later
"""Mixed OCCT B-Rep/implicit field composition with persisted snapshots."""
import json
import math
import os
import tempfile
import traceback

import FreeCAD
import Implicit


def main():
    with open(os.environ["IMPLICIT_BREP_FIXTURE"], encoding="utf-8") as stream:
        data = stream.read()
    brep = {"type": "brep", "data": data, "tolerance": 1e-7}
    sphere = {"type": "sphere", "center": [0, 0, 0], "radius": 1.2}
    document = FreeCAD.newDocument("ImplicitMixedSmoke")
    try:
        feature = document.addObject("Implicit::Feature", "Mixed")
        feature.DomainMin = (-1.5, -1.5, -1.5)
        feature.DomainMax = (1.5, 1.5, 1.5)
        Implicit.setFieldGraph(feature, json.dumps({"schema": 1, "root": brep}))
        assert math.isclose(Implicit.evaluate(feature, 0, 0, 0), -1, abs_tol=1e-7)
        assert math.isclose(Implicit.evaluate(feature, 2, 0, 0), 1, abs_tol=1e-7)
        gradient = Implicit.gradient(feature, 2, 0, 0)
        assert all(math.isclose(a, b, abs_tol=1e-5) for a, b in zip(gradient, (1, 0, 0)))

        for operation, center in (("intersection", "inside"), ("union", "inside"),
                                  ("difference", "outside")):
            graph = {"schema": 1, "root": {"type": operation, "left": brep, "right": sphere}}
            Implicit.setFieldGraph(feature, json.dumps(graph))
            document.recompute()
            assert feature.isValid()
            assert Implicit.classify(feature, 0, 0, 0) == center
            assert Implicit.classify(feature, 1.4, 0, 0) == "outside"
        # Keep this coarse: exact B-Rep distance evaluation is expensive.
        graph = {"schema": 1, "root": {"type": "intersection", "left": brep, "right": sphere}}
        canonical = Implicit.setFieldGraph(feature, json.dumps(graph))
        cache = Implicit.tessellate(feature, 4)
        assert cache["triangles"] and len(cache["vertices"]) < 3 * len(cache["triangles"])
        for point in cache["vertices"]:
            assert abs(Implicit.evaluate(feature, *point)) < 2e-6
        with tempfile.TemporaryDirectory(prefix="implicit-mixed-") as directory:
            path = os.path.join(directory, "mixed.FCStd")
            document.recompute()
            document.saveAs(path)
            FreeCAD.closeDocument(document.Name)
            document = FreeCAD.openDocument(path)
            feature = document.getObject("Mixed")
            assert Implicit.getFieldGraph(feature) == canonical
            assert Implicit.classify(feature, 0, 0, 0) == "inside"
            assert Implicit.tessellate(feature, 4) == cache
        try:
            Implicit.validateFieldGraph(json.dumps({"schema": 1,
                "root": {"type": "brep", "data": "invalid", "tolerance": 1e-7}}))
        except RuntimeError:
            pass
        else:
            raise AssertionError("accepted invalid B-Rep")
    finally:
        FreeCAD.closeDocument(document.Name)
    print("native implicit mixed smoke test passed")


try:
    main()
except BaseException:
    traceback.print_exc()
    raise
