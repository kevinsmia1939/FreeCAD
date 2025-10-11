/***************************************************************************
 *   Copyright (c) 2025 FreeCAD contributors                               *
 *                                                                         *
 *   This file is part of FreeCAD.                                         *
 *                                                                         *
 *   FreeCAD is free software: you can redistribute it and/or modify it    *
 *   under the terms of the GNU Lesser General Public License as           *
 *   published by the Free Software Foundation, either version 2.1 of the  *
 *   License, or (at your option) any later version.                       *
 *                                                                         *
 *   FreeCAD is distributed in the hope that it will be useful, but        *
 *   WITHOUT ANY WARRANTY; without even the implied warranty of            *
 *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU      *
 *   Lesser General Public License for more details.                       *
 *                                                                         *
 *   You should have received a copy of the GNU Lesser General Public      *
 *   License along with FreeCAD. If not, see                               *
 *   <https://www.gnu.org/licenses/>.                                      *
 *                                                                         *
 ***************************************************************************/


#include "PreCompiled.h"

#include "MeasureDiameter.h"


using namespace Measure;

PROPERTY_SOURCE(Measure::MeasureDiameter, Measure::MeasureRadius)

MeasureDiameter::MeasureDiameter()
{
    ADD_PROPERTY_TYPE(Diameter,
                      (0.0),
                      "Measurement",
                      App::PropertyType(App::Prop_ReadOnly | App::Prop_Output),
                      "Diameter of selection");

    Radius.setStatus(App::Property::Hidden, true);
}

MeasureDiameter::~MeasureDiameter() = default;

App::DocumentObjectExecReturn* MeasureDiameter::execute()
{
    auto* result = MeasureRadius::execute();
    if (result == DocumentObject::StdReturn) {
        Diameter.setValue(Radius.getValue() * 2.0);
    }
    else {
        Diameter.setValue(0.0);
    }

    return result;
}

