// SPDX-License-Identifier: LGPL-2.1-or-later

#pragma once

#include <App/GeoFeature.h>
#include <App/PropertyGeo.h>
#include <App/PropertyLinks.h>
#include <App/PropertyStandard.h>
#include <App/PropertyUnits.h>
#include <Mod/Implicit/ImplicitGlobal.h>

#include "Shape.h"
#include "SurfaceMesh.h"
#include <optional>

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
    App::PropertyInteger CacheRevision;
    App::PropertyEnumeration Operation;
    App::PropertyLink Left;
    App::PropertyLink Right;
    App::PropertyFloat Amount;
    App::PropertyBool AutoDomain;
    App::PropertyString StatusMessage;

    short mustExecute() const override;
    App::DocumentObjectExecReturn* execute() override;

    Shape makeShape() const;
    std::shared_ptr<const SurfaceMesh> getDisplayMesh(
        unsigned int resolution,
        bool adaptive = false
    ) const;
    const char* getViewProviderName() const override
    {
        return "ImplicitGui::ViewProviderShape";
    }

protected:
    void onChanged(const App::Property* property) override;
    void onSettingDocument() override;

private:
    static const char* FunctionEnums[];
    static const char* OperationEnums[];
    mutable std::shared_ptr<const SurfaceMesh> displayMesh;
    mutable unsigned int displayResolution = 0;
    mutable bool displayAdaptive = false;
    mutable std::optional<Shape> compiledShape;
    fastsignals::scoped_connection recomputedConnection;
    void validateDependencies() const;
};

}  // namespace Implicit
