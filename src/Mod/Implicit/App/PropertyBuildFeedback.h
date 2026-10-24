// SPDX-License-Identifier: LGPL-2.1-or-later
#pragma once

#include <App/PropertyPythonObject.h>

namespace Implicit
{
// A live Python value with a normal property-editor row. Unlike a stored status
// string, repainting this value does not write to the document's undo journal.
class PropertyBuildFeedback: public App::PropertyPythonObject
{
    TYPESYSTEM_HEADER_WITH_OVERRIDE();
public:
    const char* getEditorName() const override
    {
        return "Gui::PropertyEditor::PropertyItem";
    }
    App::Property* Copy() const override;
};
}
