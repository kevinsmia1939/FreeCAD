// SPDX-License-Identifier: LGPL-2.1-or-later
#include "PropertyBuildFeedback.h"

using namespace Implicit;
TYPESYSTEM_SOURCE(Implicit::PropertyBuildFeedback, App::PropertyPythonObject)

App::Property* PropertyBuildFeedback::Copy() const
{
    auto* copy = new PropertyBuildFeedback();
    copy->Paste(*this);
    return copy;
}
