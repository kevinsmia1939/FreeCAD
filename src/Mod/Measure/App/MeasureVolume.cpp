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


#include <BRepCheck_Analyzer.hxx>
#include <BRepGProp.hxx>
#include <GProp_GProps.hxx>

#include <App/GeoFeature.h>
#include <App/MeasureManager.h>
#include <Base/Console.h>
#include <Base/Type.h>

#include <Mod/Mesh/App/MeshFeature.h>
#include <Mod/Part/App/PartFeature.h>

#include "MeasureVolume.h"


using namespace Measure;

PROPERTY_SOURCE(Measure::MeasureVolume, Measure::MeasureBase)

namespace
{

const char* errorInvalidModule = "No measure handler available for geometry of module: %s\n";

Part::MeasureInfoPtr buildVolumeInfoFromShape(const TopoDS_Shape& shape)
{
    if (shape.IsNull()) {
        return std::make_shared<Part::MeasureVolumeInfo>(
            false,
            0.0,
            Base::Placement(),
            "Cannot calculate volume"
        );
    }

    BRepCheck_Analyzer analyzer(shape, true);
    if (!analyzer.IsValid()) {
        return std::make_shared<Part::MeasureVolumeInfo>(
            false,
            0.0,
            Base::Placement(),
            "Selected object is not manifold"
        );
    }

    if (!shape.Closed()) {
        return std::make_shared<Part::MeasureVolumeInfo>(
            false,
            0.0,
            Base::Placement(),
            "Selected object is not closed"
        );
    }

    GProp_GProps gprops;
    BRepGProp::VolumeProperties(shape, gprops);

    auto origin = gprops.CentreOfMass();
    Base::Placement placement(Base::Vector3d(origin.X(), origin.Y(), origin.Z()), Base::Rotation());
    return std::make_shared<Part::MeasureVolumeInfo>(true, gprops.Mass(), placement, std::string());
}

Part::MeasureInfoPtr measureVolumeFromPart(const App::SubObjectT& subject)
{
    App::DocumentObject* obj = subject.getObject();
    if (!obj) {
        return std::make_shared<Part::MeasureVolumeInfo>(false, 0.0, Base::Placement(), "");
    }

    Base::Matrix4D mat;
    Part::TopoShape shape = Part::Feature::getTopoShape(
        obj,
        Part::ShapeOption::ResolveLink | Part::ShapeOption::Transform,
        nullptr,
        &mat
    );

    if (shape.isNull()) {
        Base::Console().message(
            "MeasureVolume: Did not retrieve shape for %s\n",
            obj->getNameInDocument()
        );
        return std::make_shared<Part::MeasureVolumeInfo>(false, 0.0, Base::Placement(), "");
    }

    auto placement = App::GeoFeature::getGlobalPlacement(obj, obj, nullptr);
    shape.setPlacement(placement);

    auto topoShape = shape.getShape();
    if (topoShape.ShapeType() != TopAbs_SOLID && topoShape.ShapeType() != TopAbs_COMPOUND
        && topoShape.ShapeType() != TopAbs_COMPSOLID) {
        return std::make_shared<Part::MeasureVolumeInfo>(
            false,
            0.0,
            Base::Placement(),
            "Selected object does not define a volume"
        );
    }

    return buildVolumeInfoFromShape(topoShape);
}

Part::MeasureInfoPtr measureVolumeFromMesh(const App::SubObjectT& subject)
{
    auto meshFeature = dynamic_cast<Mesh::Feature*>(subject.getObject());
    if (!meshFeature) {
        return std::make_shared<Part::MeasureVolumeInfo>(false, 0.0, Base::Placement(), "");
    }

    const auto& mesh = meshFeature->Mesh.getValue();
    if (!mesh.isSolid()) {
        return std::make_shared<Part::MeasureVolumeInfo>(
            false,
            0.0,
            Base::Placement(),
            "Selected mesh is not manifold"
        );
    }

    Base::Placement placement = App::GeoFeature::getGlobalPlacement(meshFeature, meshFeature, nullptr);
    Base::Vector3d origin = placement.getPosition();
    auto info = std::make_shared<Part::MeasureVolumeInfo>(true, mesh.getVolume(), placement, std::string());
    info->placement = Base::Placement(origin, Base::Rotation());
    return info;
}

}  // namespace


MeasureVolume::MeasureVolume()
{
    ADD_PROPERTY_TYPE(
        Elements,
        (nullptr),
        "Measurement",
        App::Prop_None,
        "Element to measure the volume from"
    );
    Elements.setScope(App::LinkScope::Global);
    Elements.setAllowExternal(true);

    ADD_PROPERTY_TYPE(
        Volume,
        (0.0),
        "Measurement",
        App::PropertyType(App::Prop_ReadOnly | App::Prop_Output),
        "Volume of element"
    );
}

MeasureVolume::~MeasureVolume() = default;

bool MeasureVolume::isValidSelection(const App::MeasureSelection& selection)
{
    if (selection.empty()) {
        return false;
    }

    for (const auto& element : selection) {
        auto type = App::MeasureManager::getMeasureElementType(element);
        if (type == App::MeasureElementType::INVALID) {
            auto handler = App::MeasureManager::getMeasureHandler(element);
            Base::Console().message(errorInvalidModule, handler.module.c_str());
            return false;
        }
    }

    return true;
}

void MeasureVolume::parseSelection(const App::MeasureSelection& selection)
{
    std::vector<App::DocumentObject*> objects;
    std::vector<std::string> subElements;

    for (auto element : selection) {
        auto objT = element.object;
        objects.push_back(objT.getObject());

        const char* subName = objT.getSubName();
        subElements.emplace_back(subName ? subName : "");
    }

    Elements.setValues(objects, subElements);
}

App::DocumentObjectExecReturn* MeasureVolume::execute()
{
    const std::vector<App::DocumentObject*>& objects = Elements.getValues();
    const std::vector<std::string>& subElements = Elements.getSubValues();

    double result(0.0);
    Base::Vector3d weightedCenter(0.0, 0.0, 0.0);

    for (std::vector<App::DocumentObject*>::size_type i = 0; i < objects.size(); i++) {
        App::SubObjectT subject {objects.at(i), subElements.at(i).c_str()};

        auto info = getMeasureInfo(subject);
        if (!info || !info->valid) {
            auto volInfo = std::dynamic_pointer_cast<Part::MeasureVolumeInfo>(info);
            const char* message = "Cannot calculate volume";
            if (volInfo && !volInfo->errorMessage.empty()) {
                message = volInfo->errorMessage.c_str();
            }
            return new App::DocumentObjectExecReturn(message);
        }

        auto volInfo = std::dynamic_pointer_cast<Part::MeasureVolumeInfo>(info);
        result += volInfo->volume;
        weightedCenter += volInfo->placement.getPosition() * volInfo->volume;
    }

    if (!objects.empty() && result > 0.0) {
        Base::Vector3d center = weightedCenter / result;
        Placement.setValue(Base::Placement(center, Base::Rotation()));
    }

    Volume.setValue(result);
    return DocumentObject::StdReturn;
}

Base::Placement MeasureVolume::getPlacement()
{
    const std::vector<App::DocumentObject*>& objects = Elements.getValues();
    const std::vector<std::string>& subElements = Elements.getSubValues();

    if (!objects.empty()) {
        App::SubObjectT subject {objects.front(), subElements.front().c_str()};
        auto info = getMeasureInfo(subject);
        if (info) {
            auto volInfo = std::dynamic_pointer_cast<Part::MeasureVolumeInfo>(info);
            return volInfo->placement;
        }
    }

    return Placement.getValue();
}

std::vector<App::DocumentObject*> MeasureVolume::getSubject() const
{
    std::vector<App::DocumentObject*> subjects;

    for (auto obj : Elements.getValues()) {
        if (auto geoObj = dynamic_cast<App::GeoFeature*>(obj)) {
            subjects.push_back(geoObj);
        }
    }

    return subjects;
}

void MeasureVolume::onChanged(const App::Property* prop)
{
    if (isRestoring() || isRemoving()) {
        return;
    }

    if (prop == &Elements) {
        auto ret = recompute();
        delete ret;
    }

    MeasureBase::onChanged(prop);
}


namespace Measure
{

Part::MeasureInfoPtr makeVolumeInfo(const App::SubObjectT& subject)
{
    auto mod = Base::Type::getModuleName(subject.getObject()->getTypeId().getName());
    if (mod == "Mesh") {
        return measureVolumeFromMesh(subject);
    }

    return measureVolumeFromPart(subject);
}

}  // namespace Measure

