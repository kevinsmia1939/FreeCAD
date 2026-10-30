// SPDX-License-Identifier: LGPL-2.1-or-later
#pragma once
#include <App/ComplexGeoData.h>
#include <App/PropertyGeo.h>
#include <App/PropertyStandard.h>
#include <App/GeoFeature.h>
#include <Mod/Implicit/ImplicitGlobal.h>
#include <BRepClass3d_ImplicitCylinderIO.hxx>
#include <memory>

namespace Implicit
{
class ImplicitExport CylinderGeometry: public Data::ComplexGeoData
{
    TYPESYSTEM_HEADER_WITH_OVERRIDE();

public:
    using Solid = BRepClass3d_ImplicitCylinderIO::Solid;
    using Stored = BRepClass3d_ImplicitCylinderIO::StoredSolid;
    std::shared_ptr<const Solid> qualified;
    std::shared_ptr<const Stored> stored;
    std::string record;
    bool ready() const
    {
        return qualified && qualified->Verified;
    }
    std::vector<const char*> getElementTypes() const override;
    unsigned long countSubElements(const char*) const override;
    Data::Segment* getSubElement(const char*, unsigned long) const override;
    void getLines(std::vector<Base::Vector3d>&, std::vector<Line>&, double, uint16_t = 0) const override;
    void getPoints(
        std::vector<Base::Vector3d>&,
        std::vector<Base::Vector3d>&,
        double,
        uint16_t = 0
    ) const override;
    void getLinesFromSubElement(
        const Data::Segment*,
        std::vector<Base::Vector3d>&,
        std::vector<Line>&
    ) const override;
    bool getFirstVertexFromSubElement(const Data::Segment*, Base::Vector3d&) const override;
    void setTransform(const Base::Matrix4D&) override;
    Base::Matrix4D getTransform() const override;
    void transformGeometry(const Base::Matrix4D&) override;
    Base::BoundBox3d getBoundBox() const override;
    void getFaces(std::vector<Base::Vector3d>&, std::vector<Facet>&, double, uint16_t = 0) const override;
    void Save(Base::Writer&) const override;
    void Restore(Base::XMLReader&) override;
    unsigned int getMemSize() const override;
};

class ImplicitExport PropertyNativeCylinderGeometry: public App::PropertyComplexGeoData
{
    TYPESYSTEM_HEADER_WITH_OVERRIDE();

public:
    void setValue(std::shared_ptr<const CylinderGeometry::Solid>);
    void setRecord(const std::string&);
    bool ready() const
    {
        return data.ready();
    }
    bool empty() const
    {
        return data.record.empty();
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
    CylinderGeometry data;
    void assign(const CylinderGeometry&);
};

class ImplicitExport NativeCylinderFeature: public App::GeoFeature
{
    PROPERTY_HEADER_WITH_OVERRIDE(Implicit::NativeCylinderFeature);

public:
    NativeCylinderFeature();
    PropertyNativeCylinderGeometry Geometry;
    App::PropertyString GeometryState;
    const App::PropertyComplexGeoData* getPropertyOfGeometry() const override;
    const char* getViewProviderName() const override;

protected:
    void onChanged(const App::Property*) override;
};
}  // namespace Implicit
