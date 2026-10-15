# SPDX-License-Identifier: LGPL-2.1-or-later
"""Immutable native OCCT faces owned inside FreeCAD, never Part shapes."""
import gc
import math
import pickle
from pathlib import Path
import traceback
import FreeCAD as App
import Part
import ImplicitOCCT as native


def rejects(action, errors=(ValueError, RuntimeError, TypeError, NotImplementedError)):
    try:
        action()
    except errors:
        return
    raise AssertionError("unsupported native operation succeeded")


def main():
    assert native.kernel_version.startswith("8.") and Part.OCC_VERSION.startswith("8.")
    a = native.sphere((0, 0, 0), 2)
    metadata = native.info(a)
    assert metadata["is_implicit"] and not metadata["has_parametric_surface"]
    assert not metadata["solid_validated"] and metadata["tolerance"] == .1
    assert native.value(a, (0, 0, 0)) == -2
    assert native.gradient(a, (2, 0, 0)) == (1, 0, 0)
    assert native.normal(a, (2, 0, 0)) == (1, 0, 0)
    assert native.in_domain(a, (2, 0, 0))
    assert not native.in_domain(a, (5, 0, 0))
    rejects(lambda: native.normal(a, (0, 0, 0)))
    hits = native.intersect_ray(a, (-3, 0, 0), (1, 0, 0), 0, 6, 101, .01)
    assert len(hits) == 2 and all(h["bracket_width"] <= .01 for h in hits), hits
    assert all(abs(h["distance"] - expected) <= .01 for h, expected in zip(hits, (1, 5)))
    moved = native.translated(a, (10, 3, -1))
    assert native.value(moved, (12, 3, -1)) == 0 and native.value(a, (2, 0, 0)) == 0
    record = native.dumps(moved)
    restored = native.loads(record)
    assert native.dumps(restored) == record
    assert native.value(restored, (12, 3, -1)) == 0
    del moved
    gc.collect()
    assert native.value(restored, (10, 3, -1)) == -2

    mesh = native.tessellate(restored, .1)
    assert mesh["triangles"] and 0 < mesh["geometric_bound"] <= .1
    assert len(mesh["vertices"]) == len(mesh["normals"])
    assert all(abs(math.dist(p, (10, 3, -1)) - 2) < 1e-10 for p in mesh["vertices"])
    for triangle in mesh["triangles"]:
        x, y, z = (App.Vector(*mesh["vertices"][i]) for i in triangle)
        normal = App.Vector(*mesh["normals"][triangle[0]])
        assert (y-x).cross(z-x).dot(normal) > 0

    # Explicit schema-1 interchange can carry reflections, even though this
    # first Python API deliberately exposes only translation as a placement edit.
    lines = native.dumps(a).splitlines()
    row = lines.index("INSTANCE_LOCATION") + 1
    lines[row:row+3] = ["-1 0 0 0", "0 1 0 0", "0 0 1 0"]
    reflected = native.loads("\n".join(lines) + "\n")
    reflected_mesh = native.tessellate(reflected)
    for triangle in reflected_mesh["triangles"]:
        x, y, z = (App.Vector(*reflected_mesh["vertices"][i]) for i in triangle)
        normal = App.Vector(*reflected_mesh["normals"][triangle[0]])
        assert (y-x).cross(z-x).dot(normal) > 0

    trimmed = native.trim(a, (0, 0, 1), .5)
    assert native.in_domain(trimmed, (0, 0, -2))
    assert not native.in_domain(trimmed, (0, 0, 2))
    rejects(lambda: native.dumps(trimmed), (NotImplementedError,))
    assert native.tessellate(trimmed, .1)["geometric_bound"] <= .1
    placed_patch = native.translated(trimmed, (10, 0, 0))
    assert native.in_domain(placed_patch, (10, 0, -2))
    assert all(p[2] <= .5 + 1e-10 for p in native.tessellate(placed_patch)["vertices"])
    for op in ("common", "fuse", "cut"):
        pairs = native.boolean_faces(a, native.sphere((2, 0, 0), 2), op)
        assert len(pairs) == 2 and [source for _, source in pairs] == [0, 1]
        for face, _ in pairs:
            assert not native.info(face)["solid_validated"]
            rejects(lambda: native.dumps(face), (NotImplementedError,))
    rejects(lambda: native.boolean_faces(a, native.sphere((4, 0, 0), 2), "common"))
    gyro = native.gyroid(10, .21, (-5, -5, -5), (5, 5, 5))
    assert math.isclose(native.value(gyro, (0, 0, 0)), -.21)
    assert native.dumps(native.loads(native.dumps(gyro))) == native.dumps(gyro)
    rejects(lambda: native.tessellate(gyro), (ValueError, RuntimeError))
    rejects(lambda: native.trim(gyro, (0, 0, 1), 0))
    for invalid in (None, object(), Part.makeBox(1, 1, 1), "native face"):
        rejects(lambda: native.value(invalid, (0, 0, 0)), (TypeError,))
    for bad in ((math.nan, 0, 0), (1, 2), "bad"):
        rejects(lambda: native.value(a, bad))
    for radius in (0, -1, math.inf, math.nan):
        rejects(lambda: native.sphere((0, 0, 0), radius))
    for tolerance in (0, -1, math.inf, math.nan):
        rejects(lambda: native.sphere((0, 0, 0), 2, tolerance))
    for bad in ("", record + "junk", "x" * 65537, record + "\0", record.replace("OCCT_IMPLICIT_FACE 1", "OCCT_IMPLICIT_FACE 99")):
        rejects(lambda: native.loads(bad))
    rejects(lambda: pickle.dumps(a), (TypeError,))
    doc = App.newDocument("NativeFacePartGuard")
    try:
        obj = doc.addObject("Part::Feature", "ConventionalOnly")
        rejects(lambda: setattr(obj, "Shape", a))
        assert obj.Shape.isNull()
    finally:
        App.closeDocument(doc.Name)
    # Inputs survive every unsupported operation; no returned topology can mutate them.
    assert native.value(a, (0, 0, 0)) == -2
    assert not any("libTK" in line and ".so.7." in line
                   for line in Path("/proc/self/maps").read_text().splitlines())
    print("native implicit OCCT face smoke test passed", flush=True)


try:
    main()
except BaseException:
    traceback.print_exc()
    raise
