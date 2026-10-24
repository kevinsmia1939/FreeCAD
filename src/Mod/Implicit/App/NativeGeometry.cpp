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
#include <BRepClass3d_ImplicitSolidIO.hxx>
#include <BRep_TImplicitFace.hxx>
#include <BRep_Tool.hxx>
#include <Geom_BSplineCurve.hxx>
#include <TopExp.hxx>
#include <TopExp_Explorer.hxx>
#include <TopoDS.hxx>
#include <TopoDS_Edge.hxx>
#include <TopoDS_Vertex.hxx>
#include <NCollection_IndexedMap.hxx>
#include <TopTools_ShapeMapHasher.hxx>
#include <Python.h>
#include <QCryptographicHash>
#include <cstring>
#include <cmath>
#include <sstream>
#include <limits>
#include <algorithm>

namespace
{
constexpr const char* capsuleName = "ImplicitOCCT.HybridBoundary.v1";
constexpr const char* solidCapsuleName = "ImplicitOCCT.NativeSolids.v1";
using ShapeMap = NCollection_IndexedMap<TopoDS_Shape, TopTools_ShapeMapHasher>;
void indexTopology(const TopoDS_Shape& shape, ShapeMap& edges, ShapeMap& vertices)
{
    TopExp::MapShapes(shape, TopAbs_EDGE, edges);
    // Face/wire orientation can alter recursive vertex visitation after I/O.
    // Edge order and forward curve endpoints are preserved by the native codec.
    for (const auto& edge : edges) {
        TopoDS_Vertex first, last;
        TopExp::Vertices(TopoDS::Edge(edge.Oriented(TopAbs_FORWARD)), first, last);
        if (first.IsNull() || last.IsNull()) {
            throw Base::ValueError("Native edge is missing a topological endpoint");
        }
        vertices.Add(first);
        vertices.Add(last);
    }
}
void seamTopology(const Implicit::NativeGeometry& geometry, ShapeMap& edges)
{
    if (geometry.solids) {
        for (const auto& face : geometry.solids->Boundary.Faces) {
            if (BRep_Tool::IsImplicit(face)) {
                TopExp::MapShapes(face, TopAbs_EDGE, edges);
            }
        }
    }
    else if (geometry.boundary) {
        TopExp::MapShapes(geometry.boundary->Faces.back(), TopAbs_EDGE, edges);
    }
}
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
    if (shape.ShapeType() == TopAbs_VERTEX) {
        const auto p = BRep_Tool::Pnt(TopoDS::Vertex(shape));
        points.emplace_back(p.X(), p.Y(), p.Z());
        return;
    }
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
void destroySolid(PyObject* capsule)
{
    if (PyCapsule_IsValid(capsule, solidCapsuleName)) {
        delete static_cast<Implicit::NativeSolid*>(PyCapsule_GetPointer(capsule, solidCapsuleName));
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
Implicit::NativeSolidPtr readSolid(std::istream& input)
{
    auto value = std::make_shared<Implicit::NativeSolid>();
    try {
        BRepClass3d_ImplicitSolidIO::Read(input, *value);
    }
    catch (const Standard_Failure& error) {
        throw Base::ValueError(error.what());
    }
    return value;
}
void writeSolid(const Implicit::NativeSolid& value, std::ostream& output)
{
    try {
        BRepClass3d_ImplicitSolidIO::Write(value, output);
    }
    catch (const Standard_Failure& error) {
        throw Base::ValueError(error.what());
    }
}
Base::BoundBox3d fieldBounds(const TopoDS_Face& face)
{
    const auto data = occ::down_cast<BRep_TImplicitFace>(face.TShape());
    const auto a = data->Minimum(), b = data->Maximum();
    return Base::BoundBox3d(a.X(), a.Y(), a.Z(), b.X(), b.Y(), b.Z());
}
}  // namespace

namespace Implicit
{
TYPESYSTEM_SOURCE(Implicit::NativeGeometry, Data::ComplexGeoData)
TYPESYSTEM_SOURCE(Implicit::PropertyNativeGeometry, App::PropertyComplexGeoData)
TYPESYSTEM_SOURCE(Implicit::PropertyNativeSolidGeometry, Implicit::PropertyNativeGeometry)
TYPESYSTEM_SOURCE(Implicit::NativeElementGeometry, Implicit::NativeGeometry)
TYPESYSTEM_SOURCE(Implicit::NativePlacedGeometry, Implicit::NativeGeometry)
PROPERTY_SOURCE(Implicit::NativeFeatureBase, App::GeoFeature)
PROPERTY_SOURCE(Implicit::NativeFeature, Implicit::NativeFeatureBase)
PROPERTY_SOURCE(Implicit::NativeSolidFeature, Implicit::NativeFeatureBase)

NativePlacedGeometry::NativePlacedGeometry(const NativeGeometry& source, const Base::Matrix4D& matrix)
    : placement(matrix)
{
    requireRigid(matrix);
    if (source.solidKind) {
        setSolids(source.solids);
    }
    else {
        setBoundary(source.boundary);
    }
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
    const auto domain = fieldBounds(boundary->Faces.back());
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
    solids = source.solids;
    solidKind = source.solidKind;
    element.reset(source.getSubElementByName(name));
    ensureElementMap();
    const auto identity = source.getElementName(name);
    setElementName(Data::IndexedName("Element", 1), identity.name, 0);
}
std::vector<const char*> NativeElementGeometry::getElementTypes() const
{
    return {"Element"};
}
std::vector<Base::Vector3d> NativeElementGeometry::snapPoints(
    const char* mode, const Base::Vector3d& cursor, double coordinateTolerance
) const
{
    const bool endpoint = std::strcmp(mode, "Endpoint") == 0;
    const bool midpoint = std::strcmp(mode, "Midpoint") == 0;
    const bool near = std::strcmp(mode, "Near") == 0;
    if (!endpoint && !midpoint && !near) {
        throw Base::ValueError("Native snapping supports Endpoint, Midpoint and Near");
    }
    if (!std::isfinite(coordinateTolerance) || coordinateTolerance <= 0
        || !std::isfinite(cursor.x) || !std::isfinite(cursor.y) || !std::isfinite(cursor.z)) {
        throw Base::ValueError("Native snapping requires finite coordinates and positive coordinate tolerance");
    }
    const auto& shape = checkedSegment(element.get(), boundary).shape;
    if (shape.ShapeType() != TopAbs_VERTEX && shape.ShapeType() != TopAbs_EDGE) {
        return {}; // No mesh triangle, untrimmed surface or whole-region fallback.
    }
    // These are picks on stored topology, not a new implicit-surface accuracy
    // certificate. Refuse coordinate scales which cannot resolve the requested
    // model-length precision. Work locally to avoid subtracting large offsets
    // when measuring an edge's length or projecting to its finite segments.
    const auto domain = fieldBounds(boundary->Faces.back());
    const double extent[] = {std::max(std::abs(domain.MinX), std::abs(domain.MaxX)),
                             std::max(std::abs(domain.MinY), std::abs(domain.MaxY)),
                             std::max(std::abs(domain.MinZ), std::abs(domain.MaxZ))};
    long double magnitude = 1;
    for (int row = 0; row < 3; ++row) {
        magnitude += std::abs(static_cast<long double>(placement[row][3]));
        if (near) {
            magnitude += std::abs(static_cast<long double>(cursor[row]));
        }
        for (int column = 0; column < 3; ++column) {
            magnitude += std::abs(static_cast<long double>(placement[row][column])) * extent[column];
        }
    }
    if (512 * std::numeric_limits<double>::epsilon() * magnitude >= coordinateTolerance) {
        throw Base::ValueError("Native snap coordinate precision is exhausted");
    }
    std::vector<Base::Vector3d> result;
    if (endpoint) {
        const auto append = [&](const TopoDS_Vertex& vertex) {
            const auto p = BRep_Tool::Pnt(vertex);
            result.emplace_back(p.X(), p.Y(), p.Z());
        };
        if (shape.ShapeType() == TopAbs_VERTEX) {
            append(TopoDS::Vertex(shape));
        }
        else {
            TopoDS_Vertex first, last;
            TopExp::Vertices(TopoDS::Edge(shape), first, last, true);
            append(first);
            if (!first.IsSame(last)) {
                append(last);
            }
        }
    }
    else if (shape.ShapeType() == TopAbs_EDGE) {
        std::vector<Base::Vector3d> points;
        std::vector<Line> lines;
        boundaryLines(shape, points, lines);
        long double length = 0;
        for (const auto& line : lines) {
            length += (points[line.I2] - points[line.I1]).Length();
        }
        if (!std::isfinite(length) || length <= 0) {
            throw Base::ValueError("Native snap edge has no finite length");
        }
        if (midpoint) {
            long double remaining = length / 2;
            for (const auto& line : lines) {
                const auto delta = points[line.I2] - points[line.I1];
                const double size = delta.Length();
                if (size > 0 && remaining <= size) {
                    result.push_back(points[line.I1] + delta * static_cast<double>(remaining / size));
                    break;
                }
                remaining -= size;
            }
        }
        else {
            auto inverse = placement;
            inverse.inverse();
            auto local = cursor;
            placePoint(inverse, local);
            double best = std::numeric_limits<double>::infinity();
            Base::Vector3d candidate;
            for (const auto& line : lines) {
                const auto& a = points[line.I1];
                const auto delta = points[line.I2] - a;
                const double squared = delta.Sqr();
                if (squared <= 0) {
                    continue;
                }
                const double parameter = std::clamp((local - a).Dot(delta) / squared, 0., 1.);
                const auto projected = a + delta * parameter;
                const double distance = (local - projected).Sqr();
                if (distance < best) {
                    best = distance;
                    candidate = projected;
                }
            }
            if (!std::isfinite(best)) {
                throw Base::ValueError("Native snap projection is unresolved");
            }
            result.push_back(candidate);
        }
    }
    for (auto& point : result) {
        placePoint(placement, point);
    }
    return result;
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
void NativeElementGeometry::getPoints(
    std::vector<Base::Vector3d>& points,
    std::vector<Base::Vector3d>&,
    double,
    uint16_t
) const
{
    if (!element || checkedSegment(element.get(), boundary).shape.ShapeType() != TopAbs_VERTEX) {
        throw Base::NotImplementedError("Native surface/edge point sampling is not implemented");
    }
    Base::Vector3d point;
    if (getFirstVertexFromSubElement(element.get(), point)) {
        points.push_back(point);
    }
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
    const auto& shape = checkedSegment(element.get(), boundary).shape;
    if (shape.ShapeType() == TopAbs_FACE && BRep_Tool::IsImplicit(TopoDS::Face(shape))) {
        // Trim lines alone need not enclose the implicit surface's extrema.
        return placedBounds(fieldBounds(TopoDS::Face(shape)), placement);
    }
    else {
        std::vector<Base::Vector3d> points;
        std::vector<Line> lines;
        getLines(points, lines, 0);
        for (const auto& point : points) {
            bounds.Add(point);
        }
        // A closed implicit component can have no wires at all. Whole shell/
        // solid bounds must also include every field face's actual domain.
        if (shape.ShapeType() == TopAbs_SHELL || shape.ShapeType() == TopAbs_SOLID) {
            for (TopExp_Explorer it(shape, TopAbs_FACE); it.More(); it.Next()) {
                const auto face = TopoDS::Face(it.Current());
                if (BRep_Tool::IsImplicit(face)) {
                    bounds.Add(placedBounds(fieldBounds(face), placement));
                }
            }
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
        NCollection_IndexedMap<TopoDS_Shape, TopTools_ShapeMapHasher> edges, vertices;
        indexTopology(next->Shape, edges, vertices);
        for (const auto* type : {"NativeFace", "Cap", "Seam", "Edge", "Vertex"}) {
            const size_t count = std::strcmp(type, "NativeFace") == 0 ? 1
                : std::strcmp(type, "Cap") == 0                       ? next->Faces.size() - 1
                : std::strcmp(type, "Seam") == 0                      ? next->SeamCount
                : std::strcmp(type, "Edge") == 0                      ? edges.Size()
                                                                      : vertices.Size();
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
    solids.reset();
    solidKind = false;
    resetElementMap(std::move(names));
}

void NativeGeometry::setSolids(NativeSolidPtr next)
{
    NativeGeometry candidate;
    candidate.solidKind = true;
    candidate.solids = std::move(next);
    auto names = std::make_shared<Data::ElementMap>();
    if (candidate.solids) {
        candidate.boundary = NativeBoundaryPtr(candidate.solids, &candidate.solids->Boundary.Source);
        std::ostringstream output;
        writeSolid(*candidate.solids, output);
        const auto bytes = output.str();
        const auto digest = QCryptographicHash::hash(QByteArray(bytes.data(), qsizetype(bytes.size())),
                                                    QCryptographicHash::Sha256).toHex();
        const std::string prefix = "ImplicitSolidV1_" + digest.toStdString() + ":";
        for (const auto* type : candidate.getElementTypes()) {
            const auto count = candidate.countSubElements(type);
            for (unsigned long index = 1; index <= count; ++index) {
                const auto name = prefix + type + std::to_string(index);
                names->setElementName(Data::IndexedName(type, int(index)), Data::MappedName(name.c_str()), 0);
            }
        }
    }
    boundary = std::move(candidate.boundary);
    solids = std::move(candidate.solids);
    solidKind = true;
    resetElementMap(std::move(names));
}
const TopoDS_Shape& NativeGeometry::topology() const
{
    static const TopoDS_Shape empty;
    return solids ? static_cast<const TopoDS_Shape&>(solids->Shape)
                  : boundary ? static_cast<const TopoDS_Shape&>(boundary->Shape) : empty;
}

std::vector<const char*> NativeGeometry::getElementTypes() const
{
    if (solidKind) {
        return {"Solid", "Shell", "Face", "NativeFace", "Cap", "Seam", "Edge", "Vertex"};
    }
    return {"NativeFace", "Cap", "Seam", "Edge", "Vertex"};
}
unsigned long NativeGeometry::countSubElements(const char* type) const
{
    if (!boundary) {
        return 0;
    }
    if (solids) {
        if (std::strcmp(type, "Solid") == 0) {
            return solids->Solids.size();
        }
        if (std::strcmp(type, "Shell") == 0) {
            return solids->Boundary.Shells.size();
        }
        if (std::strcmp(type, "Face") == 0) {
            return solids->Boundary.Faces.size();
        }
        if (std::strcmp(type, "NativeFace") == 0 || std::strcmp(type, "Cap") == 0) {
            const bool implicit = std::strcmp(type, "NativeFace") == 0;
            return std::count_if(solids->Boundary.Faces.begin(), solids->Boundary.Faces.end(),
                [implicit](const auto& face) { return BRep_Tool::IsImplicit(face) == implicit; });
        }
    }
    if (std::strcmp(type, "NativeFace") == 0) {
        return 1;
    }
    if (std::strcmp(type, "Cap") == 0) {
        return boundary->Faces.size() - 1;
    }
    if (std::strcmp(type, "Seam") == 0) {
        ShapeMap seams;
        seamTopology(*this, seams);
        return seams.Size();
    }
    if (std::strcmp(type, "Edge") == 0 || std::strcmp(type, "Vertex") == 0) {
        ShapeMap edges, vertices;
        indexTopology(topology(), edges, vertices);
        return std::strcmp(type, "Edge") == 0 ? edges.Size() : vertices.Size();
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
    if (solids && std::strcmp(type, "Solid") == 0) {
        result->shape = solids->Solids.at(index - 1);
    }
    else if (solids && std::strcmp(type, "Shell") == 0) {
        result->shape = solids->Boundary.Shells.at(index - 1);
    }
    else if (solids && std::strcmp(type, "Face") == 0) {
        result->shape = solids->Boundary.Faces.at(index - 1);
    }
    else if (solids && (std::strcmp(type, "NativeFace") == 0 || std::strcmp(type, "Cap") == 0)) {
        const bool implicit = std::strcmp(type, "NativeFace") == 0;
        unsigned long current = 0;
        for (const auto& face : solids->Boundary.Faces) {
            if (BRep_Tool::IsImplicit(face) == implicit && ++current == index) {
                result->shape = face;
                break;
            }
        }
    }
    else if (std::strcmp(type, "NativeFace") == 0) {
        result->shape = boundary->Faces.back();
    }
    else if (std::strcmp(type, "Cap") == 0) {
        result->shape = boundary->Faces.at(index - 1);
    }
    else if (std::strcmp(type, "Vertex") == 0) {
        ShapeMap edges, vertices;
        indexTopology(topology(), edges, vertices);
        result->shape = vertices.FindKey(int(index));
    }
    else {
        NCollection_IndexedMap<TopoDS_Shape, TopTools_ShapeMapHasher> shapes;
        if (std::strcmp(type, "Seam") == 0) {
            seamTopology(*this, shapes);
        }
        else {
            TopExp::MapShapes(topology(), TopAbs_EDGE, shapes);
        }
        result->shape = shapes.FindKey(int(index));
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
    if (solids) {
        Base::BoundBox3d result;
        for (const auto& face : solids->Boundary.Faces) {
            if (BRep_Tool::IsImplicit(face)) {
                result.Add(fieldBounds(face));
            }
            else {
                std::vector<Base::Vector3d> points;
                std::vector<Line> lines;
                boundaryLines(face, points, lines);
                for (const auto& p : points) {
                    result.Add(p);
                }
            }
        }
        return result;
    }
    return fieldBounds(boundary->Faces.back());
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
    boundaryLines(topology(), points, lines);
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
    if (getTypeId() != PropertyNativeGeometry::getClassTypeId()) {
        throw Base::TypeError("Use the representation-specific native solid setter");
    }
    NativeGeometry next;
    next.setBoundary(std::move(value));  // Validate/map before property mutation.
    aboutToSetValue();
    data.boundary = std::move(next.boundary);
    data.solids.reset();
    data.solidKind = false;
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
    if (from.getTypeId() != getTypeId()) {
        throw Base::TypeError("Native geometry property types cannot be converted implicitly");
    }
    setValue(dynamic_cast<const PropertyNativeGeometry&>(from).data.boundary);
}
unsigned int PropertyNativeGeometry::getMemSize() const
{
    return data.getMemSize();
}
void PropertyNativeGeometry::Save(Base::Writer& writer) const
{
    const auto tag = xmlTag();
    if (!data.boundary) {
        writer.Stream() << writer.ind() << "<" << tag << " schema=\"1\" empty=\"1\"/>\n";
    }
    else if (writer.isForceXML()) {
        writer.Stream() << writer.ind() << "<" << tag << " schema=\"1\" inline=\"1\">\n";
        writeNative(writer.beginCharStream(Base::CharStreamFormat::Base64Encoded));
        writer.endCharStream() << writer.ind() << "</" << tag << ">\n";
    }
    else {
        writer.Stream() << writer.ind() << "<" << tag << " schema=\"1\" file=\""
                        << writer.addFile(getFileName(fileSuffix()).c_str(), this) << "\"/>\n";
    }
}
void PropertyNativeGeometry::Restore(Base::XMLReader& reader)
{
    reader.readElement(xmlTag());
    if (reader.getAttribute<int>("schema") != 1) {
        throw Base::ValueError("Unsupported native geometry property schema");
    }
    if (reader.getAttribute<int>("empty", 0)) {
        setPyObject(Py_None);
        return;
    }
    if (reader.getAttribute<int>("inline", 0)) {
        auto& input = reader.beginCharStream(Base::CharStreamFormat::Base64Encoded);
        auto pending = emptyProperty();
        try {
            pending->readNative(input);
        }
        catch (...) {
            reader.endCharStream();
            throw;
        }
        reader.endCharStream();
        Paste(*pending);
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
        writeNative(writer.Stream());
    }
}
void PropertyNativeGeometry::RestoreDocFile(Base::Reader& reader)
{
    readNative(reader);
}
void PropertyNativeGeometry::writeNative(std::ostream& output) const
{
    writeBoundary(*data.boundary, output);
}
void PropertyNativeGeometry::readNative(std::istream& input)
{
    setValue(readBoundary(input));
}
std::unique_ptr<PropertyNativeGeometry> PropertyNativeGeometry::emptyProperty() const
{
    return std::make_unique<PropertyNativeGeometry>();
}
PropertyNativeSolidGeometry::PropertyNativeSolidGeometry()
{
    data.setSolids(nullptr);
}
void PropertyNativeSolidGeometry::setValue(NativeSolidPtr value)
{
    NativeGeometry next;
    next.setSolids(std::move(value));
    aboutToSetValue();
    data.boundary = std::move(next.boundary);
    data.solids = std::move(next.solids);
    data.solidKind = true;
    data.resetElementMap(next.elementMap());
    hasSetValue();
}
PyObject* PropertyNativeSolidGeometry::getPyObject()
{
    if (!data.solids) {
        Py_RETURN_NONE;
    }
    auto owned = std::make_unique<NativeSolid>(*data.solids);
    auto* result = PyCapsule_New(owned.get(), solidCapsuleName, destroySolid);
    if (result) {
        owned.release();
    }
    return result;
}
void PropertyNativeSolidGeometry::setPyObject(PyObject* object)
{
    if (object == Py_None) {
        setValue(NativeSolidPtr());
        return;
    }
    if (PyCapsule_IsValid(object, solidCapsuleName)) {
        setValue(std::make_shared<const NativeSolid>(
            *static_cast<const NativeSolid*>(PyCapsule_GetPointer(object, solidCapsuleName))));
        return;
    }
    if (PyUnicode_Check(object)) {
        Py_ssize_t size;
        const char* text = PyUnicode_AsUTF8AndSize(object, &size);
        if (!text || size > 32 * 1024 * 1024) {
            throw Base::ValueError("Invalid native solid UTF-8 record or record exceeds 32 MiB");
        }
        std::istringstream input(std::string(text, size_t(size)));
        readNative(input);
        return;
    }
    throw Base::TypeError("Expected native solid topology, its explicit record or None; not a source boundary/Part shape");
}
App::Property* PropertyNativeSolidGeometry::Copy() const
{
    auto* result = new PropertyNativeSolidGeometry;
    result->data.setSolids(data.solids);
    return result;
}
void PropertyNativeSolidGeometry::Paste(const App::Property& from)
{
    if (from.getTypeId() != getTypeId()) {
        throw Base::TypeError("Native solid property types cannot be converted implicitly");
    }
    setValue(static_cast<const PropertyNativeSolidGeometry&>(from).data.solids);
}
void PropertyNativeSolidGeometry::writeNative(std::ostream& output) const
{
    writeSolid(*data.solids, output);
}
void PropertyNativeSolidGeometry::readNative(std::istream& input)
{
    setValue(readSolid(input));
}
std::unique_ptr<PropertyNativeGeometry> PropertyNativeSolidGeometry::emptyProperty() const
{
    return std::make_unique<PropertyNativeSolidGeometry>();
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
NativeSolidFeature::NativeSolidFeature()
{
    ADD_PROPERTY_TYPE(Geometry, (nullptr), "Native solid geometry", App::Prop_Output,
                      "Authoritative native solid topology; not a Part shape or source boundary");
}
const App::PropertyComplexGeoData* NativeSolidFeature::getPropertyOfGeometry() const
{
    return &Geometry;
}
const char* NativeFeatureBase::getViewProviderName() const
{
    return "Gui::ViewProviderGeometryPython";
}
App::DocumentObject* NativeFeatureBase::getSubObject(
    const char* name,
    PyObject** pyObject,
    Base::Matrix4D* matrix,
    bool transform,
    int depth
) const
{
    const auto* property = dynamic_cast<const PropertyNativeGeometry*>(getPropertyOfGeometry());
    if (!property) {
        return App::GeoFeature::getSubObject(name, pyObject, matrix, transform, depth);
    }
    if (!name || !*name) {
        Base::Matrix4D placed = matrix ? *matrix : Base::Matrix4D();
        auto* owner = App::GeoFeature::getSubObject(name, pyObject, &placed, transform, depth);
        if (owner == this && pyObject && !*pyObject && !property->isNull()) {
            auto snapshot = std::make_unique<NativePlacedGeometry>(
                *static_cast<const NativeGeometry*>(property->getComplexData()),
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
    const auto* geometry = property->getComplexData();
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
    return const_cast<NativeFeatureBase*>(this);
}
void NativeFeatureBase::onSettingDocument()
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
                    auto* property = const_cast<PropertyNativeGeometry*>(
                        dynamic_cast<const PropertyNativeGeometry*>(getPropertyOfGeometry()));
                    if (property && !property->isNull()) {
                        property->setPyObject(Py_None);
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
PROPERTY_SOURCE_TEMPLATE(Implicit::NativeSolidFeaturePython, Implicit::NativeSolidFeature)
template<>
PyObject* Implicit::NativeFeaturePython::getPyObject()
{
    if (PythonObject.is(Py::_None())) {
        PythonObject = Py::Object(new FeaturePythonPyT<GeoFeaturePy>(this), true);
    }
    return Py::new_reference_to(PythonObject);
}
template class ImplicitExport FeaturePythonT<Implicit::NativeFeature>;
template<>
PyObject* Implicit::NativeSolidFeaturePython::getPyObject()
{
    if (PythonObject.is(Py::_None())) {
        PythonObject = Py::Object(new FeaturePythonPyT<GeoFeaturePy>(this), true);
    }
    return Py::new_reference_to(PythonObject);
}
template class ImplicitExport FeaturePythonT<Implicit::NativeSolidFeature>;
}  // namespace App
