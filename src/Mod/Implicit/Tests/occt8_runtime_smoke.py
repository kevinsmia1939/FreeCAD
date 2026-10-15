# SPDX-License-Identifier: LGPL-2.1-or-later
"""Linux migration gate: actual Part/Implicit imports and loaded OCCT library paths."""
import math
import os
from pathlib import Path
import traceback

import FreeCAD as App
import Part
import Implicit


def main():
    kernel_root = Path(os.environ["IMPLICIT_EXPECTED_OCCT_LIBRARY_DIR"]).resolve(strict=True)
    build_root = Path(os.environ["IMPLICIT_EXPECTED_FREECAD_BUILD"]).resolve(strict=True)
    assert Part.OCC_VERSION.startswith("8."), Part.OCC_VERSION
    for module in (Part, Implicit):
        assert Path(module.__file__).resolve().is_relative_to(build_root), module.__file__

    doc = App.newDocument("OCCT8RuntimeAudit")
    try:
        source = doc.addObject("Part::Feature", "Box")
        source.Shape = Part.makeBox(4, 6, 8)
        clipped = source.Shape.common(Part.makeBox(4, 6, 8, App.Vector(2, 0, 0)))
        assert clipped.isValid() and math.isclose(clipped.Volume, 96, abs_tol=1e-7)
        field = doc.addObject("Implicit::Feature", "Distance")
        field.Operation = "BRep"
        field.Left = source
        doc.recompute()
        assert field.isValid(), field.State
        # Exercises the signed-distance implementation exported by TKTopAlgo.
        assert math.isclose(Implicit.evaluate(field, 2, 3, 4), -2, abs_tol=1e-6)

        loaded = set()
        for line in Path("/proc/self/maps").read_text().splitlines():
            columns = line.split(maxsplit=5)
            if len(columns) == 6:
                path = Path(columns[5])
                if path.name.startswith("libTK") and ".so" in path.name:
                    loaded.add(path.resolve(strict=True))
        assert loaded, "No OCCT libraries found in process maps"
        assert all(path.parent == kernel_root for path in loaded), sorted(map(str, loaded))
        for toolkit in ("TKernel", "TKBRep", "TKTopAlgo"):
            assert any(path.name.startswith("lib" + toolkit + ".so.8.") for path in loaded), toolkit
        print("OCCT runtime:", Part.OCC_VERSION, "libraries:", len(loaded), "root:", kernel_root)
    finally:
        App.closeDocument(doc.Name)
    print("native implicit OCCT8 runtime smoke test passed")


try:
    main()
except BaseException:
    traceback.print_exc()
    raise
