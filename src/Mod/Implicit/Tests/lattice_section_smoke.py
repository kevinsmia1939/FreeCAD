# SPDX-License-Identifier: LGPL-2.1-or-later
"""Exact-node sections retain curves AND isolated contacts, not native trim B-Reps."""
from collections import Counter
import math
import os
import traceback
import FreeCAD as App
import Implicit
import ImplicitOCCT as native


def main():
    doc = App.newDocument("DefaultGyroidSections")
    obj = doc.addObject("Implicit::Feature", "Gyroid")
    obj.Function, obj.Period, obj.IsoValue = "Gyroid", 10, 0
    obj.DomainMin, obj.DomainMax = (0, 0, 0), (10, 10, 10)
    doc.recompute()
    face = native.gyroid(obj.Period, obj.IsoValue, tuple(obj.DomainMin), tuple(obj.DomainMax))
    saved = native.dumps(face)
    corners = native.check_box_corners(face)["corners"]
    corner_points = {tuple(c["anchor"]): c["index"] for c in corners}
    curve_ends, contacts = Counter(), Counter()
    for axis in range(3):
        for high in (False, True):
            origin, normal, direction = [0., 0., 0.], [0., 0., 0.], [0., 0., 0.]
            origin[axis], normal[axis], direction[(axis + 1) % 3] = 10. if high else 0., 1., 1.
            report = native.trace_gyroid_plane(face, origin, normal, direction, (0, 10), (0, 10),
                                               allow_exact_lattice_nodes=True)
            assert report["resolved"], report
            assert len(report["curves"]) == 3 and len(report["point_contacts"]) == 2
            assert report["allow_exact_lattice_nodes"] and report["exact_lattice_node_count"] >= 4
            assert 0 < report["geometric_bound"] <= .1
            assert report["maximum_root_bracket"] <= .1 / 16
            assert not report["topology_validated"] and not report["solid_validated"]
            for p in report["point_contacts"]:
                assert tuple(p) in corner_points
                contacts[corner_points[tuple(p)]] += 1
            for curve in report["curves"]:
                assert not curve["closed"] and len(curve["points"]) >= 2
                for p in (curve["points"][0], curve["points"][-1]):
                    if tuple(p) in corner_points:
                        curve_ends[corner_points[tuple(p)]] += 1
                for p in curve["points"]:
                    assert p[axis] == origin[axis]
                    assert abs(native.value(face, p)) <= report["maximum_residual"] + 1e-13
    for corner in corners:
        index = corner["index"]
        assert curve_ends[index] == (0 if index in (0, 7) else 2)
        assert contacts[index] == (3 if index in (0, 7) else 1)
    base = (face, (0, 0, 0), (0, 0, 1), (1, 0, 0), (0, 10), (0, 10))
    legacy = native.trace_gyroid_plane(*base, maximum_cells=32)
    assert not legacy["resolved"] and not legacy["point_contacts"]
    assert legacy["exact_lattice_node_count"] == 0 and not legacy["allow_exact_lattice_nodes"]
    point_only = native.trace_gyroid_plane(*base[:4], (0, .25), (0, .25), allow_exact_lattice_nodes=True)
    assert point_only["resolved"] and not point_only["curves"]
    assert point_only["point_contacts"] == [(0., 0., 0.)]
    crossing = native.trace_gyroid_plane(face, (4.875, 4.875, 0), *base[2:4],
                                        (0, .25), (0, .25), allow_exact_lattice_nodes=True)
    assert crossing["resolved"] and len(crossing["curves"]) == 1 and not crossing["point_contacts"]
    assert crossing["curves"][0]["points"].count((5., 5., 0.)) == 1
    for keywords in ({"maximum_cells": 0}, {"distance_tolerance": math.nan},
                     {"allow_exact_lattice_nodes": "yes"}):
        try:
            native.trace_gyroid_plane(*base, **keywords)
        except (ValueError, TypeError):
            pass
        else:
            raise AssertionError("invalid section settings accepted")
    try:
        native.trace_gyroid_plane(face, (0, 0, 0), (0, 0, 0), (1, 0, 0), (0, 1), (0, 1))
    except ValueError:
        pass
    else:
        raise AssertionError("zero plane normal accepted")
    try:
        native.trace_gyroid_plane(native.translated(face, (1e-18, 0, 0)), *base[1:],
                                  allow_exact_lattice_nodes=True)
    except NotImplementedError:
        pass
    else:
        raise AssertionError("nonidentity exact-node placement accepted")
    assert native.dumps(face) == saved
    restored = native.loads(saved)
    assert native.trace_gyroid_plane(restored, *base[1:], allow_exact_lattice_nodes=True)["resolved"]
    App.closeDocument(doc.Name)
    assert native.trace_gyroid_plane(face, *base[1:], allow_exact_lattice_nodes=True)["resolved"]
    print("native implicit lattice section smoke test passed", flush=True)


try:
    main()
except BaseException:
    traceback.print_exc()
    os._exit(1)
