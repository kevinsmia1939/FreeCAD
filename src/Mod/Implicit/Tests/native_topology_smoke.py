# SPDX-License-Identifier: LGPL-2.1-or-later
"""Native whole-boundary edge/vertex identity, not sampled display points."""
import os
import traceback
import FreeCAD as App
import Implicit
import ImplicitMixed
import ImplicitOCCT as native
import Part


def check(obj):
    data = native.inspect_mixed(obj.Geometry)
    geometry = Implicit.nativeGeometry(obj)
    assert geometry.countSubElements("Edge") == len(data["edge_points"])
    assert geometry.countSubElements("Vertex") == len(data["vertex_points"])
    assert len(data["seam_edges"]) == geometry.countSubElements("Seam")
    assert len(set(data["seam_edges"])) == len(data["seam_edges"])
    assert len(data["edge_vertices"]) == len(data["edge_points"])
    cap_vertices = [v.Point for cap in data["planar_caps"] for v in cap.Vertexes]
    for i, p in enumerate(data["vertex_points"], 1):
        points, lines = geometry.getLinesFromSubElement("Vertex", i)
        assert len(points) == 1 and tuple(points[0]) == p and not lines
        assert any((App.Vector(p) - v).Length < 1e-10 for v in cap_vertices)
        selected = obj.getSubObject("Vertex" + str(i), transform=False)
        assert selected.getPoints(.1) == (points, [])
        assert selected.BoundBox.isValid() and selected.BoundBox.DiagonalLength == 0
    for i, (points, endpoints) in enumerate(zip(data["edge_points"], data["edge_vertices"]), 1):
        sampled, lines = geometry.getLinesFromSubElement("Edge", i)
        assert [tuple(p) for p in sampled] == points
        assert lines == [(j, j + 1) for j in range(len(points) - 1)]
        for p, index in zip((points[0], points[-1]), endpoints):
            assert 0 <= index < len(data["vertex_points"])
            assert (App.Vector(p) - App.Vector(data["vertex_points"][index])).Length < 1e-10
    for i, edge in enumerate(data["seam_edges"], 1):
        assert data["seams"][i - 1] == data["edge_points"][edge]
        assert geometry.getLinesFromSubElement("Seam", i) == geometry.getLinesFromSubElement("Edge", edge + 1)
    copied = obj.Proxy.native_boundary()
    copied["edge_points"][0][0] = (999, 999, 999)
    copied["vertex_points"][0] = (999, 999, 999)
    copied["edge_vertices"][0] = (999, 999)
    copied["seam_edges"][0] = 999
    current = obj.Proxy.native_boundary()
    for key in ("edge_points", "vertex_points", "edge_vertices", "seam_edges"):
        assert current[key] == data[key], "preview metadata was not independently copied"
    for kind in ("Edge", "Vertex"):
        selected = obj.getSubObject(kind + "1")
        try:
            Part.Shape(selected)
        except TypeError:
            pass
        else:
            raise AssertionError("native topology silently became a conventional Part shape")
    # Polyline refinement points are NOT native topological vertices.
    assert sum(map(len, data["edge_points"])) > len(data["vertex_points"])
    restored = obj.Document.addObject("Implicit::NativeFeaturePython", "RestoredTopology")
    restored.Geometry = native.dumps_mixed(obj.Geometry)
    roundtrip = native.inspect_mixed(restored.Geometry)
    for key in ("edge_points", "vertex_points", "edge_vertices", "seam_edges"):
        if key == "vertex_points":
            # Standard BRep vertex text is 15 significant decimal digits.
            # Require machine-scale proximity, NOT the much looser .1 mm target.
            magnitude = max(1, *(abs(v) for p in data[key] for v in p))
            reserve = 128 * 2.220446049250313e-16 * magnitude
            assert len(data[key]) == len(roundtrip[key])
            for p, q in zip(data[key], roundtrip[key]):
                assert (App.Vector(p) - App.Vector(q)).Length <= reserve, (key, p, q)
        else:
            assert data[key] == roundtrip[key], key
    before = Implicit.nativeGeometry(obj)
    after = Implicit.nativeGeometry(restored)
    for kind in ("Edge", "Vertex"):
        for i in range(1, before.countSubElements(kind) + 1):
            name = kind + str(i)
            assert before.getElementName(name, 1) == after.getElementName(name, 1)
    return geometry


def main():
    for crossing in (False, True):
        obj = ImplicitMixed.demo(open_contours=crossing)
        for operation in ("Common", "BoxMinusField"):
            obj.Operation = operation
            obj.Document.recompute()
            retained = check(obj)
        App.closeDocument(obj.Document.Name)
    assert retained.getLinesFromSubElement("Vertex", 1)[0]
    print("native implicit topology smoke test passed", flush=True)


try:
    main()
except BaseException:
    traceback.print_exc()
    os._exit(1)
