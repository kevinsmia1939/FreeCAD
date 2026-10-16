// SPDX-License-Identifier: LGPL-2.1-or-later
#include "NativeGeometry.h"
#include <Base/Exception.h>
#include <Base/Reader.h>
#include <Base/Writer.h>
#include <Base/BoundBox.h>
#include <App/GeoFeaturePy.h>
#include <App/FeaturePythonPyImp.h>
#include <App/Document.h>
#include <App/PropertyStandard.h>
#include <BRepClass3d_ImplicitBoxIO.hxx>
#include <BRep_TImplicitFace.hxx>
#include <BRep_Tool.hxx>
#include <Geom_BSplineCurve.hxx>
#include <TopExp.hxx>
#include <TopoDS.hxx>
#include <NCollection_IndexedMap.hxx>
#include <TopTools_ShapeMapHasher.hxx>
#include <Python.h>
#include <cstring>
#include <sstream>

namespace
{
constexpr const char* capsuleName = "ImplicitOCCT.HybridBoundary.v1";
void destroyBoundary(PyObject* capsule)
{
    if (PyCapsule_IsValid(capsule, capsuleName)) {
        delete static_cast<Implicit::NativeBoundary*>(PyCapsule_GetPointer(capsule, capsuleName));
    }
}
void identityOnly(const Base::Matrix4D& matrix)
{
    if (matrix != Base::Matrix4D()) {
        throw Base::NotImplementedError(
            "Native mixed geometry does not yet support geometry transforms"
        );
    }
}
Implicit::NativeBoundaryPtr readBoundary(std::istream& input)
{
    auto value = std::make_shared<Implicit::NativeBoundary>();
    try {
        BRepClass3d_ImplicitBoxIO::Read(input, *value);
    }
    catch (const Standard_Failure& error) {
        throw Base::ValueError(error.what());
    }
    return value;
}
void writeBoundary(const Implicit::NativeBoundary& value, std::ostream& output)
{
    try {
        BRepClass3d_ImplicitBoxIO::Write(value, output);
    }
    catch (const Standard_Failure& error) {
        throw Base::ValueError(error.what());
    }
}
}  // namespace

namespace Implicit
{
TYPESYSTEM_SOURCE(Implicit::NativeGeometry, Data::ComplexGeoData)
TYPESYSTEM_SOURCE(Implicit::PropertyNativeGeometry, App::PropertyComplexGeoData)
PROPERTY_SOURCE(Implicit::NativeFeature, App::GeoFeature)

std::vector<const char*> NativeGeometry::getElementTypes() const
{
    return {"NativeFace", "Cap", "Seam"};
}
unsigned long NativeGeometry::countSubElements(const char* type) const
{
    if (!boundary) {
        return 0;
    }
    if (std::strcmp(type, "NativeFace") == 0) {
        return 1;
    }
    if (std::strcmp(type, "Cap") == 0) {
        return boundary->Faces.size() - 1;
    }
    if (std::strcmp(type, "Seam") == 0) {
        return boundary->SeamCount;
    }
    return 0;
}
Data::Segment* NativeGeometry::getSubElement(const char*, unsigned long) const
{
    throw Base::NotImplementedError("Native mixed subelement selection is not yet implemented");
}
void NativeGeometry::setTransform(const Base::Matrix4D& matrix)
{
    identityOnly(matrix);
}
Base::Matrix4D NativeGeometry::getTransform() const
{
    return {};
}
void NativeGeometry::transformGeometry(const Base::Matrix4D& matrix)
{
    identityOnly(matrix);
}
Base::BoundBox3d NativeGeometry::getBoundBox() const
{
    if (!boundary) {
        return Base::BoundBox3d();
    }
    const auto data = occ::down_cast<BRep_TImplicitFace>(boundary->Faces.back().TShape());
    const auto a = data->Minimum(), b = data->Maximum();
    return Base::BoundBox3d(a.X(), a.Y(), a.Z(), b.X(), b.Y(), b.Z());
}
void NativeGeometry::getFaces(std::vector<Base::Vector3d>&, std::vector<Facet>&, double, uint16_t) const
{
    throw Base::NotImplementedError(
        "A conforming native implicit surface mesher is required; cap-only output refused"
    );
}
void NativeGeometry::getPoints(
    std::vector<Base::Vector3d>&,
    std::vector<Base::Vector3d>&,
    double,
    uint16_t
) const
{
    throw Base::NotImplementedError(
        "Native mixed surface sampling is not yet implemented; partial output refused"
    );
}
void NativeGeometry::getLines(
    std::vector<Base::Vector3d>& points,
    std::vector<Line>& lines,
    double,
    uint16_t
) const
{
    if (!boundary) {
        return;
    }
    NCollection_IndexedMap<TopoDS_Shape, TopTools_ShapeMapHasher> edges;
    TopExp::MapShapes(boundary->Shape, TopAbs_EDGE, edges);
    for (const auto& edge : edges) {
        TopLoc_Location location;
        double first, last;
        const auto curve = occ::down_cast<Geom_BSplineCurve>(
            BRep_Tool::Curve(TopoDS::Edge(edge), location, first, last)
        );
        if (curve.IsNull()) {
            throw Base::NotImplementedError("Unsupported native boundary curve");
        }
        const auto base = static_cast<uint32_t>(points.size());
        for (int i = 1; i <= curve->NbPoles(); ++i) {
            const auto p = curve->Pole(i).Transformed(location.Transformation());
            points.emplace_back(p.X(), p.Y(), p.Z());
            if (i > 1) {
                lines.push_back({base + uint32_t(i - 2), base + uint32_t(i - 1)});
            }
        }
    }
}
void NativeGeometry::Save(Base::Writer&) const
{
    throw Base::NotImplementedError("Persist native geometry through PropertyNativeGeometry");
}
void NativeGeometry::Restore(Base::XMLReader&)
{
    throw Base::NotImplementedError("Restore native geometry through PropertyNativeGeometry");
}
unsigned int NativeGeometry::getMemSize() const
{
    return sizeof(*this)
        + (boundary ? unsigned(boundary->Faces.size() * 256 + boundary->SeamCount * 128) : 0);
}
void PropertyNativeGeometry::setValue(NativeBoundaryPtr value)
{
    aboutToSetValue();
    data.boundary = std::move(value);
    hasSetValue();
}
const Data::ComplexGeoData* PropertyNativeGeometry::getComplexData() const
{
    return &data;
}
void PropertyNativeGeometry::setTransform(const Base::Matrix4D& matrix)
{
    identityOnly(matrix);
}
Base::Matrix4D PropertyNativeGeometry::getTransform() const
{
    return {};
}
void PropertyNativeGeometry::transformGeometry(const Base::Matrix4D& matrix)
{
    identityOnly(matrix);
}
Base::BoundBox3d PropertyNativeGeometry::getBoundingBox() const
{
    return data.getBoundBox();
}
PyObject* PropertyNativeGeometry::getPyObject()
{
    if (!data.boundary) {
        Py_RETURN_NONE;
    }
    auto owned = std::make_unique<NativeBoundary>(*data.boundary);
    PyObject* result = PyCapsule_New(owned.get(), capsuleName, destroyBoundary);
    if (result) {
        owned.release();
    }
    return result;
}
void PropertyNativeGeometry::setPyObject(PyObject* object)
{
    if (object == Py_None) {
        setValue(nullptr);
        return;
    }
    if (PyCapsule_IsValid(object, capsuleName)) {
        setValue(
            std::make_shared<const NativeBoundary>(
                *static_cast<const NativeBoundary*>(PyCapsule_GetPointer(object, capsuleName))
            )
        );
        return;
    }
    if (PyUnicode_Check(object)) {
        Py_ssize_t size;
        const char* text = PyUnicode_AsUTF8AndSize(object, &size);
        if (!text) {
            throw Base::ValueError("Native geometry record is not UTF-8");
        }
        if (size > 16 * 1024 * 1024) {
            throw Base::ValueError("Native geometry record exceeds 16 MiB");
        }
        std::istringstream input(std::string(text, size));
        setValue(readBoundary(input));
        return;
    }
    throw Base::TypeError(
        "Expected a native mixed-boundary snapshot, topology record or None; not a Part shape"
    );
}
App::Property* PropertyNativeGeometry::Copy() const
{
    auto result = new PropertyNativeGeometry;
    result->data.boundary = data.boundary;  // immutable sharing, never editable kernel aliasing
    return result;
}
void PropertyNativeGeometry::Paste(const App::Property& from)
{
    setValue(dynamic_cast<const PropertyNativeGeometry&>(from).data.boundary);
}
unsigned int PropertyNativeGeometry::getMemSize() const
{
    return data.getMemSize();
}
void PropertyNativeGeometry::Save(Base::Writer& writer) const
{
    if (!data.boundary) {
        writer.Stream() << writer.ind() << "<NativeGeometry schema=\"1\" empty=\"1\"/>\n";
    }
    else if (writer.isForceXML()) {
        writer.Stream() << writer.ind() << "<NativeGeometry schema=\"1\" inline=\"1\">\n";
        writeBoundary(*data.boundary, writer.beginCharStream(Base::CharStreamFormat::Base64Encoded));
        writer.endCharStream() << writer.ind() << "</NativeGeometry>\n";
    }
    else {
        writer.Stream() << writer.ind() << "<NativeGeometry schema=\"1\" file=\""
                        << writer.addFile(getFileName(".nativegeo").c_str(), this) << "\"/>\n";
    }
}
void PropertyNativeGeometry::Restore(Base::XMLReader& reader)
{
    reader.readElement("NativeGeometry");
    if (reader.getAttribute<int>("schema") != 1) {
        throw Base::ValueError("Unsupported native geometry property schema");
    }
    if (reader.getAttribute<int>("empty", 0)) {
        setValue(nullptr);
        return;
    }
    if (reader.getAttribute<int>("inline", 0)) {
        auto& input = reader.beginCharStream(Base::CharStreamFormat::Base64Encoded);
        NativeBoundaryPtr next;
        try {
            next = readBoundary(input);
        }
        catch (...) {
            reader.endCharStream();
            throw;
        }
        reader.endCharStream();
        setValue(std::move(next));
    }
    else {
        const auto file = reader.getAttribute<std::string>("file");
        if (file.empty()) {
            throw Base::ValueError("Missing native geometry payload");
        }
        reader.addFile(file.c_str(), this);
    }
}
void PropertyNativeGeometry::SaveDocFile(Base::Writer& writer) const
{
    if (data.boundary) {
        writeBoundary(*data.boundary, writer.Stream());
    }
}
void PropertyNativeGeometry::RestoreDocFile(Base::Reader& reader)
{
    setValue(readBoundary(reader));
}
NativeFeature::NativeFeature()
{
    ADD_PROPERTY_TYPE(
        Geometry,
        (nullptr),
        "Native geometry",
        App::Prop_Output,
        "Authoritative native mixed geometry; not Part::Feature::Shape"
    );
}
const App::PropertyComplexGeoData* NativeFeature::getPropertyOfGeometry() const
{
    return &Geometry;
}
const char* NativeFeature::getViewProviderName() const
{
    return "Gui::ViewProviderGeometryPython";
}
void NativeFeature::onSettingDocument()
{
    App::GeoFeature::onSettingDocument();
    recomputedConnection.disconnect();
    if (getDocument()) {
        recomputedConnection = getDocument()->signalRecomputed.connect(
            [this](const App::Document&, const std::vector<App::DocumentObject*>&) {
                if (isRestoring()) {
                    return;
                }
                for (const auto* input : getOutList()) {
                    if (!input->isError()) {
                        continue;
                    }
                    // Source errors can skip Python execution entirely. Clear
                    // the C++ geometry too, so no valid-looking stale body or
                    // proxy/view cache survives that skipped recompute.
                    if (!Geometry.isNull()) {
                        Geometry.setValue(nullptr);
                    }
                    setError();
                    if (auto* status
                        = dynamic_cast<App::PropertyString*>(getPropertyByName("BackendStatus"))) {
                        status->setValue("Native geometry invalidated: an input is in an error state");
                    }
                    break;
                }
            }
        );
    }
}
}  // namespace Implicit

namespace App
{
PROPERTY_SOURCE_TEMPLATE(Implicit::NativeFeaturePython, Implicit::NativeFeature)
template<>
PyObject* Implicit::NativeFeaturePython::getPyObject()
{
    if (PythonObject.is(Py::_None())) {
        PythonObject = Py::Object(new FeaturePythonPyT<GeoFeaturePy>(this), true);
    }
    return Py::new_reference_to(PythonObject);
}
template class ImplicitExport FeaturePythonT<Implicit::NativeFeature>;
}  // namespace App
