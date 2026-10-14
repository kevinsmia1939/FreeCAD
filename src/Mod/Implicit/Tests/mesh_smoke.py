# SPDX-License-Identifier: LGPL-2.1-or-later

"""Numerical and connectivity regression checks for native display extraction."""

from collections import Counter
import json
import math
import os
import tempfile
import traceback

import FreeCAD
import Implicit


def subtract(a, b):
    return tuple(x - y for x, y in zip(a, b))


def cross(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def check_mesh(feature, mesh, closed=False, euler=None, smooth=True):
    vertices, normals, triangles = (mesh[key] for key in ("vertices", "normals", "triangles"))
    assert vertices and triangles
    assert len(vertices) == len(normals)
    assert len(vertices) < 3 * len(triangles), "vertices were not shared"
    assert len(set(vertices)) == len(vertices), "duplicate root positions"
    edges = Counter()
    oriented_edges = Counter()
    for point, normal in zip(vertices, normals):
        assert all(math.isfinite(x) for x in (*point, *normal))
        assert abs(Implicit.evaluate(feature, *point)) < 1e-6
        assert math.isclose(dot(normal, normal), 1.0, abs_tol=1e-10)
        assert all(lo <= value <= hi for value, lo, hi in
                   zip(point, feature.DomainMin, feature.DomainMax))
    for a, b, c in triangles:
        assert len({a, b, c}) == 3
        assert all(0 <= i < len(vertices) for i in (a, b, c))
        face_normal = cross(subtract(vertices[b], vertices[a]),
                            subtract(vertices[c], vertices[a]))
        assert dot(face_normal, face_normal) > 0
        mean_normal = tuple(normals[a][i] + normals[b][i] + normals[c][i]
                            for i in range(3))
        if smooth:
            assert dot(face_normal, mean_normal) > 0
        for edge in ((a, b), (b, c), (c, a)):
            edges[tuple(sorted(edge))] += 1
            oriented_edges[edge] += 1
    if closed:
        assert set(edges.values()) == {2}, Counter(edges.values())
        assert all(oriented_edges[(b, a)] == 1 for a, b in oriented_edges)
    if euler is not None:
        used = {i for triangle in triangles for i in triangle}
        assert len(used) - len(edges) + len(triangles) == euler
    return edges


def main():
    document = FreeCAD.newDocument("ImplicitMeshSmoke")
    try:
        feature = document.addObject("Implicit::Feature", "Field")
        feature.Function = "Sphere"
        feature.Radius = 1
        feature.DomainMin = (-2, -2, -2)
        feature.DomainMax = (2, 2, 2)
        document.recompute()
        # This grid puts some roots exactly on grid nodes.
        sphere = Implicit.tessellate(feature, 16)
        assert sphere["sample_count"] == 17 ** 3
        check_mesh(feature, sphere, closed=True, euler=2)
        assert sphere == Implicit.tessellate(feature, 16), "non-deterministic extraction"
        adaptive = Implicit.tessellateAdaptive(feature, 16)
        check_mesh(feature, adaptive, closed=True, euler=2)
        assert adaptive["pruned_blocks"] > 0
        assert adaptive["sample_count"] < sphere["sample_count"]
        def geometry(mesh):
            return {tuple(sorted(mesh["vertices"][index] for index in triangle))
                    for triangle in mesh["triangles"]}
        assert geometry(adaptive) == geometry(sphere)
        for point, normal in zip(sphere["vertices"], sphere["normals"]):
            assert dot(point, normal) > 0

        feature.InsideNegative = False
        reversed_mesh = Implicit.tessellate(feature, 16)
        check_mesh(feature, reversed_mesh, closed=True, euler=2)
        assert reversed_mesh["vertices"] == sphere["vertices"]
        for point, normal in zip(reversed_mesh["vertices"], reversed_mesh["normals"]):
            assert dot(point, normal) < 0
        feature.InsideNegative = True

        # Tessellation, like evaluate(), uses local coordinates; the renderer
        # applies Placement once. A changed placement must not move local roots.
        feature.Placement = FreeCAD.Placement(FreeCAD.Vector(10, 20, 30), FreeCAD.Rotation())
        assert feature.Placement.Base == FreeCAD.Vector(10, 20, 30)
        assert Implicit.tessellate(feature, 16) == sphere

        graph = {"schema": 1, "root": {
            "type": "difference",
            "left": {"type": "sphere", "center": [0, 0, 0], "radius": 1.4},
            "right": {"type": "sphere", "center": [0, 0, 0], "radius": 0.6}}}
        Implicit.setFieldGraph(feature, json.dumps(graph))
        shell = Implicit.tessellate(feature, 20)
        check_mesh(feature, shell, closed=True, euler=4)

        with tempfile.TemporaryDirectory(prefix="implicit-native-mesh-") as directory:
            path = os.path.join(directory, "mesh.FCStd")
            document.recompute()
            document.saveAs(path)
            FreeCAD.closeDocument(document.Name)
            document = FreeCAD.openDocument(path)
            feature = document.getObject("Field")
            assert Implicit.tessellate(feature, 20) == shell

        feature.FieldGraph = ""
        feature.Radius = 10
        empty = Implicit.tessellate(feature)
        assert not empty["vertices"] and not empty["triangles"]
        assert empty["sample_count"] == 25 ** 3
        empty_adaptive = Implicit.tessellateAdaptive(feature, 32)
        assert empty_adaptive["sample_count"] == 1
        assert empty_adaptive["pruned_blocks"] == 1
        assert not empty_adaptive["triangles"]

        feature.Radius = 1
        feature.DomainMin = (-0.75, -0.75, -0.75)
        feature.DomainMax = (0.75, 0.75, 0.75)
        clipped = Implicit.tessellate(feature, 12)
        edges = check_mesh(feature, clipped)
        assert 1 in edges.values(), "clipped zero surface was unexpectedly capped"

        feature.Function = "Gyroid"
        feature.Period = 4
        feature.IsoValue = 0.17
        feature.DomainMin = (-2, -2, -2)
        feature.DomainMax = (2, 2, 2)
        check_mesh(feature, Implicit.tessellate(feature, 12))

        # The box supplies real field boundaries, unlike computational-domain
        # clipping. A gyroid band clipped by this box should have paired edges.
        capped = {"schema": 1, "root": {"type": "intersection",
            "left": {"type": "band", "halfWidth": 0.3,
                     "field": {"type": "gyroid", "period": 4, "iso": 0.17}},
            "right": {"type": "box", "center": [0, 0, 0], "halfSize": [1.7, 1.7, 1.7]}}}
        Implicit.setFieldGraph(feature, json.dumps(capped))
        check_mesh(feature, Implicit.tessellate(feature, 16), closed=True, smooth=False)
        Implicit.setFieldGraph(feature, json.dumps({"schema": 1, "root": {
            "type": "box", "center": [0, 0, 0], "halfSize": [1, 2, 3]}}))
        assert math.isclose(Implicit.evaluate(feature, 0, 0, 0), -1)
        assert math.isclose(Implicit.evaluate(feature, 2, 3, 4), math.sqrt(3))
        assert Implicit.gradient(feature, 2, 0, 0) == (1, 0, 0)
        feature.FieldGraph = ""

        for invalid in (0, -1, 1, 65, 2 ** 80, 2.5, True, "24"):
            try:
                Implicit.tessellate(feature, invalid)
            except (ValueError, TypeError, OverflowError):
                pass
            else:
                raise AssertionError("accepted invalid resolution: {!r}".format(invalid))
        try:
            Implicit.tessellateAdaptive(feature, 24)
        except RuntimeError:
            pass
        else:
            raise AssertionError("accepted non-power-of-two adaptive resolution")

        feature.DomainMax = feature.DomainMin
        try:
            Implicit.tessellate(feature, 12)
        except RuntimeError as error:
            assert "domain" in str(error)
        else:
            raise AssertionError("accepted an invalid domain")
    finally:
        FreeCAD.closeDocument(document.Name)
    print("native implicit mesh smoke test passed")


try:
    main()
except BaseException:
    traceback.print_exc()
    raise
