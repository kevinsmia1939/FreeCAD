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
        commands = ImplicitCommands.register()
        self.appendToolbar("Implicit Modelling", ["Implicit_NativeGyroid"])
        self.appendMenu("Implicit Modelling", ["Implicit_NativeGyroid", "Implicit_Gyroid"])
        native = [name for name in ("Implicit_NativeTopologyDemo", "Implicit_OCCTMixedCommon",
                                   "Implicit_OCCTMixedBoxMinusField") if name in commands]
        if native:
            self.appendMenu(["Implicit Modelling", "Native boundaries (experimental)"], native)
        solids = [name for name in ("Implicit_NativeSolid", "Implicit_NativeSolidDemo") if name in commands]
        if solids:
            self.appendMenu(["Implicit Modelling", "Native solids (experimental)"], solids)

    def GetClassName(self):
        return "Gui::PythonWorkbench"


def register():
    if "ImplicitModelingWorkbench" not in Gui.listWorkbenches():
        Gui.addWorkbench(ImplicitModelingWorkbench())
