# SPDX-License-Identifier: LGPL-2.1-or-later
"""Reject the public native-face API before loading any OCCT 8 library in OCCT 7."""
import sys
from pathlib import Path
import Part

if not Part.OCC_VERSION.startswith("7."):
    print("native-face legacy guard applies only to OCCT 7")
else:
    try:
        import ImplicitOCCT
    except ImportError as error:
        assert "wholly OCCT-8-linked" in str(error), str(error)
    else:
        raise AssertionError("OCCT 7 process imported the native OCCT 8 API")
    assert "_ImplicitOCCT" not in sys.modules
    assert not any("libTK" in line and ".so.8." in line
                   for line in Path("/proc/self/maps").read_text().splitlines())
    print("native implicit OCCT7 face ABI guard passed")
