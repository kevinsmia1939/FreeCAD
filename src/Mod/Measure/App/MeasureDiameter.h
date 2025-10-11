/***************************************************************************
 *   Copyright (c) 2024 FreeCAD contributors                               *
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


#ifndef MEASURE_MEASUREDIAMETER_H
#define MEASURE_MEASUREDIAMETER_H

#include "MeasureRadius.h"

namespace Measure
{

class MeasureExport MeasureDiameter: public Measure::MeasureRadius
{
    PROPERTY_HEADER_WITH_OVERRIDE(Measure::MeasureDiameter);

public:
    MeasureDiameter();
    ~MeasureDiameter() override;

    App::PropertyDistance Diameter;

    App::DocumentObjectExecReturn* execute() override;
    const char* getViewProviderName() const override
    {
        return "MeasureGui::ViewProviderMeasureDiameter";
    }

    App::Property* getResultProp() override
    {
        return &this->Diameter;
    }
};

}  // namespace Measure


#endif  // MEASURE_MEASUREDIAMETER_H

