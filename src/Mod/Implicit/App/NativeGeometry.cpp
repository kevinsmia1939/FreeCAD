// SPDX-License-Identifier: LGPL-2.1-or-later
#include "NativeGeometry.h"
#include <Base/Exception.h>
#include <Base/Reader.h>
#include <Base/Writer.h>
#include <Base/BoundBox.h>
#include <App/GeoFeaturePy.h>
#include <App/FeaturePythonPyImp.h>
#include <App/Document.h>
#include <App/ElementNamingUtils.h>
#include <App/ComplexGeoDataPy.h>
#include <App/PropertyStandard.h>
#include <BRepClass3d_ImplicitBoxIO.hxx>
#include <BRep_TImplicitFace.hxx>
#include <BRep_Tool.hxx>
#include <Geom_BSplineCurve.hxx>
#include <TopExp.hxx>
#include <TopExp_Explorer.hxx>
#include <TopoDS.hxx>
#include <NCollection_IndexedMap.hxx>
#include <TopTools_ShapeMapHasher.hxx>
#include <Python.h>
#include <QCryptographicHash>
#include <cstring>
#include <cmath>
#include <sstream>
#include <limits>

namespace
{
constexpr const char* capsuleName = "ImplicitOCCT.HybridBoundary.v1";
void placePoint(const Base::Matrix4D& matrix, Base::Vector3d& point)
{
    matrix.multVec(point, point);
    if (!std::isfinite(point.x) || !std::isfinite(point.y) || !std::isfinite(point.z)) {
        throw Base::ValueError("Native subelement placement produced a nonfinite point");
    }
}
void requireRigid(const Base::Matrix4D& matrix)
{
    for (int row = 0; row < 4; ++row) {
        for (int column = 0; column < 4; ++column) {
            if (!std::isfinite(matrix[row][column])) {
                throw Base::ValueError("Nonfinite native geometry placement");
            }
        }
    }
    if (matrix[3][0] != 0 || matrix[3][1] != 0 || matrix[3][2] != 0 || matrix[3][3] != 1
        || matrix.hasScale(1e-12) != Base::ScaleType::NoScaling) {
        throw Base::NotImplementedError("Native geometry requires a rigid placement");
    }
}
Base::BoundBox3d placedBounds(const Base::BoundBox3d& domain, const Base::Matrix4D& matrix)
{
    Base::BoundBox3d bounds;
    if (!domain.IsValid()) {
        return bounds;
    }
    for (int corner = 0; corner < 8; ++corner) {
        Base::Vector3d point(
            corner & 1 ? domain.MaxX : domain.MinX,
            corner & 2 ? domain.MaxY : domain.MinY,
            corner & 4 ? domain.MaxZ : domain.MinZ
        );
        placePoint(matrix, point);
        bounds.Add(point);
    }
    return bounds;
}
class NativeSegment: public Data::Segment
{
public:
    Implicit::NativeBoundaryPtr owner;
    TopoDS_Shape shape;
    std::string name;
    std::string getName() const override
    {
        return name;
    }
};
void boundaryLines(
    const TopoDS_Shape& shape,
    std::vector<Base::Vector3d>& points,
    std::vector<Data::ComplexGeoData::Line>& lines
)
{
    NCollection_IndexedMap<TopoDS_Shape, TopTools_ShapeMapHasher> edges;
    TopExp::MapShapes(shape, TopAbs_EDGE, edges);
    for (const auto& edge : edges) {
        TopLoc_Location location;
        double first, last;
        const auto curve = occ::down_cast<Geom_BSplineCurve>(
            BRep_Tool::Curve(TopoDS::Edge(edge), location, first, last)
        );
        if (curve.IsNull() || curve->Degree() != 1) {
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
const NativeSegment& checkedSegment(const Data::Segment* value, const Implicit::NativeBoundaryPtr& owner)
{
    const auto* segment = dynamic_cast<const NativeSegment*>(value);
    if (!segment || segment->owner != owner) {
        throw Base::ValueError("Missing or foreign native geometry subelement");
    }
    return *segment;
}
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
TYPESYSTEM_SOURCE(Implicit::NativeElementGeometry, Implicit::NativeGeometry)
TYPESYSTEM_SOURCE(Implicit::NativePlacedGeometry, Implicit::NativeGeometry)
PROPERTY_SOURCE(Implicit::NativeFeature, App::GeoFeature)

NativePlacedGeometry::NativePlacedGeometry(const NativeGeometry& source, const Base::Matrix4D& matrix)
    : placement(matrix)
{
    requireRigid(matrix);
    setBoundary(source.boundary);
}
NativeRegionQuery NativeGeometry::classifyRegion(const Base::Vector3d& point, double tolerance) const
{
    if (!boundary) {
        throw Base::ValueError("Cannot classify an empty native geometry snapshot");
    }
    if (!std::isfinite(tolerance) || tolerance <= 0 || !std::isfinite(point.x)
        || !std::isfinite(point.y) || !std::isfinite(point.z)) {
        throw Base::ValueError("Classification requires finite coordinates and positive tolerance");
    }
    NativeRegionQuery result;
    try {
        result.classification = BRepClass3d_ImplicitBox::Classify(
            *boundary,
            gp_Pnt(point.x, point.y, point.z),
            tolerance
        );
    }
    catch (const Standard_Failure& error) {
        throw Base::ValueError(error.what());
    }
    return result;
}
NativeRegionQuery NativeElementGeometry::classifyRegion(const Base::Vector3d&, double) const
{
    throw Base::NotImplementedError(
        "A selected boundary element is not a region; extract the whole native object"
    );
}
NativeRegionQuery NativePlacedGeometry::classifyRegion(const Base::Vector3d& point, double tolerance) const
{
    using Ops = BRepClass3d_ImplicitBox;
    if (!boundary || !std::isfinite(tolerance) || tolerance <= 0 || !std::isfinite(point.x)
        || !std::isfinite(point.y) || !std::isfinite(point.z)) {
        throw Base::ValueError(
            "Classification requires native geometry, finite coordinates and positive tolerance"
        );
    }
    auto inverse = placement;
    inverse.inverse();
    Base::Vector3d local = point;
    placePoint(inverse, local);
    auto returned = local;
    placePoint(placement, returned);
    const auto domain = NativeGeometry::getBoundBox();
    const double extent[3] = {
        std::max(std::abs(domain.MinX), std::abs(domain.MaxX)),
        std::max(std::abs(domain.MinY), std::abs(domain.MaxY)),
        std::max(std::abs(domain.MinZ), std::abs(domain.MaxZ))
    };
    // Residual bounds the computed inverse's backward error. The reserve
    // also covers forward transformation of any witness in the finite domain.
    long double magnitude = 1, residual = 0;
    for (int row = 0; row < 3; ++row) {
        residual += std::abs(static_cast<long double>(returned[row]) - point[row]);
        magnitude += std::abs(static_cast<long double>(point[row])) + std::abs(placement[row][3]);
        for (int column = 0; column < 3; ++column) {
            magnitude += std::abs(static_cast<long double>(placement[row][column]))
                * (std::abs(static_cast<long double>(local[column])) + extent[column]);
        }
    }
    constexpr double epsilon = std::numeric_limits<double>::epsilon();
    NativeRegionQuery result;
    const long double error = residual + 128 * epsilon * magnitude;
    result.placementErrorBound = error < std::numeric_limits<double>::max()
        ? std::nextafter(static_cast<double>(error), std::numeric_limits<double>::infinity())
        : std::numeric_limits<double>::max();
    // Preserve the kernel's tolerance/256 root-bracket policy after both
    // endpoint transforms. Reserve 4*256 errors, keeping >= half the query
    // tolerance for local numerical work instead of requesting tiny brackets.
    if (error * 2048 >= tolerance) {
        result.placementResolved = false;
        return result;
    }
    // Gershgorin bound on M^T M, including a floating-point reserve. Even an
    // accepted near-rigid matrix must not silently assume unit stretch.
    double deviation = 0;
    for (int row = 0; row < 3; ++row) {
        double sum = 512 * epsilon;
        for (int column = 0; column < 3; ++column) {
            double gram = 0;
            for (int axis = 0; axis < 3; ++axis) {
                gram += placement[axis][row] * placement[axis][column];
            }
            sum += std::abs(gram - (row == column ? 1 : 0));
        }
        deviation = std::max(deviation, sum);
    }
    if (deviation >= .01) {
        throw Base::NotImplementedError("Native classification requires a numerically rigid placement");
    }
    const double minimumStretch = std::sqrt(1 - deviation) - 64 * epsilon;
    const double maximumStretch = std::sqrt(1 + deviation) + 64 * epsilon;
    const double allowed = (tolerance - 1024 * result.placementErrorBound) / maximumStretch;
    auto localResult = NativeGeometry::classifyRegion(local, allowed);
    auto& query = localResult.classification;
    query.DistanceLowerBound
        = std::max(0., minimumStretch * query.DistanceLowerBound - result.placementErrorBound);
    if ((query.State == Ops::PointState::Inside || query.State == Ops::PointState::Outside)
        && query.DistanceLowerBound <= tolerance) {
        query.State = Ops::PointState::Unresolved;
    }
    if (query.HasBoundaryWitness) {
        query.WitnessDistanceUpperBound = maximumStretch * query.WitnessDistanceUpperBound
            + result.placementErrorBound;
        query.WitnessBracketWidth = query.WitnessBracketWidth == 0
            ? 0
            : maximumStretch * query.WitnessBracketWidth + 2 * result.placementErrorBound;
        if (query.WitnessDistanceUpperBound > tolerance
            || query.WitnessBracketWidth > tolerance / 256) {
            query = {};
        }
        else {
            for (auto* witness : {&query.WitnessFirst, &query.WitnessLast}) {
                Base::Vector3d coordinates(witness->X(), witness->Y(), witness->Z());
                placePoint(placement, coordinates);
                witness->SetCoord(coordinates.x, coordinates.y, coordinates.z);
            }
        }
    }
    result.classification = query;
    return result;
}
Base::BoundBox3d NativePlacedGeometry::getBoundBox() const
{
    return placedBounds(NativeGeometry::getBoundBox(), placement);
}
void NativePlacedGeometry::getLines(
    std::vector<Base::Vector3d>& points,
    std::vector<Line>& lines,
    double accuracy,
    uint16_t flags
) const
{
    const auto start = points.size();
    NativeGeometry::getLines(points, lines, accuracy, flags);
    for (size_t i = start; i < points.size(); ++i) {
        placePoint(placement, points[i]);
    }
}
void NativePlacedGeometry::getLinesFromSubElement(
    const Data::Segment* selected,
    std::vector<Base::Vector3d>& points,
    std::vector<Line>& lines
) const
{
    const auto start = points.size();
    NativeGeometry::getLinesFromSubElement(selected, points, lines);
    for (size_t i = start; i < points.size(); ++i) {
        placePoint(placement, points[i]);
    }
}
bool NativePlacedGeometry::getFirstVertexFromSubElement(
    const Data::Segment* selected,
    Base::Vector3d& point
) const
{
    if (!NativeGeometry::getFirstVertexFromSubElement(selected, point)) {
        return false;
    }
    placePoint(placement, point);
    return true;
}

NativeElementGeometry::NativeElementGeometry(
    const NativeGeometry& source,
    const char* name,
    const Base::Matrix4D& matrix
)
    : placement(matrix)
{
    // Only rigid, orientation-preserving placements are qualified here. Do
    // not carry an unchanged millimetre tolerance through a scale/shear.
    requireRigid(matrix);
    boundary = source.boundary;
    element.reset(source.getSubElementByName(name));
    ensureElementMap();
    const auto identity = source.getElementName(name);
    setElementName(Data::IndexedName("Element", 1), identity.name, 0);
}
std::vector<const char*> NativeElementGeometry::getElementTypes() const
{
    return {"Element"};
}
unsigned long NativeElementGeometry::countSubElements(const char* type) const
{
    return element && std::strcmp(type, "Element") == 0 ? 1 : 0;
}
Data::Segment* NativeElementGeometry::getSubElement(const char* type, unsigned long index) const
{
    if (index != 1 || countSubElements(type) != 1) {
        throw Base::ValueError("Unknown native selected subelement");
    }
    const auto& selected = checkedSegment(element.get(), boundary);
    auto result = std::make_unique<NativeSegment>();
    result->owner = selected.owner;
    result->shape = selected.shape;
    result->name = "Element1";
    return result.release();
}
void NativeElementGeometry::getLines(
    std::vector<Base::Vector3d>& points,
    std::vector<Line>& lines,
    double,
    uint16_t
) const
{
    getLinesFromSubElement(element.get(), points, lines);
}
void NativeElementGeometry::getLinesFromSubElement(
    const Data::Segment* selected,
    std::vector<Base::Vector3d>& points,
    std::vector<Line>& lines
) const
{
    const auto& shape = checkedSegment(selected, boundary).shape;
    if (!shape.IsSame(checkedSegment(element.get(), boundary).shape)) {
        throw Base::ValueError("Foreign native selected subelement");
    }
    const auto start = points.size();
    boundaryLines(shape, points, lines);
    for (size_t index = start; index < points.size(); ++index) {
        placePoint(placement, points[index]);
    }
}
bool NativeElementGeometry::getFirstVertexFromSubElement(
    const Data::Segment* selected,
    Base::Vector3d& point
) const
{
    if (!checkedSegment(selected, boundary).shape.IsSame(checkedSegment(element.get(), boundary).shape)) {
        throw Base::ValueError("Foreign native selected subelement");
    }
    if (!NativeGeometry::getFirstVertexFromSubElement(selected, point)) {
        return false;
    }
    placePoint(placement, point);
    return true;
}
Base::BoundBox3d NativeElementGeometry::getBoundBox() const
{
    Base::BoundBox3d bounds;
    if (!element) {
        return bounds;
    }
    if (checkedSegment(element.get(), boundary).shape.ShapeType() == TopAbs_FACE
        && checkedSegment(element.get(), boundary).shape.IsSame(boundary->Faces.back())) {
        // Trim lines alone need not enclose the implicit surface's extrema.
        return placedBounds(NativeGeometry::getBoundBox(), placement);
    }
    else {
        std::vector<Base::Vector3d> points;
        std::vector<Line> lines;
        getLines(points, lines, 0);
        for (const auto& point : points) {
            bounds.Add(point);
        }
    }
    return bounds;
}

void NativeGeometry::setBoundary(NativeBoundaryPtr next)
{
    // Conservative whole-snapshot identity: unchanged topology survives I/O
    // and copying; changed topology MUST NOT silently reuse indexed names.
    auto names = std::make_shared<Data::ElementMap>();
    if (next) {
        std::ostringstream output;
        writeBoundary(*next, output);
        const auto bytes = output.str();
        const auto digest = QCryptographicHash::hash(
                                QByteArray(bytes.data(), qsizetype(bytes.size())),
                                QCryptographicHash::Sha256
        )
                                .toHex();
        const std::string prefix = "ImplicitV1_" + digest.toStdString() + ":";
        for (const auto* type : {"NativeFace", "Cap", "Seam"}) {
            const size_t count = std::strcmp(type, "NativeFace") == 0 ? 1
                : std::strcmp(type, "Cap") == 0                       ? next->Faces.size() - 1
                                                                      : next->SeamCount;
            for (size_t index = 1; index <= count; ++index) {
                const auto name = prefix + type + std::to_string(index);
                names->setElementName(
                    Data::IndexedName(type, int(index)),
                    Data::MappedName(name.c_str()),
                    0
                );
            }
        }
    }
    boundary = std::move(next);
    resetElementMap(std::move(names));
}

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
Data::Segment* NativeGeometry::getSubElement(const char* type, unsigned long index) const
{
    // One-based names, consistently with conventional FreeCAD Face1/Edge1.
    if (index == 0 || index > countSubElements(type)) {
        throw Base::ValueError("Unknown native geometry subelement");
    }
    auto result = std::make_unique<NativeSegment>();
    result->owner = boundary;
    result->name = std::string(type) + std::to_string(index);
    if (std::strcmp(type, "NativeFace") == 0) {
        result->shape = boundary->Faces.back();
    }
    else if (std::strcmp(type, "Cap") == 0) {
        result->shape = boundary->Faces.at(index - 1);
    }
    else {
        NCollection_IndexedMap<TopoDS_Shape, TopTools_ShapeMapHasher> edges;
        TopExp::MapShapes(boundary->Faces.back(), TopAbs_EDGE, edges);
        result->shape = edges.FindKey(int(index));
    }
    return result.release();
}
Data::Segment* NativeGeometry::getSubElementByName(const char* name) const
{
    if (!name) {
        throw Base::ValueError("Missing native subelement name");
    }
    const auto mapped = getElementName(name);
    if (!mapped.index) {
        throw Base::ValueError("Missing or stale native subelement reference");
    }
    return getSubElement(mapped.index.getType(), mapped.index.getIndex());
}
void NativeGeometry::getLinesFromSubElement(
    const Data::Segment* segment,
    std::vector<Base::Vector3d>& points,
    std::vector<Line>& lines
) const
{
    boundaryLines(checkedSegment(segment, boundary).shape, points, lines);
}
bool NativeGeometry::getFirstVertexFromSubElement(const Data::Segment* segment, Base::Vector3d& point) const
{
    const auto& shape = checkedSegment(segment, boundary).shape;
    TopExp_Explorer vertices(shape, TopAbs_VERTEX);
    if (!vertices.More()) {
        return false;
    }
    const auto p = BRep_Tool::Pnt(TopoDS::Vertex(vertices.Current()));
    point = Base::Vector3d(p.X(), p.Y(), p.Z());
    return true;
}
void NativeGeometry::getFacesFromSubElement(
    const Data::Segment* segment,
    std::vector<Base::Vector3d>&,
    std::vector<Base::Vector3d>&,
    std::vector<Facet>&
) const
{
    checkedSegment(segment, boundary);
    throw Base::NotImplementedError("Native subelement surface meshing is not implemented");
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
    boundaryLines(boundary->Shape, points, lines);
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
    NativeGeometry next;
    next.setBoundary(std::move(value));  // Validate/map before property mutation.
    aboutToSetValue();
    data.boundary = std::move(next.boundary);
    data.resetElementMap(next.elementMap());
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
    result->data.setBoundary(data.boundary);
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
App::DocumentObject* NativeFeature::getSubObject(
    const char* name,
    PyObject** pyObject,
    Base::Matrix4D* matrix,
    bool transform,
    int depth
) const
{
    if (!name || !*name) {
        Base::Matrix4D placed = matrix ? *matrix : Base::Matrix4D();
        auto* owner = App::GeoFeature::getSubObject(name, pyObject, &placed, transform, depth);
        if (owner == this && pyObject && !*pyObject && !Geometry.isNull()) {
            auto snapshot = std::make_unique<NativePlacedGeometry>(
                *static_cast<const NativeGeometry*>(Geometry.getComplexData()),
                placed
            );
            *pyObject = new Data::ComplexGeoDataPy(snapshot.get());
            snapshot.release();
        }
        if (matrix) {
            *matrix = placed;
        }
        return owner;
    }
    if (std::strchr(name, '.') && !Data::isMappedElement(name)) {
        return App::GeoFeature::getSubObject(name, pyObject, matrix, transform, depth);
    }
    const auto* geometry = Geometry.getComplexData();
    try {
        std::unique_ptr<Data::Segment> segment(geometry->getSubElementByName(name));
    }
    catch (const Base::ValueError&) {
        return nullptr;
    }
    Base::Matrix4D placed = matrix ? *matrix : Base::Matrix4D();
    if (transform) {
        placed *= Placement.getValue().toMatrix();
    }
    if (pyObject) {
        auto selected = std::make_unique<NativeElementGeometry>(
            *static_cast<const NativeGeometry*>(geometry),
            name,
            placed
        );
        *pyObject = new Data::ComplexGeoDataPy(selected.get());
        selected.release();  // Wrapper owns the reference-counted snapshot.
    }
    if (matrix) {
        *matrix = placed;
    }
    return const_cast<NativeFeature*>(this);
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
