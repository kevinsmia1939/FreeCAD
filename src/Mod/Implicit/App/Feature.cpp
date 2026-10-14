// SPDX-License-Identifier: LGPL-2.1-or-later

#include "Feature.h"

#include "FieldGraph.h"

#include <memory>
#include <stdexcept>
#include <string>

#include <App/DocumentObject.h>

using namespace Implicit;

PROPERTY_SOURCE(Implicit::Feature, App::GeoFeature)

const char* Feature::FunctionEnums[] = {"Gyroid", "Sphere", nullptr};

Feature::Feature()
{
    ADD_PROPERTY_TYPE(Function, (0L), "Field", App::Prop_None, "Implicit field primitive");
    Function.setEnums(FunctionEnums);
    ADD_PROPERTY_TYPE(Center, (Base::Vector3d()), "Field", App::Prop_None, "Sphere center");
    ADD_PROPERTY_TYPE(Radius, (10.0), "Field", App::Prop_None, "Sphere radius");
    ADD_PROPERTY_TYPE(Period, (10.0), "Field", App::Prop_None, "Gyroid period");
    ADD_PROPERTY_TYPE(IsoValue, (0.0), "Field", App::Prop_None, "Field isovalue");
    ADD_PROPERTY_TYPE(
        DomainMin,
        (Base::Vector3d(-10.0, -10.0, -10.0)),
        "Domain",
        App::Prop_None,
        "Finite evaluation domain minimum"
    );
    ADD_PROPERTY_TYPE(
        DomainMax,
        (Base::Vector3d(10.0, 10.0, 10.0)),
        "Domain",
        App::Prop_None,
        "Finite evaluation domain maximum"
    );
    ADD_PROPERTY_TYPE(Tolerance, (1.0e-9), "Domain", App::Prop_None, "Classification tolerance");
    ADD_PROPERTY_TYPE(
        InsideNegative,
        (true),
        "Domain",
        App::Prop_None,
        "Treat negative field values as inside"
    );
    ADD_PROPERTY_TYPE(
        FieldGraph,
        (""),
        "Field",
        App::Prop_None,
        "Versioned JSON field graph; empty uses the primitive properties"
    );
    ADD_PROPERTY_TYPE(
        SchemaVersion,
        (2),
        "Persistence",
        App::Prop_ReadOnly,
        "Serialized implicit feature schema"
    );
}

short Feature::mustExecute() const
{
    return Function.isTouched() || Center.isTouched() || Radius.isTouched() || Period.isTouched()
            || IsoValue.isTouched() || DomainMin.isTouched() || DomainMax.isTouched()
            || Tolerance.isTouched() || InsideNegative.isTouched() || FieldGraph.isTouched()
        ? 1
        : App::GeoFeature::mustExecute();
}

App::DocumentObjectExecReturn* Feature::execute()
{
    try {
        (void)makeShape();
    }
    catch (const std::exception& error) {
        return new App::DocumentObjectExecReturn(error.what());
    }
    return App::DocumentObject::StdReturn;
}

Shape Feature::makeShape() const
{
    FieldPtr field;
    const std::string serializedGraph = FieldGraph.getValue();
    if (!serializedGraph.empty()) {
        field = Implicit::FieldGraph::parse(serializedGraph);
    }
    else if (Function.getValue() == 0) {
        field = std::make_shared<GyroidField>(Period.getValue(), IsoValue.getValue());
    }
    else {
        field = std::make_shared<SphereField>(Center.getValue(), Radius.getValue());
    }
    return {
        std::move(field),
        {DomainMin.getValue(), DomainMax.getValue()},
        Tolerance.getValue(),
        InsideNegative.getValue()
    };
}
