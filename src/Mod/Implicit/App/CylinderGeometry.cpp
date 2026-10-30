// SPDX-License-Identifier: LGPL-2.1-or-later
#include "CylinderGeometry.h"
#include "CylinderBoundary.h"
#include <TopExp_Explorer.hxx>
#include <App/ComplexGeoDataPy.h>
#include <charconv>
#include <Base/Exception.h>
#include <Base/Reader.h>
#include <Base/Writer.h>
#include <BRep_Tool.hxx>
#include <TopExp.hxx>
#include <TopoDS.hxx>
#include <NCollection_IndexedMap.hxx>
#include <TopTools_ShapeMapHasher.hxx>
#include <Python.h>
#include <cstring>
#include <sstream>

namespace
{
using IO = BRepClass3d_ImplicitCylinderIO;
using Map = NCollection_IndexedMap<TopoDS_Shape, TopTools_ShapeMapHasher>;
constexpr const char* solidName = "ImplicitOCCT.QualifiedStoredCylinder.v1";
constexpr const char* storedName = "ImplicitOCCT.StoredCylinderSolid.v1";
constexpr size_t maximumRecord = 16 * 1024 * 1024;
void identity(const Base::Matrix4D& matrix)
{
    if (matrix != Base::Matrix4D()) {
        throw Base::NotImplementedError("Requalify cylinder geometry after a placement change");
    }
}
std::string readRecord(std::istream& input)
{
    std::string text;
    char buffer[4096];
    while (input.read(buffer, sizeof(buffer)) || input.gcount()) {
        if (text.size() + size_t(input.gcount()) > maximumRecord) {
            throw Base::ValueError("Cylinder record exceeds 16 MiB");
        }
        text.append(buffer, size_t(input.gcount()));
    }
    if (!input.eof() || input.bad()) {
        throw Base::ValueError("Incomplete cylinder geometry payload");
    }
    return text;
}
void destroySolid(PyObject* object)
{
    delete static_cast<IO::Solid*>(PyCapsule_GetPointer(object, solidName));
}
void destroyStored(PyObject* object)
{
    delete static_cast<IO::StoredSolid*>(PyCapsule_GetPointer(object, storedName));
}
TopAbs_ShapeEnum kind(const char* type)
{
    if (!std::strcmp(type, "Solid")) {
        return TopAbs_SOLID;
    }
    if (!std::strcmp(type, "Shell")) {
        return TopAbs_SHELL;
    }
    if (!std::strcmp(type, "Face")) {
        return TopAbs_FACE;
    }
    if (!std::strcmp(type, "Edge")) {
        return TopAbs_EDGE;
    }
    if (!std::strcmp(type, "Vertex")) {
        return TopAbs_VERTEX;
    }
    return TopAbs_SHAPE;
}
class CylinderSegment: public Data::Segment
{
public:
    std::shared_ptr<const IO::Solid> owner;
    std::string name;
    TopoDS_Shape shape;
    std::string getName() const override
    {
        return name;
    }
};
const CylinderSegment& segment(const Data::Segment* value, const std::shared_ptr<const IO::Solid>& owner)
{
    const auto* selected = dynamic_cast<const CylinderSegment*>(value);
    if (!selected || !owner || selected->owner != owner) {
        throw Base::ValueError("Foreign cylinder subelement");
    }
    return *selected;
}
class CylinderSelectedGeometry final: public Implicit::CylinderGeometry
{
    TopoDS_Shape selected;

public:
    CylinderSelectedGeometry(const Implicit::CylinderGeometry& source, const char* type, unsigned long index)
    {
        qualified = source.qualified;
        std::unique_ptr<Data::Segment> value(source.getSubElement(type, index));
        selected = segment(value.get(), qualified).shape;
    }
    std::vector<const char*> getElementTypes() const override
    {
        return {"Element"};
    }
    unsigned long countSubElements(const char* type) const override
    {
        return !std::strcmp(type, "Element") ? 1 : 0;
    }
    Base::BoundBox3d getBoundBox() const override
    {
        if (selected.ShapeType() != TopAbs_VERTEX) {
            return CylinderGeometry::getBoundBox();
        }
        const auto p = BRep_Tool::Pnt(TopoDS::Vertex(selected));
        Base::BoundBox3d box;
        box.Add(Base::Vector3d(p.X(), p.Y(), p.Z()));
        return box;
    }
    Data::Segment* getSubElement(const char* type, unsigned long index) const override
    {
        if (std::strcmp(type, "Element") || index != 1) {
            throw Base::ValueError("Invalid selected cylinder element");
        }
        auto value = std::make_unique<CylinderSegment>();
        value->owner = qualified;
        value->shape = selected;
        value->name = "Element1";
        return value.release();
    }
    void getLines(
        std::vector<Base::Vector3d>& points,
        std::vector<Line>& lines,
        double accuracy,
        uint16_t
    ) const override
    {
        Implicit::detail::cylinderBoundary(selected, accuracy, points, lines);
    }
    void getPoints(
        std::vector<Base::Vector3d>& points,
        std::vector<Base::Vector3d>&,
        double,
        uint16_t
    ) const override
    {
        Map vertices;
        TopExp::MapShapes(selected, TopAbs_VERTEX, vertices);
        for (const auto& vertex : vertices) {
            const auto p = BRep_Tool::Pnt(TopoDS::Vertex(vertex));
            points.emplace_back(p.X(), p.Y(), p.Z());
        }
    }
};
}  // namespace

TYPESYSTEM_SOURCE(Implicit::CylinderGeometry, Data::ComplexGeoData)
TYPESYSTEM_SOURCE(Implicit::PropertyNativeCylinderGeometry, App::PropertyComplexGeoData)
PROPERTY_SOURCE(Implicit::NativeCylinderFeature, App::GeoFeature)

namespace Implicit
{
std::vector<const char*> CylinderGeometry::getElementTypes() const
{
    return {"Solid", "Shell", "Face", "Edge", "Vertex"};
}
unsigned long CylinderGeometry::countSubElements(const char* type) const
{
    if (!ready() || kind(type) == TopAbs_SHAPE) {
        return 0;
    }
    Map map;
    TopExp::MapShapes(qualified->Shape, kind(type), map);
    return map.Size();
}
Data::Segment* CylinderGeometry::getSubElement(const char* type, unsigned long index) const
{
    if (!ready() || kind(type) == TopAbs_SHAPE) {
        throw Base::ValueError("Cylinder geometry is unverified or element type is unsupported");
    }
    Map map;
    TopExp::MapShapes(qualified->Shape, kind(type), map);
    if (!index || index > map.Size()) {
        throw Base::ValueError("Cylinder subelement index out of range");
    }
    auto result = std::make_unique<CylinderSegment>();
    result->name = std::string(type) + std::to_string(index);
    result->owner = qualified;
    result->shape = map.FindKey(int(index));
    return result.release();
}
void CylinderGeometry::getLines(
    std::vector<Base::Vector3d>& points,
    std::vector<Line>& lines,
    double accuracy,
    uint16_t
) const
{
    if (!ready()) {
        throw Base::ValueError("Cylinder geometry is unverified");
    }
    detail::cylinderBoundary(qualified->Shape, accuracy, points, lines);
}
void CylinderGeometry::getPoints(
    std::vector<Base::Vector3d>& points,
    std::vector<Base::Vector3d>&,
    double,
    uint16_t
) const
{
    if (!ready()) {
        throw Base::ValueError("Cylinder geometry is unverified");
    }
    Map vertices;
    TopExp::MapShapes(qualified->Shape, TopAbs_VERTEX, vertices);
    for (const auto& vertex : vertices) {
        const auto p = BRep_Tool::Pnt(TopoDS::Vertex(vertex));
        points.emplace_back(p.X(), p.Y(), p.Z());
    }
}
void CylinderGeometry::getLinesFromSubElement(
    const Data::Segment* value,
    std::vector<Base::Vector3d>& points,
    std::vector<Line>& lines
) const
{
    detail::cylinderBoundary(segment(value, qualified).shape, .01, points, lines);
}
bool CylinderGeometry::getFirstVertexFromSubElement(const Data::Segment* value, Base::Vector3d& point) const
{
    const auto& shape = segment(value, qualified).shape;
    if (shape.ShapeType() == TopAbs_VERTEX) {
        const auto p = BRep_Tool::Pnt(TopoDS::Vertex(shape));
        point = Base::Vector3d(p.X(), p.Y(), p.Z());
        return true;
    }
    TopExp_Explorer vertices(shape, TopAbs_VERTEX);
    if (!vertices.More()) {
        return false;
    }
    const auto p = BRep_Tool::Pnt(TopoDS::Vertex(vertices.Current()));
    point = Base::Vector3d(p.X(), p.Y(), p.Z());
    return true;
}
void CylinderGeometry::setTransform(const Base::Matrix4D& matrix)
{
    identity(matrix);
}
Base::Matrix4D CylinderGeometry::getTransform() const
{
    return {};
}
void CylinderGeometry::transformGeometry(const Base::Matrix4D& matrix)
{
    identity(matrix);
}
Base::BoundBox3d CylinderGeometry::getBoundBox() const
{
    Base::BoundBox3d box;
    if (!qualified && !stored) {
        return box;
    }
    const auto& s = qualified ? qualified->Source.Parameters : stored->Parameters;
    const gp_Vec x(s.Frame.XDirection()), y(s.Frame.YDirection()), z(s.Frame.Direction());
    for (double a : {-s.Radius, s.Radius}) {
        for (double b : {-s.Radius, s.Radius}) {
            for (double c : {s.HeightMinimum, s.HeightMaximum}) {
                const auto p = s.Frame.Location().Translated(x * a + y * b + z * c);
                box.Add(Base::Vector3d(p.X(), p.Y(), p.Z()));
            }
        }
    }
    return box;
}
void CylinderGeometry::getFaces(std::vector<Base::Vector3d>&, std::vector<Facet>&, double, uint16_t) const
{
    throw Base::NotImplementedError("Cylinder display needs a trim-conforming transient cache");
}
void CylinderGeometry::Save(Base::Writer&) const
{
    throw Base::NotImplementedError("Persist through PropertyNativeCylinderGeometry");
}
void CylinderGeometry::Restore(Base::XMLReader&)
{
    throw Base::NotImplementedError("Restore through PropertyNativeCylinderGeometry");
}
unsigned int CylinderGeometry::getMemSize() const
{
    return unsigned(sizeof(*this) + record.size());
}

void PropertyNativeCylinderGeometry::assign(const CylinderGeometry& next)
{
    // Allocate the potentially large payload before starting property mutation.
    auto record = next.record;
    aboutToSetValue();
    data.qualified = next.qualified;
    data.stored = next.stored;
    data.record.swap(record);
    data.resetElementMap();
    hasSetValue();
}
void PropertyNativeCylinderGeometry::setValue(std::shared_ptr<const CylinderGeometry::Solid> value)
{
    CylinderGeometry next;
    if (value) {
        if (!value->Verified) {
            throw Base::ValueError("Cylinder solid is unqualified");
        }
        std::ostringstream output;
        try {
            IO::Write(*value, output);
        }
        catch (const Standard_Failure& error) {
            throw Base::ValueError(error.what());
        }
        next.record = output.str();
        next.qualified = std::move(value);
    }
    assign(next);
}
void PropertyNativeCylinderGeometry::setRecord(const std::string& text)
{
    if (text.empty() || text.size() > maximumRecord) {
        throw Base::ValueError("Invalid cylinder payload size");
    }
    auto value = std::make_shared<IO::StoredSolid>();
    std::istringstream input(text);
    try {
        IO::Read(input, *value);
    }
    catch (const Standard_Failure& error) {
        throw Base::ValueError(error.what());
    }
    CylinderGeometry next;
    next.stored = std::move(value);
    next.record = text;
    assign(next);
}
const Data::ComplexGeoData* PropertyNativeCylinderGeometry::getComplexData() const
{
    return &data;
}
void PropertyNativeCylinderGeometry::setTransform(const Base::Matrix4D& matrix)
{
    identity(matrix);
}
Base::Matrix4D PropertyNativeCylinderGeometry::getTransform() const
{
    return {};
}
void PropertyNativeCylinderGeometry::transformGeometry(const Base::Matrix4D& matrix)
{
    identity(matrix);
}
Base::BoundBox3d PropertyNativeCylinderGeometry::getBoundingBox() const
{
    return data.getBoundBox();
}
PyObject* PropertyNativeCylinderGeometry::getPyObject()
{
    if (data.qualified) {
        auto value = std::make_unique<IO::Solid>(*data.qualified);
        PyObject* result = PyCapsule_New(value.get(), solidName, destroySolid);
        if (result) {
            value.release();
        }
        return result;
    }
    if (data.stored) {
        auto value = std::make_unique<IO::StoredSolid>(*data.stored);
        PyObject* result = PyCapsule_New(value.get(), storedName, destroyStored);
        if (result) {
            value.release();
        }
        return result;
    }
    Py_RETURN_NONE;
}
void PropertyNativeCylinderGeometry::setPyObject(PyObject* object)
{
    if (object == Py_None) {
        setValue(nullptr);
        return;
    }
    if (PyCapsule_IsValid(object, solidName)) {
        setValue(
            std::make_shared<const IO::Solid>(
                *static_cast<const IO::Solid*>(PyCapsule_GetPointer(object, solidName))
            )
        );
        return;
    }
    if (PyUnicode_Check(object)) {
        Py_ssize_t length;
        const char* text = PyUnicode_AsUTF8AndSize(object, &length);
        if (!text) {
            throw Base::ValueError("Cylinder payload is not UTF-8");
        }
        if (length > Py_ssize_t(maximumRecord)) {
            throw Base::ValueError("Cylinder payload exceeds 16 MiB");
        }
        setRecord(std::string(text, size_t(length)));
        return;
    }
    throw Base::TypeError("Expected a qualified restored cylinder, graph record or None");
}
App::Property* PropertyNativeCylinderGeometry::Copy() const
{
    auto value = new PropertyNativeCylinderGeometry;
    value->data.qualified = data.qualified;
    value->data.stored = data.stored;
    value->data.record = data.record;
    return value;
}
void PropertyNativeCylinderGeometry::Paste(const App::Property& from)
{
    if (from.getTypeId() != getTypeId()) {
        throw Base::TypeError("Cylinder geometry property types differ");
    }
    assign(static_cast<const PropertyNativeCylinderGeometry&>(from).data);
}
unsigned int PropertyNativeCylinderGeometry::getMemSize() const
{
    return data.getMemSize();
}
void PropertyNativeCylinderGeometry::Save(Base::Writer& writer) const
{
    if (empty()) {
        writer.Stream() << writer.ind() << "<NativeCylinderGeometry schema=\"1\" empty=\"1\"/>\n";
    }
    else if (writer.isForceXML()) {
        writer.Stream() << writer.ind()
                        << "<NativeCylinderGeometry schema=\"1\" inline=\"1\" bytes=\""
                        << data.record.size() << "\">\n";
        writer.beginCharStream(Base::CharStreamFormat::Base64Encoded) << data.record;
        writer.endCharStream() << writer.ind() << "</NativeCylinderGeometry>\n";
    }
    else {
        writer.Stream() << writer.ind() << "<NativeCylinderGeometry schema=\"1\" file=\""
                        << writer.addFile(getFileName(".nativecylinder").c_str(), this) << "\"/>\n";
    }
}
void PropertyNativeCylinderGeometry::Restore(Base::XMLReader& reader)
{
    reader.readElement("NativeCylinderGeometry");
    if (reader.getAttribute<int>("schema") != 1) {
        throw Base::ValueError("Unsupported cylinder property schema");
    }
    if (reader.getAttribute<int>("empty", 0)) {
        setValue(nullptr);
        return;
    }
    if (reader.getAttribute<int>("inline", 0)) {
        std::string text;
        const int count = reader.getAttribute<int>("bytes", 0);
        if (count <= 0 || size_t(count) > maximumRecord) {
            throw Base::ValueError("Invalid inline cylinder payload size");
        }
        text.resize(size_t(count));
        try {
            auto& input = reader.beginCharStream(Base::CharStreamFormat::Base64Encoded);
            if (!input.read(text.data(), count)) {
                throw Base::ValueError("Truncated inline cylinder payload");
            }
        }
        catch (...) {
            reader.endCharStream();
            throw;
        }
        reader.endCharStream();
        setRecord(text);
    }
    else {
        const auto file = reader.getAttribute<std::string>("file");
        if (file.empty()) {
            throw Base::ValueError("Missing cylinder geometry payload");
        }
        reader.addFile(file.c_str(), this);
    }
}
void PropertyNativeCylinderGeometry::SaveDocFile(Base::Writer& writer) const
{
    writer.Stream() << data.record;
}
void PropertyNativeCylinderGeometry::RestoreDocFile(Base::Reader& reader)
{
    setRecord(readRecord(reader));
}

NativeCylinderFeature::NativeCylinderFeature()
{
    ADD_PROPERTY_TYPE(
        Geometry,
        (nullptr),
        "Native cylinder",
        App::Prop_Output,
        "Authoritative native cylinder graph; not a Part Shape"
    );
    ADD_PROPERTY_TYPE(
        GeometryState,
        ("Empty"),
        "Native cylinder",
        App::PropertyType(App::Prop_ReadOnly | App::Prop_Output | App::Prop_Transient),
        "Empty, Unverified or Ready; restore never retains qualification"
    );
}
const App::PropertyComplexGeoData* NativeCylinderFeature::getPropertyOfGeometry() const
{
    return &Geometry;
}
const char* NativeCylinderFeature::getViewProviderName() const
{
    return "Gui::ViewProviderGeometryPython";
}
void NativeCylinderFeature::onChanged(const App::Property* property)
{
    if (property == &Geometry) {
        GeometryState.setValue(
            Geometry.empty()       ? "Empty"
                : Geometry.ready() ? "Ready"
                                   : "Unverified"
        );
    }
    App::GeoFeature::onChanged(property);
}
App::DocumentObject* NativeCylinderFeature::getSubObject(
    const char* name,
    PyObject** pyObject,
    Base::Matrix4D* matrix,
    bool transform,
    int depth
) const
{
    if (!name || !*name || std::strchr(name, '.')) {
        return App::GeoFeature::getSubObject(name, pyObject, matrix, transform, depth);
    }
    if (!Geometry.ready()) {
        return nullptr;
    }
    const auto* geometry = static_cast<const CylinderGeometry*>(Geometry.getComplexData());
    for (const auto* type : geometry->getElementTypes()) {
        const size_t length = std::strlen(type);
        if (std::strncmp(name, type, length)) {
            continue;
        }
        unsigned long index = 0;
        const auto parsed = std::from_chars(name + length, name + std::strlen(name), index);
        if (parsed.ec != std::errc() || *parsed.ptr || !index
            || index > geometry->countSubElements(type)) {
            return nullptr;
        }
        Base::Matrix4D placed = matrix ? *matrix : Base::Matrix4D();
        if (transform) {
            placed *= Placement.getValue().toMatrix();
        }
        if (placed != Base::Matrix4D()) {
            return nullptr;
        }
        if (pyObject) {
            auto selected = std::make_unique<CylinderSelectedGeometry>(*geometry, type, index);
            *pyObject = new Data::ComplexGeoDataPy(selected.get());
            selected.release();
        }
        if (matrix) {
            *matrix = placed;
        }
        return const_cast<NativeCylinderFeature*>(this);
    }
    return nullptr;
}
}  // namespace Implicit
