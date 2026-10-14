// SPDX-License-Identifier: LGPL-2.1-or-later

#pragma once

#include <App/GeoFeature.h>
#include <App/PropertyGeo.h>
#include <App/PropertyStandard.h>
#include <App/PropertyUnits.h>
#include <Mod/Implicit/ImplicitGlobal.h>

#include "Shape.h"

namespace Implicit
{

class ImplicitExport Feature: public App::GeoFeature
{
    PROPERTY_HEADER_WITH_OVERRIDE(Implicit::Feature);

public:
    Feature();

    App::PropertyEnumeration Function;
    App::PropertyVector Center;
    App::PropertyLength Radius;
    App::PropertyLength Period;
    App::PropertyFloat IsoValue;
    App::PropertyVector DomainMin;
    App::PropertyVector DomainMax;
    App::PropertyFloat Tolerance;
    App::PropertyBool InsideNegative;
    App::PropertyString FieldGraph;
    App::PropertyInteger SchemaVersion;

    short mustExecute() const override;
    App::DocumentObjectExecReturn* execute() override;

    Shape makeShape() const;

private:
    static const char* FunctionEnums[];
};

}  // namespace Implicit
