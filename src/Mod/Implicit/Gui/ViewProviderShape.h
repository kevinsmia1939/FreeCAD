// SPDX-License-Identifier: LGPL-2.1-or-later
#pragma once
#include <Gui/ViewProviderGeometryObject.h>
#include <Mod/Implicit/App/SurfaceMesh.h>

class SoCoordinate3;
class SoNormal;
class SoIndexedFaceSet;
class SoSeparator;

namespace ImplicitGui
{
class ViewProviderShape: public Gui::ViewProviderGeometryObject
{
    PROPERTY_HEADER_WITH_OVERRIDE(ImplicitGui::ViewProviderShape);

public:
    ViewProviderShape();
    ~ViewProviderShape() override;
    App::PropertyIntegerConstraint Resolution;
    App::PropertyBool AdaptiveSampling;
    App::PropertyColor SurfaceColor;
    App::PropertyInteger TriangleCount;
    App::PropertyInteger CacheBuildCount;
    void attach(App::DocumentObject*) override;
    void updateData(const App::Property*) override;
    void finishRestoring() override;
    void setDisplayMode(const char*) override;
    std::vector<std::string> getDisplayModes() const override;
    const char* getDefaultDisplayMode() const override;

protected:
    void onChanged(const App::Property*) override;

private:
    void updateMesh();
    SoSeparator* shaded;
    SoSeparator* wire;
    SoSeparator* combined;
    SoCoordinate3* coordinates;
    SoNormal* normals;
    SoIndexedFaceSet* faces;
    std::shared_ptr<const Implicit::SurfaceMesh> uploadedMesh;
};
}  // namespace ImplicitGui
