# SPDX-License-Identifier: LGPL-2.1-or-later
"""Register native implicit view providers before documents are restored."""
import ImplicitGui  # noqa: F401
import FreeCADGui as Gui


class NativeImplicitWorkbench(Gui.Workbench):
    MenuText = "Native Implicit"
    ToolTip = "Native implicit fields, linked operations and live B-Rep inputs"

    def Initialize(self):
        import ImplicitCommands
        names = ImplicitCommands.register()
        self.appendToolbar("Native Implicit", names)
        self.appendMenu("Native Implicit", names)

    def GetClassName(self):
        return "Gui::PythonWorkbench"


Gui.addWorkbench(NativeImplicitWorkbench())

import ImplicitWorkbench
ImplicitWorkbench.register()
