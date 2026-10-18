# SPDX-License-Identifier: LGPL-2.1-or-later
"""Focused modelling workbench, backed by the compiled Implicit module."""
import FreeCADGui as Gui
from ImplicitCommands import GYROID_ICON


class ImplicitModelingWorkbench(Gui.Workbench):
    MenuText = "Implicit Modelling"
    ToolTip = "Editable implicit geometry using the native field core"
    Icon = GYROID_ICON

    def Initialize(self):
        import ImplicitCommands
        ImplicitCommands.register()
        self.appendToolbar("Implicit Modelling", ["Implicit_Gyroid"])
        self.appendMenu("Implicit Modelling", ["Implicit_Gyroid"])

    def GetClassName(self):
        return "Gui::PythonWorkbench"


def register():
    if "ImplicitModelingWorkbench" not in Gui.listWorkbenches():
        Gui.addWorkbench(ImplicitModelingWorkbench())
