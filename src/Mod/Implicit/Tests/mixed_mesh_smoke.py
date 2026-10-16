# SPDX-License-Identifier: LGPL-2.1-or-later
"""Native constraints and trim-conforming candidate, NOT a validated solid."""
from collections import defaultdict
import math
import traceback
import FreeCAD as App
import ImplicitMixed
import ImplicitOCCT as native


def check(data, mesh, surface=False):
    vertices, triangles = mesh["vertices"], mesh["cap_triangles"]
    assert vertices and triangles and mesh["seams"] and mesh["wires"]
    assert mesh["native_surface_meshed"] is surface
    assert mesh["solid_validated"] is False
    assert mesh["surface_coverage_verified"] is False
    assert mesh["seam_geometric_bound"] == data["seam_geometric_bound"]
    assert mesh["seam_bound_verified"] == data["seam_bound_verified"]
    assert all(len(p) == 3 and all(math.isfinite(x) for x in p) for p in vertices)
    cap_uses, wire_uses = defaultdict(list), defaultdict(list)

    def use(table, a, b):
        assert 0 <= a < len(vertices) and 0 <= b < len(vertices) and a != b
        table[tuple(sorted((a, b)))].append(1 if a < b else -1)

    for a, b, c, cap in triangles:
        assert len({a, b, c}) == 3 and 0 <= cap < len(data["planar_caps"])
        p, q, r = (App.Vector(*vertices[i]) for i in (a, b, c))
        n = (q - p).cross(r - p)
        assert n.Length > 0
        assert n.dot(data["planar_caps"][cap].normalAt(0, 0)) > 0
        for i, j in ((a, b), (b, c), (c, a)):
            use(cap_uses, i, j)
    for wire in mesh["wires"]:
        assert len(wire) >= 4 and wire[0] == wire[-1]
        for a, b in zip(wire, wire[1:]):
            use(wire_uses, a, b)
    assert len(mesh["seams"]) == len(data["seams"])
    seam_segments = set()
    for indices, poles in zip(mesh["seams"], data["seams"]):
        assert len(indices) >= len(poles)
        samples = [vertices[i] for i in indices]
        for pole in poles:
            assert any(math.dist(pole, p) < 1.e-9 for p in samples)
        for a, b in zip(indices, indices[1:]):
            edge = tuple(sorted((a, b)))
            assert edge not in seam_segments
            seam_segments.add(edge)
    assert seam_segments == set(wire_uses)
    for edge, signs in cap_uses.items():
        if edge in wire_uses:
            assert len(signs) == len(wire_uses[edge]) == 1
            assert signs[0] == -wire_uses[edge][0]
        else:
            assert len(signs) == 2 and sum(signs) == 0
    assert set(wire_uses) <= set(cap_uses)
    if surface:
        assert mesh["mesh_closed"] and mesh["implicit_triangles"]
        assert 0 < mesh["field_distance_bound"] <= .1 and 8 <= mesh["cells"] <= 256
        combined = defaultdict(list, {edge: list(signs) for edge, signs in cap_uses.items()})
        for triangle in mesh["implicit_triangles"]:
            assert len(set(triangle)) == 3
            p, q, r = (App.Vector(*vertices[i]) for i in triangle)
            center = (p + q + r) / 3
            gradient = App.Vector(*native.gradient(data["implicit_face"], tuple(center)))
            direction = 1 if data["operation"] == "common" else -1
            assert direction * (q - p).cross(r - p).dot(gradient) > 0
            for a, b in zip(triangle, (*triangle[1:], triangle[0])):
                use(combined, a, b)
        assert all(len(signs) == 2 and sum(signs) == 0 for signs in combined.values())


def main():
    retained = []
    for open_contours in (False, True):
        obj = ImplicitMixed.demo(open_contours=open_contours)
        doc = obj.Document
        for operation in ("Common", "BoxMinusField"):
            obj.Operation = operation
            doc.recompute()
            assert obj.isValid(), obj.BackendStatus
            data = obj.Proxy.native_boundary()
            handle = data["boundary_handle"]
            record = native.dumps_mixed(handle)
            geometry = obj.Geometry
            mesh = native.prepare_mixed_mesh(handle)
            check(data, mesh)
            surface = native.tessellate_mixed(handle)
            print("native mesh candidate", open_contours, operation, surface["cells"],
                  len(surface["vertices"]), len(surface["implicit_triangles"]),
                  surface["field_distance_bound"])
            check(data, surface, surface=True)
            assert surface == native.tessellate_mixed(obj.Geometry)
            assert surface["vertices"][:len(mesh["vertices"])] == mesh["vertices"]
            assert surface["seams"] == mesh["seams"] and surface["wires"] == mesh["wires"]
            assert mesh == native.prepare_mixed_mesh(handle)
            assert native.dumps_mixed(handle) == record
            # Independent Part copies and native property remain untouched.
            cap_records = [c.exportBrepToString() for c in data["planar_caps"]]
            for cap in data["planar_caps"]:
                cap.tessellate(.05)
            assert mesh == native.prepare_mixed_mesh(handle)
            assert [c.exportBrepToString() for c in data["planar_caps"]] == cap_records
            assert native.dumps_mixed(geometry) == native.dumps_mixed(obj.Geometry)
            assert mesh == native.prepare_mixed_mesh(obj.Geometry)
            loaded = native.loads_mixed(record)
            prepared = native.prepare_mixed_mesh(loaded["boundary_handle"])
            check(loaded, prepared)
            assert prepared["seam_bound_verified"] is False
            restored_surface = native.tessellate_mixed(loaded["boundary_handle"])
            check(loaded, restored_surface, surface=True)
            assert restored_surface["implicit_triangles"] == surface["implicit_triangles"]
            for args, error in (
                    ((None,), TypeError),
                    ((handle, .1, 257), ValueError),
                    ((handle, 1.e-6, 8), NotImplementedError),
                    ((handle, .1, 128, 3), NotImplementedError)):
                try:
                    native.tessellate_mixed(*args)
                except error:
                    pass
                else:
                    raise AssertionError("invalid surface meshing accepted")
            for args, error in (
                    ((data["implicit_face"],), TypeError),
                    ((None,), TypeError),
                    ((handle, float("nan")), ValueError),
                    ((handle, 0), ValueError),
                    ((handle, .1, 1000001), ValueError),
                    ((handle, .1, 3), NotImplementedError),
                    ((handle, .1, 200000, 1), NotImplementedError)):
                try:
                    native.prepare_mixed_mesh(*args)
                except error:
                    pass
                else:
                    raise AssertionError("invalid mesh preparation accepted")
            assert native.dumps_mixed(handle) == record
            retained.append((data, mesh, surface, record))
        App.closeDocument(doc.Name)
    for data, mesh, surface, record in retained:
        assert native.prepare_mixed_mesh(data["boundary_handle"]) == mesh
        assert native.dumps_mixed(data["boundary_handle"]) == record
        assert native.tessellate_mixed(data["boundary_handle"]) == surface
    print("native implicit mixed mesh preparation smoke test passed")


try:
    main()
except Exception:
    traceback.print_exc()
    raise
