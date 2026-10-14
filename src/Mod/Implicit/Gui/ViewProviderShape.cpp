// SPDX-License-Identifier: LGPL-2.1-or-later
#include "ViewProviderShape.h"

#include <Inventor/nodes/SoCoordinate3.h>
#include <Inventor/nodes/SoDrawStyle.h>
#include <Inventor/nodes/SoIndexedFaceSet.h>
#include <Inventor/nodes/SoMaterial.h>
#include <Inventor/nodes/SoNormal.h>
#include <Inventor/nodes/SoNormalBinding.h>
#include <Inventor/nodes/SoSeparator.h>
#include <Inventor/nodes/SoShapeHints.h>
#include <Base/Console.h>
#include <Mod/Implicit/App/Feature.h>

using namespace ImplicitGui;
PROPERTY_SOURCE(ImplicitGui::ViewProviderShape, Gui::ViewProviderGeometryObject)

ViewProviderShape::ViewProviderShape()
{
    static const App::PropertyIntegerConstraint::Constraints range = {2, 64, 1};
    ADD_PROPERTY_TYPE(Resolution, (24), "Display", App::Prop_None, "Grid cells per domain axis");
    Resolution.setConstraints(&range);
    ADD_PROPERTY_TYPE(
        AdaptiveSampling,
        (true),
        "Display",
        App::Prop_None,
        "Octree empty-space pruning; resolution rounds up to a power of two"
    );
    ADD_PROPERTY_TYPE(
        SurfaceColor,
        (Base::Color(0.2f, 0.7f, 0.85f)),
        "Display",
        App::Prop_None,
        "Implicit surface color"
    );
    ADD_PROPERTY_TYPE(
        TriangleCount,
        (0),
        "Display",
        static_cast<App::PropertyType>(App::Prop_ReadOnly | App::Prop_Transient),
        "Display cache triangle count"
    );
    ADD_PROPERTY_TYPE(
        CacheBuildCount,
        (0),
        "Display",
        static_cast<App::PropertyType>(App::Prop_ReadOnly | App::Prop_Transient),
        "Display buffer uploads this session"
    );

    coordinates = new SoCoordinate3;
    coordinates->setName("ImplicitCoordinates");
    normals = new SoNormal;
    faces = new SoIndexedFaceSet;
    faces->setName("ImplicitFaces");
    auto* binding = new SoNormalBinding;
    binding->value = SoNormalBinding::PER_VERTEX_INDEXED;
    auto* hints = new SoShapeHints;
    hints->vertexOrdering = SoShapeHints::COUNTERCLOCKWISE;
    shaded = new SoSeparator;
    shaded->ref();
    for (SoNode* node :
         std::array<SoNode*, 6> {pcShapeMaterial, hints, coordinates, normals, binding, faces}) {
        shaded->addChild(node);
    }
    wire = new SoSeparator;
    wire->ref();
    auto* style = new SoDrawStyle;
    style->style = SoDrawStyle::LINES;
    auto* material = new SoMaterial;
    material->diffuseColor.setValue(0.05f, 0.05f, 0.05f);
    wire->addChild(material);
    wire->addChild(style);
    wire->addChild(coordinates);
    wire->addChild(faces);
    combined = new SoSeparator;
    combined->ref();
    combined->addChild(shaded);
    combined->addChild(wire);
    pcShapeMaterial->diffuseColor.setValue(0.2f, 0.7f, 0.85f);
}

ViewProviderShape::~ViewProviderShape()
{
    combined->unref();
    wire->unref();
    shaded->unref();
}

void ViewProviderShape::attach(App::DocumentObject* object)
{
    Gui::ViewProviderGeometryObject::attach(object);
    addDisplayMaskMode(shaded, "Shaded");
    addDisplayMaskMode(wire, "Wireframe");
    addDisplayMaskMode(combined, "Flat Lines");
    updateMesh();
}

void ViewProviderShape::setDisplayMode(const char* mode)
{
    setDisplayMaskMode(mode);
    Gui::ViewProviderGeometryObject::setDisplayMode(mode);
}

std::vector<std::string> ViewProviderShape::getDisplayModes() const
{
    return {"Shaded", "Wireframe", "Flat Lines"};
}

const char* ViewProviderShape::getDefaultDisplayMode() const
{
    return "Shaded";
}

void ViewProviderShape::updateData(const App::Property* property)
{
    Gui::ViewProviderGeometryObject::updateData(property);
    const auto* feature = freecad_cast<Implicit::Feature*>(getObject());
    if (feature && property == &feature->CacheRevision) {
        updateMesh();
    }
}

void ViewProviderShape::finishRestoring()
{
    Gui::ViewProviderGeometryObject::finishRestoring();
    uploadedMesh.reset();
    updateMesh();
}

void ViewProviderShape::onChanged(const App::Property* property)
{
    Gui::ViewProviderGeometryObject::onChanged(property);
    if ((property == &Resolution || property == &AdaptiveSampling) && getObject()) {
        updateMesh();
    }
    if (property == &SurfaceColor && pcShapeMaterial) {
        const auto color = SurfaceColor.getValue();
        pcShapeMaterial->diffuseColor.setValue(color.r, color.g, color.b);
    }
}

void ViewProviderShape::updateMesh()
{
    auto* feature = freecad_cast<Implicit::Feature*>(getObject());
    if (!feature) {
        return;
    }
    try {
        const auto mesh = feature->getDisplayMesh(
            static_cast<unsigned int>(Resolution.getValue()),
            AdaptiveSampling.getValue()
        );
        if (mesh == uploadedMesh) {
            return;
        }
        coordinates->point.setNum(static_cast<int>(mesh->vertices.size()));
        normals->vector.setNum(static_cast<int>(mesh->normals.size()));
        auto* points = coordinates->point.startEditing();
        auto* directions = normals->vector.startEditing();
        for (std::size_t i = 0; i < mesh->vertices.size(); ++i) {
            const auto& point = mesh->vertices[i];
            const auto& normal = mesh->normals[i];
            points[i].setValue(point.x, point.y, point.z);
            directions[i].setValue(normal.x, normal.y, normal.z);
        }
        coordinates->point.finishEditing();
        normals->vector.finishEditing();
        faces->coordIndex.setNum(static_cast<int>(mesh->triangles.size() * 4));
        auto* indices = faces->coordIndex.startEditing();
        std::size_t offset = 0;
        for (const auto& triangle : mesh->triangles) {
            for (auto index : triangle) {
                indices[offset++] = static_cast<int32_t>(index);
            }
            indices[offset++] = -1;
        }
        faces->coordIndex.finishEditing();
        TriangleCount.setValue(static_cast<long>(mesh->triangles.size()));
        CacheBuildCount.setValue(CacheBuildCount.getValue() + 1);
        uploadedMesh = mesh;
    }
    catch (const std::exception& error) {
        coordinates->point.setNum(0);
        normals->vector.setNum(0);
        faces->coordIndex.setNum(0);
        uploadedMesh.reset();
        TriangleCount.setValue(0);
        Base::Console().error("Implicit display: {}\n", error.what());
    }
}
