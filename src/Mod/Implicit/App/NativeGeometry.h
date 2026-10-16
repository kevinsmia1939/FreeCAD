// SPDX-License-Identifier: LGPL-2.1-or-later
#pragma once
#include <App/ComplexGeoData.h>
#include <App/PropertyGeo.h>
#include <App/GeoFeature.h>
#include <App/FeaturePython.h>
#include <Mod/Implicit/ImplicitGlobal.h>
#include <BRepClass3d_ImplicitBox.hxx>
#include <memory>

namespace Implicit
{
using NativeBoundary = BRepClass3d_ImplicitBox::Boundary;
using NativeBoundaryPtr = std::shared_ptr<const NativeBoundary>;

// Immutable kernel geometry, not a mesh or a Python recipe. Geometry-property
// persistence owns I/O; generic surface meshing/transforms remain guarded.
class ImplicitExport NativeGeometry: public Data::ComplexGeoData
{
    TYPESYSTEM_HEADER_WITH_OVERRIDE();

public:
    NativeBoundaryPtr boundary;
    std::vector<const char*> getElementTypes() const override;
    unsigned long countSubElements(const char*) const override;
    Data::Segment* getSubElement(const char*, unsigned long) const override;
    void setTransform(const Base::Matrix4D&) override;
    Base::Matrix4D getTransform() const override;
    void transformGeometry(const Base::Matrix4D&) override;
    Base::BoundBox3d getBoundBox() const override;
    void getFaces(std::vector<Base::Vector3d>&, std::vector<Facet>&, double, uint16_t = 0) const override;
    void getPoints(
        std::vector<Base::Vector3d>&,
        std::vector<Base::Vector3d>&,
        double,
        uint16_t = 0
    ) const override;
    void getLines(std::vector<Base::Vector3d>&, std::vector<Line>&, double, uint16_t = 0) const override;
    void Save(Base::Writer&) const override;
    void Restore(Base::XMLReader&) override;
    unsigned int getMemSize() const override;
};

class ImplicitExport PropertyNativeGeometry: public App::PropertyComplexGeoData
{
    TYPESYSTEM_HEADER_WITH_OVERRIDE();

public:
    void setValue(NativeBoundaryPtr);
    bool isNull() const
    {
        return !data.boundary;
    }
    const Data::ComplexGeoData* getComplexData() const override;
    void setTransform(const Base::Matrix4D&) override;
    Base::Matrix4D getTransform() const override;
    void transformGeometry(const Base::Matrix4D&) override;
    Base::BoundBox3d getBoundingBox() const override;
    PyObject* getPyObject() override;
    void setPyObject(PyObject*) override;
    App::Property* Copy() const override;
    void Paste(const App::Property&) override;
    void Save(Base::Writer&) const override;
    void Restore(Base::XMLReader&) override;
    void SaveDocFile(Base::Writer&) const override;
    void RestoreDocFile(Base::Reader&) override;
    unsigned int getMemSize() const override;

private:
    NativeGeometry data;
};

class ImplicitExport NativeFeature: public App::GeoFeature
{
    PROPERTY_HEADER_WITH_OVERRIDE(Implicit::NativeFeature);

public:
    NativeFeature();
    PropertyNativeGeometry Geometry;
    const App::PropertyComplexGeoData* getPropertyOfGeometry() const override;
    const char* getViewProviderName() const override;

protected:
    void onSettingDocument() override;

private:
    fastsignals::scoped_connection recomputedConnection;
};
using NativeFeaturePython = App::FeaturePythonT<NativeFeature>;
}  // namespace Implicit
