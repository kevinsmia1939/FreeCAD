# SPDX-License-Identifier: LGPL-2.1-or-later

import json
import math
import os
import tempfile
import traceback

import FreeCAD
import Implicit


def close_document(document):
    FreeCAD.closeDocument(document.Name)


def main():
    document = FreeCAD.newDocument("ImplicitNativeSmoke")
    feature = document.addObject("Implicit::Feature", "Field")

    assert feature.TypeId == "Implicit::Feature"
    assert feature.SchemaVersion == 2

    feature.Function = "Gyroid"
    feature.Period = 8.0
    feature.IsoValue = 0.25
    document.recompute()

    assert "Error" not in feature.State, feature.State
    assert math.isclose(Implicit.evaluate(feature, 0.0, 0.0, 0.0), -0.25, abs_tol=1e-12)
    expected_gradient = 2.0 * math.pi / 8.0
    gradient = Implicit.gradient(feature, 0.0, 0.0, 0.0)
    assert all(math.isclose(value, expected_gradient, rel_tol=1e-12) for value in gradient)
    assert Implicit.classify(feature, 0.0, 0.0, 0.0) == "inside"

    feature.Function = "Sphere"
    feature.Center = FreeCAD.Vector(1.0, 2.0, 3.0)
    feature.Radius = 4.0
    document.recompute()

    assert math.isclose(Implicit.evaluate(feature, 1.0, 2.0, 3.0), -4.0, abs_tol=1e-12)
    assert Implicit.classify(feature, 5.0, 2.0, 3.0) == "surface"
    assert Implicit.classify(feature, 6.0, 2.0, 3.0) == "outside"

    gyroid_graph = {
        "schema": 1,
        "root": {"type": "gyroid", "period": 8, "iso": 0.25},
    }
    Implicit.setFieldGraph(feature, json.dumps(gyroid_graph))
    assert math.isclose(Implicit.evaluate(feature, 0.0, 0.0, 0.0), -0.25, abs_tol=1e-12)

    intersection_graph = {
        "schema": 1,
        "root": {
            "type": "intersection",
            "left": {"type": "sphere", "center": [-1, 0, 0], "radius": 2},
            "right": {"type": "sphere", "center": [1, 0, 0], "radius": 2},
        },
    }
    Implicit.setFieldGraph(feature, json.dumps(intersection_graph))
    assert Implicit.classify(feature, 0.0, 0.0, 0.0) == "inside"
    assert Implicit.classify(feature, -2.5, 0.0, 0.0) == "outside"

    graph = {
        "schema": 1,
        "root": {
            "type": "union",
            "left": {
                "type": "difference",
                "left": {"type": "sphere", "center": [0, 0, 0], "radius": 4},
                "right": {"type": "sphere", "center": [0, 0, 0], "radius": 1},
            },
            "right": {
                "type": "translate",
                "offset": [5, 0, 0],
                "field": {
                    "type": "offset",
                    "amount": 0.5,
                    "field": {"type": "sphere", "center": [0, 0, 0], "radius": 1},
                },
            },
        },
    }
    canonical_graph = Implicit.setFieldGraph(feature, json.dumps(graph, indent=2))
    assert canonical_graph == Implicit.validateFieldGraph(canonical_graph)
    assert canonical_graph == Implicit.getFieldGraph(feature)
    document.recompute()

    assert "Error" not in feature.State, feature.State
    assert Implicit.classify(feature, 0.0, 0.0, 0.0) == "outside"
    assert Implicit.classify(feature, 2.0, 0.0, 0.0) == "inside"
    assert Implicit.classify(feature, 5.0, 0.0, 0.0) == "inside"
    assert math.isclose(Implicit.evaluate(feature, 6.5, 0.0, 0.0), 0.0, abs_tol=1e-12)
    assert Implicit.gradient(feature, 6.5, 0.0, 0.0) == (1.0, 0.0, 0.0)

    try:
        Implicit.validateFieldGraph('{"schema":1,"root":{"type":"unknown"}}')
    except RuntimeError as error:
        assert "unsupported field graph node type" in str(error)
    else:
        raise AssertionError("invalid graph unexpectedly validated")

    try:
        Implicit.validateFieldGraph(
            '{"schema":1,"root":{"type":"sphere","center":[0,0,0],"radius":1,"typo":2}}'
        )
    except RuntimeError as error:
        assert "unexpected field graph member" in str(error)
    else:
        raise AssertionError("graph with an unknown member unexpectedly validated")

    handle, path = tempfile.mkstemp(suffix=".FCStd")
    os.close(handle)
    try:
        document.saveAs(path)
        close_document(document)

        restored = FreeCAD.openDocument(path)
        restored_feature = restored.getObject("Field")
        assert restored_feature.TypeId == "Implicit::Feature"
        assert restored_feature.Function == "Sphere"
        assert math.isclose(restored_feature.Radius.Value, 4.0, abs_tol=1e-12)
        assert restored_feature.Center == FreeCAD.Vector(1.0, 2.0, 3.0)
        assert Implicit.getFieldGraph(restored_feature) == canonical_graph
        assert Implicit.classify(restored_feature, 0.0, 0.0, 0.0) == "outside"
        assert Implicit.classify(restored_feature, 2.0, 0.0, 0.0) == "inside"
        close_document(restored)
    finally:
        os.unlink(path)

    print("native implicit smoke test passed")


try:
    main()
except BaseException:
    traceback.print_exc()
    raise
