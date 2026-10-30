# SPDX-License-Identifier: LGPL-2.1-or-later
"""Transient surface preview, native viewport picks and property lifecycle."""
import os
from pathlib import Path
import runpy
import traceback
import FreeCADGui as Gui

try:
    runpy.run_path(str(Path(__file__).with_name("cylinder_property_smoke.py")))
    print("native implicit cylinder property GUI smoke test passed", flush=True)
    Gui.getMainWindow().close()
except BaseException:
    traceback.print_exc()
    os._exit(1)
