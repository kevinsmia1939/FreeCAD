// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
 *   Copyright (c) 2025 Kavin Teenakul <andythe_great@protonmail.com>      *
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
 **************************************************************************/

#ifndef MEASURE_MEASUREVOLUME_H
#define MEASURE_MEASUREVOLUME_H

#include <Mod/Measure/MeasureGlobal.h>

#include <vector>

#include <App/GeoFeature.h>
#include <App/PropertyLinks.h>
#include <App/PropertyUnits.h>

#include <Mod/Part/App/MeasureInfo.h>

#include "MeasureBase.h"


namespace Measure
{


class MeasureExport MeasureVolume: public Measure::MeasureBaseExtendable<Part::MeasureVolumeInfo>
{
    PROPERTY_HEADER_WITH_OVERRIDE(Measure::MeasureVolume);

public:
    MeasureVolume();
    ~MeasureVolume() override;

    App::PropertyLinkSubList Elements;
    App::PropertyVolume Volume;

    App::DocumentObjectExecReturn* execute() override;

    const char* getViewProviderName() const override
    {
        return "MeasureGui::ViewProviderMeasureVolume";
    }

    static bool isValidSelection(const App::MeasureSelection& selection);
    void parseSelection(const App::MeasureSelection& selection) override;

    std::vector<std::string> getInputProps() override
    {
        return {"Elements"};
    }
    App::Property* getResultProp() override
    {
        return &this->Volume;
    }

    Base::Placement getPlacement() override;

    std::vector<App::DocumentObject*> getSubject() const override;

private:
    void onChanged(const App::Property* prop) override;
};

Part::MeasureInfoPtr makeVolumeInfo(const App::SubObjectT& subject);

}  // namespace Measure


#endif  // MEASURE_MEASUREVOLUME_H
