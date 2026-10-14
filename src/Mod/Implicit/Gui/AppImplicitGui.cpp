// SPDX-License-Identifier: LGPL-2.1-or-later
#include <Base/Interpreter.h>
#include <Base/PyObjectBase.h>
#include <Gui/Application.h>
#include "ViewProviderShape.h"

namespace ImplicitGui
{
class Module: public Py::ExtensionModule<Module>
{
public:
    Module()
        : Py::ExtensionModule<Module>("ImplicitGui")
    {
        initialize("Native implicit feature visualization.");
    }
};
}  // namespace ImplicitGui

PyMOD_INIT_FUNC(ImplicitGui)
{
    if (!Gui::Application::Instance) {
        PyErr_SetString(PyExc_ImportError, "ImplicitGui requires the FreeCAD GUI");
        PyMOD_Return(nullptr);
    }
    try {
        Base::Interpreter().loadModule("Implicit");
    }
    catch (const Base::Exception& error) {
        PyErr_SetString(PyExc_ImportError, error.what());
        PyMOD_Return(nullptr);
    }
    ImplicitGui::ViewProviderShape::init();
    PyMOD_Return(Base::Interpreter().addModule(new ImplicitGui::Module));
}
