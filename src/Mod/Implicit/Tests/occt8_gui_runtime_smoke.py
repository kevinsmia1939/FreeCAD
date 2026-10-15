# SPDX-License-Identifier: LGPL-2.1-or-later
"""Audit the actual GUI process, including PartGui, ImplicitGui and bundled Coin/Pivy."""
import os
from pathlib import Path
import runpy
import traceback

import FreeCADGui as Gui
import PartGui
import ImplicitGui
import pivy
import pivy._coin as coin_extension


def main():
    build_root = Path(os.environ["IMPLICIT_EXPECTED_FREECAD_BUILD"]).resolve(strict=True)
    for module in (PartGui, ImplicitGui, pivy, coin_extension):
        assert Path(module.__file__).resolve().is_relative_to(build_root), module.__file__
    Gui.activateWorkbench("NativeImplicitWorkbench")
    # Reuse the command-line audit after loading the GUI-specific consumers.
    # This also creates/recomputes a conventional Part shape and a live field.
    runpy.run_path(str(Path(__file__).with_name("occt8_runtime_smoke.py")))
    coins = set()
    for line in Path("/proc/self/maps").read_text().splitlines():
        columns = line.split(maxsplit=5)
        if len(columns) == 6 and Path(columns[5]).name.startswith("libCoin.so"):
            coins.add(Path(columns[5]).resolve(strict=True))
    assert coins and all(path.parent == build_root / "lib" for path in coins), coins
    print("native implicit OCCT8 GUI runtime smoke test passed", flush=True)
    Gui.getMainWindow().close()


try:
    main()
except BaseException:
    traceback.print_exc()
    os._exit(1)
