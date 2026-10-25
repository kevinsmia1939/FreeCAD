// SPDX-License-Identifier: LGPL-2.1-or-later
// Private OCCT 8-only binding. Import through the ABI-checking ImplicitOCCT facade.
#include <Python.h>
#include "NativeSolidJob.h"
#include "CheckedDisplay.h"
#include <BRep_Builder.hxx>
#include <BRep_Tool.hxx>
#include <BRep_ImplicitIO.hxx>
#include <BRep_ImplicitTool.hxx>
#include <BRep_ImplicitCylinderSection.hxx>
#include <BRep_ImplicitSphereOps.hxx>
#include <BRepClass3d_ImplicitBox.hxx>
#include <BRepClass3d_ImplicitBoxIO.hxx>
#include <BRepClass3d_ImplicitSolidIO.hxx>
#include <BRepMesh_ImplicitBoundary.hxx>
#include <BRep_TImplicitFace.hxx>
#include <BRep_TImplicitCylinderPatch.hxx>
#include <BRepTools.hxx>
#include <Geom_ImplicitSphere.hxx>
#include <Geom_ImplicitGyroid.hxx>
#include <Geom_BSplineCurve.hxx>
#include <TopExp.hxx>
#include <NCollection_IndexedMap.hxx>
#include <TopTools_ShapeMapHasher.hxx>
#include <Standard_DomainError.hxx>
#include <Standard_ConstructionError.hxx>
#include <Standard_NotImplemented.hxx>
#include <Standard_Version.hxx>
#include <TopoDS.hxx>
#include <TopoDS_Edge.hxx>
#include <TopoDS_Vertex.hxx>
#include <gp_Trsf.hxx>
#include <cmath>
#include <limits>
#include <memory>
#include <sstream>
#include <string>

namespace
{
constexpr const char* faceName = "ImplicitOCCT.NativeFace.v1";
constexpr const char* boundaryName = "ImplicitOCCT.HybridBoundary.v1";
constexpr const char* shellsName = "ImplicitOCCT.NativeShells.v1";
constexpr const char* solidsName = "ImplicitOCCT.NativeSolids.v1";

void destroySolids(PyObject* capsule)
{
    if (PyCapsule_IsValid(capsule, solidsName)) {
        delete static_cast<BRepClass3d_ImplicitBox::NativeSolids*>(
            PyCapsule_GetPointer(capsule, solidsName));
    }
}
void destroyShells(PyObject* capsule)
{
    if (PyCapsule_IsValid(capsule, shellsName)) {
        delete static_cast<BRepClass3d_ImplicitBox::NativeShells*>(
            PyCapsule_GetPointer(capsule, shellsName)
        );
    }
}
void destroyBoundary(PyObject* capsule)
{
    if (PyCapsule_IsValid(capsule, boundaryName)) {
        delete static_cast<BRepClass3d_ImplicitBox::Boundary*>(
            PyCapsule_GetPointer(capsule, boundaryName)
        );
    }
}
struct Decref
{
    void operator()(PyObject* p) const
    {
        Py_XDECREF(p);
    }
};
using Object = std::unique_ptr<PyObject, Decref>;

void destroyFace(PyObject* capsule)
{
    if (PyCapsule_IsValid(capsule, faceName)) {
        delete static_cast<TopoDS_Face*>(PyCapsule_GetPointer(capsule, faceName));
    }
}

PyObject* ownFace(const TopoDS_Face& face)
{
    auto owned = std::make_unique<TopoDS_Face>(face);
    PyObject* result = PyCapsule_New(owned.get(), faceName, destroyFace);
    if (result) {
        owned.release();
    }
    return result;
}

const TopoDS_Face* getFace(PyObject* object)
{
    if (!PyCapsule_IsValid(object, faceName)) {
        PyErr_SetString(PyExc_TypeError, "expected an immutable ImplicitOCCT native-face handle");
        return nullptr;
    }
    return static_cast<const TopoDS_Face*>(PyCapsule_GetPointer(object, faceName));
}

bool point(PyObject* object, gp_Pnt& result)
{
    Object sequence(PySequence_Fast(object, "expected three coordinates"));
    if (!sequence) {
        return false;
    }
    if (PySequence_Fast_GET_SIZE(sequence.get()) != 3) {
        PyErr_SetString(PyExc_ValueError, "expected three coordinates");
        return false;
    }
    double xyz[3];
    for (int i = 0; i < 3; ++i) {
        xyz[i] = PyFloat_AsDouble(PySequence_Fast_GET_ITEM(sequence.get(), i));
        if (PyErr_Occurred()) {
            return false;
        }
        if (!std::isfinite(xyz[i])) {
            PyErr_SetString(PyExc_ValueError, "coordinates must be finite");
            return false;
        }
    }
    result.SetCoord(xyz[0], xyz[1], xyz[2]);
    return true;
}

PyObject* xyz(const gp_XYZ& p)
{
    return Py_BuildValue("(ddd)", p.X(), p.Y(), p.Z());
}
bool set(PyObject* dictionary, const char* key, PyObject* value)
{
    Object owned(value);
    return owned && PyDict_SetItemString(dictionary, key, owned.get()) == 0;
}

template<PyObject* (*Function)(PyObject*)>
PyObject* checked(PyObject*, PyObject* args)
{
    try {
        return Function(args);
    }
    catch (const Standard_NotImplemented& error) {
        PyErr_SetString(PyExc_NotImplementedError, error.what());
    }
    catch (const Standard_DomainError& error) {
        PyErr_SetString(PyExc_ValueError, error.what());
    }
    catch (const Standard_Failure& error) {
        PyErr_SetString(PyExc_RuntimeError, error.what());
    }
    catch (const std::bad_alloc&) {
        return PyErr_NoMemory();
    }
    catch (const std::exception& error) {
        PyErr_SetString(PyExc_RuntimeError, error.what());
    }
    catch (...) {
        PyErr_SetString(PyExc_RuntimeError, "unknown native implicit-face failure");
    }
    return nullptr;
}

PyObject* sphere(PyObject* args)
{
    PyObject* center;
    double radius, tolerance = .1;
    gp_Pnt p;
    if (!PyArg_ParseTuple(args, "Od|d", &center, &radius, &tolerance) || !point(center, p)) {
        return nullptr;
    }
    const double extent = radius + tolerance;
    TopoDS_Face result;
    BRep_Builder().MakeImplicitFace(
        result,
        new Geom_ImplicitSphere(p, radius),
        p.Translated(gp_Vec(-extent, -extent, -extent)),
        p.Translated(gp_Vec(extent, extent, extent)),
        TopLoc_Location(),
        tolerance
    );
    return ownFace(result);
}

PyObject* gyroid(PyObject* args)
{
    PyObject *minimum, *maximum;
    double period, iso, tolerance = .1;
    gp_Pnt a, b;
    if (!PyArg_ParseTuple(args, "ddOO|d", &period, &iso, &minimum, &maximum, &tolerance)
        || !point(minimum, a) || !point(maximum, b)) {
        return nullptr;
    }
    TopoDS_Face result;
    BRep_Builder().MakeImplicitFace(
        result,
        new Geom_ImplicitGyroid(period, iso),
        a,
        b,
        TopLoc_Location(),
        tolerance
    );
    return ownFace(result);
}

template<int Query>
PyObject* query(PyObject* args)
{
    PyObject *object, *coordinate;
    gp_Pnt p;
    if (!PyArg_ParseTuple(args, "OO", &object, &coordinate)) {
        return nullptr;
    }
    const auto* face = getFace(object);
    if (!face || !point(coordinate, p)) {
        return nullptr;
    }
    if constexpr (Query == 0) {
        return PyFloat_FromDouble(BRep_ImplicitTool::Value(*face, p));
    }
    if constexpr (Query == 1) {
        return xyz(BRep_ImplicitTool::Gradient(*face, p).XYZ());
    }
    if constexpr (Query == 2) {
        return xyz(BRep_ImplicitTool::Normal(*face, p).XYZ());
    }
    return PyBool_FromLong(BRep_ImplicitTool::IsInDomain(*face, p));
}

PyObject* restrictCylinderLocal(PyObject* args)
{
    PyObject *object, *origin, *axis, *direction;
    double radius, minimum, maximum;
    gp_Pnt p, n, x;
    if (!PyArg_ParseTuple(args, "OOOOd(dd)", &object, &origin, &axis, &direction,
        &radius, &minimum, &maximum)
        || !point(origin, p) || !point(axis, n) || !point(direction, x)) {
        return nullptr;
    }
    const auto* face = getFace(object);
    if (!face) {
        return nullptr;
    }
    gp_Ax2 frame;
    try {
        frame = gp_Ax2(p, gp_Dir(gp_Vec(n.XYZ())), gp_Dir(gp_Vec(x.XYZ())));
    }
    catch (const Standard_ConstructionError&) {
        throw Standard_DomainError("Cylinder axis and X direction must define a nondegenerate frame");
    }
    return ownFace(BRep_TImplicitCylinderPatch::Restrict(*face, frame, radius, minimum, maximum));
}

PyObject* info(PyObject* args)
{
    PyObject* object;
    if (!PyArg_ParseTuple(args, "O", &object)) {
        return nullptr;
    }
    const auto* face = getFace(object);
    if (!face) {
        return nullptr;
    }
    double x0, y0, z0, x1, y1, z1;
    BRep_ImplicitTool::Bounds(*face).Get(x0, y0, z0, x1, y1, z1);
    return Py_BuildValue(
        "{s:O,s:O,s:O,s:O,s:d,s:(ddd),s:(ddd)}",
        "is_implicit",
        BRep_Tool::IsImplicit(*face) ? Py_True : Py_False,
        "has_parametric_surface",
        BRep_Tool::HasParametricSurface(*face) ? Py_True : Py_False,
        "cylinder_restricted",
        dynamic_cast<const BRep_TImplicitCylinderPatch*>(face->TShape().get()) ? Py_True : Py_False,
        "solid_validated",
        Py_False,
        "tolerance",
        BRep_Tool::Tolerance(*face),
        "minimum",
        x0,
        y0,
        z0,
        "maximum",
        x1,
        y1,
        z1
    );
}

PyObject* ray(PyObject* args)
{
    PyObject *object, *origin, *direction;
    double first, last, tolerance = 0;
    int samples = 512;
    gp_Pnt p, d;
    if (
        !PyArg_ParseTuple(args, "OOOdd|id", &object, &origin, &direction, &first, &last, &samples, &tolerance)
    ) {
        return nullptr;
    }
    const auto* face = getFace(object);
    if (!face || !point(origin, p) || !point(direction, d)) {
        return nullptr;
    }
    const auto hits
        = BRep_ImplicitTool::IntersectRay(*face, p, gp_Vec(d.XYZ()), first, last, samples, tolerance);
    Object result(PyList_New(static_cast<Py_ssize_t>(hits.size())));
    if (!result) {
        return nullptr;
    }
    for (size_t i = 0; i < hits.size(); ++i) {
        const auto& hit = hits[i];
        auto* item = Py_BuildValue(
            "{s:d,s:(ddd),s:d,s:d}",
            "distance",
            hit.Distance,
            "point",
            hit.Point.X(),
            hit.Point.Y(),
            hit.Point.Z(),
            "residual",
            hit.Residual,
            "bracket_width",
            hit.BracketWidth
        );
        if (!item) {
            return nullptr;
        }
        PyList_SET_ITEM(result.get(), static_cast<Py_ssize_t>(i), item);
    }
    return result.release();
}

PyObject* dumps(PyObject* args)
{
    PyObject* object;
    if (!PyArg_ParseTuple(args, "O", &object)) {
        return nullptr;
    }
    const auto* face = getFace(object);
    if (!face) {
        return nullptr;
    }
    std::ostringstream output;
    BRep_ImplicitIO::Write(*face, output);  // Rejects trim subtypes/child topology before output.
    const std::string record = output.str();
    return PyUnicode_FromStringAndSize(record.data(), static_cast<Py_ssize_t>(record.size()));
}

PyObject* loads(PyObject* args)
{
    PyObject* object;
    if (!PyArg_ParseTuple(args, "U", &object)) {
        return nullptr;
    }
    Py_ssize_t size;
    const char* text = PyUnicode_AsUTF8AndSize(object, &size);
    if (!text) {
        return nullptr;
    }
    if (size > 65536) {
        PyErr_SetString(PyExc_ValueError, "native-face record exceeds 64 KiB");
        return nullptr;
    }
    std::istringstream input(std::string(text, static_cast<size_t>(size)));
    TopoDS_Face face;
    BRep_ImplicitIO::Read(input, face);
    return ownFace(face);
}

PyObject* translated(PyObject* args)
{
    PyObject *object, *offset;
    gp_Pnt d;
    if (!PyArg_ParseTuple(args, "OO", &object, &offset)) {
        return nullptr;
    }
    const auto* face = getFace(object);
    if (!face || !point(offset, d)) {
        return nullptr;
    }
    gp_Trsf transform;
    transform.SetTranslation(gp_Vec(d.XYZ()));
    const auto result = TopoDS::Face(face->Moved(TopLoc_Location(transform)));
    BRep_ImplicitTool::Bounds(result);  // Reject placement/domain overflow before publishing.
    return ownFace(result);
}

PyObject* trim(PyObject* args)
{
    PyObject *object, *normal;
    double offset;
    gp_Pnt n;
    if (!PyArg_ParseTuple(args, "OOd", &object, &normal, &offset)) {
        return nullptr;
    }
    const auto* face = getFace(object);
    if (!face || !point(normal, n)) {
        return nullptr;
    }
    if (!std::isfinite(offset)) {
        throw Standard_DomainError("plane offset must be finite");
    }
    const gp_Dir direction(n.XYZ());
    return ownFace(
        BRep_ImplicitSphereOps::Trim(*face, gp_Pln(gp_Pnt(direction.XYZ() * offset), direction))
    );
}

PyObject* booleanFaces(PyObject* args)
{
    PyObject *a, *b;
    const char* operation;
    if (!PyArg_ParseTuple(args, "OOs", &a, &b, &operation)) {
        return nullptr;
    }
    const auto *left = getFace(a), *right = getFace(b);
    if (!left || !right) {
        return nullptr;
    }
    using Ops = BRep_ImplicitSphereOps;
    Ops::Operation op;
    const std::string name(operation);
    if (name == "common") {
        op = Ops::Operation::Common;
    }
    else if (name == "fuse") {
        op = Ops::Operation::Fuse;
    }
    else if (name == "cut") {
        op = Ops::Operation::Cut;
    }
    else {
        throw Standard_DomainError("expected common, fuse or cut");
    }
    const auto boundary = Ops::Boolean(*left, *right, op);
    Object result(PyList_New(static_cast<Py_ssize_t>(boundary.Faces.size())));
    if (!result) {
        return nullptr;
    }
    for (size_t i = 0; i < boundary.Faces.size(); ++i) {
        Object face(ownFace(boundary.Faces[i]));
        Object source(PyLong_FromLong(boundary.Sources[i]));
        if (!face || !source) {
            return nullptr;
        }
        PyObject* pair = PyTuple_Pack(2, face.get(), source.get());
        if (!pair) {
            return nullptr;
        }
        PyList_SET_ITEM(result.get(), static_cast<Py_ssize_t>(i), pair);
    }
    return result.release();
}

PyObject* mesh(PyObject* args)
{
    PyObject* object;
    double tolerance = .1;
    if (!PyArg_ParseTuple(args, "O|d", &object, &tolerance)) {
        return nullptr;
    }
    const auto* face = getFace(object);
    if (!face) {
        return nullptr;
    }
    const auto data = BRep_ImplicitSphereOps::Tessellate(*face, tolerance);
    const auto& triangulation = data.Triangulation;
    TopLoc_Location location;
    BRep_Tool::ImplicitGeometry(*face, location);
    const auto transform = location.Transformation();
    Object vertices(PyList_New(triangulation->NbNodes()));
    Object normals(PyList_New(triangulation->NbNodes()));
    Object triangles(PyList_New(triangulation->NbTriangles()));
    Object result(PyDict_New());
    if (!vertices || !normals || !triangles || !result) {
        return nullptr;
    }
    for (int i = 1; i <= triangulation->NbNodes(); ++i) {
        const auto p = triangulation->Node(i).Transformed(transform);
        PyObject* vertex = xyz(p.XYZ());
        if (!vertex) {
            return nullptr;
        }
        PyList_SET_ITEM(vertices.get(), i - 1, vertex);
        PyObject* normal = xyz(BRep_ImplicitTool::Normal(*face, p).XYZ());
        if (!normal) {
            return nullptr;
        }
        PyList_SET_ITEM(normals.get(), i - 1, normal);
    }
    for (int i = 1; i <= triangulation->NbTriangles(); ++i) {
        int a, b, c;
        triangulation->Triangle(i).Get(a, b, c);
        if (transform.IsNegative()) {
            std::swap(b, c);
        }
        PyObject* triangle = Py_BuildValue("(iii)", a - 1, b - 1, c - 1);
        if (!triangle) {
            return nullptr;
        }
        PyList_SET_ITEM(triangles.get(), i - 1, triangle);
    }
    if (!set(result.get(), "vertices", vertices.release())
        || !set(result.get(), "normals", normals.release())
        || !set(result.get(), "triangles", triangles.release())
        || !set(result.get(), "geometric_bound", PyFloat_FromDouble(data.GeometricBound))) {
        return nullptr;
    }
    return result.release();
}

PyObject* boundaryResult(const BRepClass3d_ImplicitBox::Boundary& boundary);

PyObject* mixedBox(PyObject* args)
{
    PyObject *object, *record;
    const char* operation;
    const char* cornerPolicy = "reject";
    double tolerance = .1;
    int maximumCells = 512;
    if (!PyArg_ParseTuple(args, "OUs|dis", &object, &record, &operation, &tolerance, &maximumCells, &cornerPolicy)) {
        return nullptr;
    }
    const auto* face = getFace(object);
    if (!face) {
        return nullptr;
    }
    Py_ssize_t size;
    const char* text = PyUnicode_AsUTF8AndSize(record, &size);
    if (!text) {
        return nullptr;
    }
    if (size > 4 * 1024 * 1024) {
        throw Standard_DomainError("conventional box snapshot exceeds 4 MiB");
    }
    using Ops = BRepClass3d_ImplicitBox;
    const std::string policy(cornerPolicy);
    if (policy != "reject" && policy != "regularized") {
        throw Standard_DomainError("expected reject or regularized corner policy");
    }
    const std::string name(operation);
    if (name != "common" && name != "box_minus_field") {
        throw Standard_DomainError("expected common or box_minus_field; operand order is explicit");
    }
    std::istringstream input(std::string(text, static_cast<size_t>(size)));
    TopoDS_Shape box;
    BRepTools::Read(box, input, BRep_Builder());
    if (input.fail() || box.IsNull()) {
        throw Standard_DomainError("invalid conventional box B-Rep snapshot");
    }
    input >> std::ws;
    if (!input.eof()) {
        throw Standard_DomainError("trailing conventional box snapshot data");
    }
    const auto boundary = Ops::Build(
        *face,
        box,
        name == "common" ? Ops::Operation::Common : Ops::Operation::BoxMinusField,
        tolerance,
        maximumCells,
        policy == "regularized" ? Ops::CornerPolicy::Regularized : Ops::CornerPolicy::Reject
    );
    return boundaryResult(boundary);
}

PyObject* boundaryResult(const BRepClass3d_ImplicitBox::Boundary& boundary)
{
    using Ops = BRepClass3d_ImplicitBox;
    const auto geometry = occ::down_cast<BRep_TImplicitFace>(boundary.Faces.back().TShape());
    const auto gyroid = occ::down_cast<Geom_ImplicitGyroid>(geometry->Field());
    Object result(PyDict_New());
    Object caps(PyList_New(0)), sources(PyList_New(0)), sections(PyList_New(0));
    Object implicit;
    if (!result || !caps || !sources || !sections) {
        return nullptr;
    }
    for (size_t i = 0; i < boundary.Faces.size(); ++i) {
        if (boundary.Sources[i] == -1) {
            implicit.reset(ownFace(boundary.Faces[i]));
            if (!implicit) {
                return nullptr;
            }
        }
        else {
            std::ostringstream output;
            BRepTools::Write(boundary.Faces[i], output);
            const auto serialized = output.str();
            Object cap(PyUnicode_FromStringAndSize(serialized.data(), serialized.size()));
            Object source(PyLong_FromLong(boundary.Sources[i]));
            if (!cap || !source || PyList_Append(caps.get(), cap.get()) < 0
                || PyList_Append(sources.get(), source.get()) < 0) {
                return nullptr;
            }
        }
    }
    // Subelement indices follow the stored implicit wire graph, both before
    // and after I/O. Tracing section order is not a persistent seam identity.
    NCollection_IndexedMap<TopoDS_Shape, TopTools_ShapeMapHasher> edges;
    TopExp::MapShapes(boundary.Faces.back(), TopAbs_EDGE, edges);
    for (const auto& edge : edges) {
        TopLoc_Location location;
        double first, last;
        const auto curve = occ::down_cast<Geom_BSplineCurve>(
            BRep_Tool::Curve(TopoDS::Edge(edge), location, first, last)
        );
        Object points(PyList_New(curve->NbPoles()));
        if (!points) {
            return nullptr;
        }
        for (int i = 0; i < curve->NbPoles(); ++i) {
            auto* p = xyz(curve->Pole(i + 1).Transformed(location.Transformation()).XYZ());
            if (!p) {
                return nullptr;
            }
            PyList_SET_ITEM(points.get(), i, p);
        }
        if (PyList_Append(sections.get(), points.get()) < 0) {
            return nullptr;
        }
    }
    // Canonical whole-boundary identities, including conventional box edges.
    // Coordinates never weld unrelated vertices or invent vertices at poles.
    NCollection_IndexedMap<TopoDS_Shape, TopTools_ShapeMapHasher> allEdges, allVertices;
    TopExp::MapShapes(boundary.Shape, TopAbs_EDGE, allEdges);
    for (const auto& edge : allEdges) {
        TopoDS_Vertex first, last;
        TopExp::Vertices(TopoDS::Edge(edge.Oriented(TopAbs_FORWARD)), first, last);
        if (first.IsNull() || last.IsNull()) {
            throw Standard_DomainError("Native edge is missing a topological endpoint");
        }
        allVertices.Add(first);
        allVertices.Add(last);
    }
    Object edgePoints(PyList_New(0)), vertexPoints(PyList_New(0)),
        edgeVertices(PyList_New(0)), seamEdges(PyList_New(0));
    if (!edgePoints || !vertexPoints || !edgeVertices || !seamEdges) {
        return nullptr;
    }
    for (const auto& vertex : allVertices) {
        Object p(xyz(BRep_Tool::Pnt(TopoDS::Vertex(vertex)).XYZ()));
        if (!p || PyList_Append(vertexPoints.get(), p.get()) < 0) {
            return nullptr;
        }
    }
    for (const auto& shape : allEdges) {
        const auto edge = TopoDS::Edge(shape);
        TopoDS_Vertex firstVertex, lastVertex;
        TopExp::Vertices(TopoDS::Edge(edge.Oriented(TopAbs_FORWARD)), firstVertex, lastVertex);
        Object endpoints(Py_BuildValue("(ii)", allVertices.FindIndex(firstVertex) - 1,
                                        allVertices.FindIndex(lastVertex) - 1));
        TopLoc_Location location;
        double first, last;
        const auto curve = occ::down_cast<Geom_BSplineCurve>(BRep_Tool::Curve(edge, location, first, last));
        if (curve.IsNull() || curve->Degree() != 1) {
            throw Standard_NotImplemented("Unsupported native topology curve");
        }
        Object points(PyList_New(curve->NbPoles()));
        if (!points || !endpoints) {
            return nullptr;
        }
        for (int i = 0; i < curve->NbPoles(); ++i) {
            auto* point = xyz(curve->Pole(i + 1).Transformed(location.Transformation()).XYZ());
            if (!point) {
                return nullptr;
            }
            PyList_SET_ITEM(points.get(), i, point);
        }
        if (PyList_Append(edgePoints.get(), points.get()) < 0
            || PyList_Append(edgeVertices.get(), endpoints.get()) < 0) {
            return nullptr;
        }
    }
    for (const auto& seam : edges) {
        Object index(PyLong_FromLong(allEdges.FindIndex(seam) - 1));
        if (!index || PyList_Append(seamEdges.get(), index.get()) < 0) {
            return nullptr;
        }
    }
    if (!set(result.get(), "edge_points", edgePoints.release())
        || !set(result.get(), "vertex_points", vertexPoints.release())
        || !set(result.get(), "edge_vertices", edgeVertices.release())
        || !set(result.get(), "seam_edges", seamEdges.release())) {
        return nullptr;
    }
    Object contacts(PyList_New(boundary.ExcludedCornerContacts.size()));
    if (!contacts) {
        return nullptr;
    }
    for (size_t i = 0; i < boundary.ExcludedCornerContacts.size(); ++i) {
        auto* point = xyz(boundary.ExcludedCornerContacts[i].XYZ());
        if (!point) {
            return nullptr;
        }
        PyList_SET_ITEM(contacts.get(), i, point);
    }
    if (!set(result.get(), "corner_policy", PyUnicode_FromString(
            boundary.Policy == Ops::CornerPolicy::Regularized ? "regularized" : "reject"))
        || !set(result.get(), "exact_corner_count", PyLong_FromLong(boundary.ExactCornerCount))
        || !set(result.get(), "surface_domain_exclusion_count",
                PyLong_FromSize_t(geometry->ExcludedDomains().size()))
        || !set(result.get(), "corner_contour_ends", PyLong_FromLong(boundary.CornerContourEnds))
        || !set(result.get(), "planar_corner_contacts", PyLong_FromLong(boundary.PlanarCornerContacts))
        || !set(result.get(), "excluded_corner_contacts", contacts.release())) {
        return nullptr;
    }
    auto owned = std::make_unique<Ops::Boundary>(boundary);
    Object handle(PyCapsule_New(owned.get(), boundaryName, destroyBoundary));
    if (!handle) {
        return nullptr;
    }
    owned.release();
    if (!set(result.get(), "boundary_handle", handle.release())
        || !set(result.get(), "implicit_face", implicit.release())
        || !set(result.get(), "planar_caps_brep", caps.release())
        || !set(result.get(), "cap_sources", sources.release())
        || !set(result.get(), "seams", sections.release())
        || !set(result.get(), "seam_count", PyLong_FromLong(boundary.SeamCount))
        || !set(result.get(), "box_edge_root_count", PyLong_FromLong(boundary.BoxEdgeRootCount))
        || !set(result.get(), "seam_geometric_bound", PyFloat_FromDouble(boundary.GeometricBound))
        || !set(result.get(), "seam_bound_verified", PyBool_FromLong(boundary.SeamBoundVerified))
        || !set(result.get(), "period", PyFloat_FromDouble(gyroid->Period()))
        || !set(result.get(), "isovalue", PyFloat_FromDouble(gyroid->IsoValue()))
        || !set(
            result.get(),
            "operation",
            PyUnicode_FromString(
                boundary.Faces.back().Orientation() == TopAbs_FORWARD ? "common" : "box_minus_field"
            )
        )
        || !set(result.get(), "solid_validated", PyBool_FromLong(0))) {
        return nullptr;
    }
    return result.release();
}

PyObject* inspectMixed(PyObject* args)
{
    PyObject* object;
    if (!PyArg_ParseTuple(args, "O", &object)) {
        return nullptr;
    }
    if (!PyCapsule_IsValid(object, boundaryName)) {
        PyErr_SetString(PyExc_TypeError, "expected an immutable native hybrid-boundary handle");
        return nullptr;
    }
    return boundaryResult(*static_cast<const BRepClass3d_ImplicitBox::Boundary*>(
        PyCapsule_GetPointer(object, boundaryName)
    ));
}

PyObject* dumpMixed(PyObject* args)
{
    PyObject* object;
    if (!PyArg_ParseTuple(args, "O", &object)) {
        return nullptr;
    }
    if (!PyCapsule_IsValid(object, boundaryName)) {
        PyErr_SetString(PyExc_TypeError, "expected an immutable native hybrid-boundary handle");
        return nullptr;
    }
    const auto* boundary = static_cast<const BRepClass3d_ImplicitBox::Boundary*>(
        PyCapsule_GetPointer(object, boundaryName)
    );
    std::ostringstream output;
    BRepClass3d_ImplicitBoxIO::Write(*boundary, output);
    const auto record = output.str();
    return PyUnicode_FromStringAndSize(record.data(), record.size());
}

PyObject* loadMixed(PyObject* args)
{
    PyObject* object;
    if (!PyArg_ParseTuple(args, "U", &object)) {
        return nullptr;
    }
    Py_ssize_t size;
    const char* text = PyUnicode_AsUTF8AndSize(object, &size);
    if (!text) {
        return nullptr;
    }
    if (size > 16 * 1024 * 1024) {
        throw Standard_DomainError("native topology record exceeds 16 MiB");
    }
    std::istringstream input(std::string(text, static_cast<size_t>(size)));
    BRepClass3d_ImplicitBox::Boundary boundary;
    BRepClass3d_ImplicitBoxIO::Read(input, boundary);
    return boundaryResult(boundary);
}

template<int Context = 0>
PyObject* classifyMixed(PyObject* args)
{
    PyObject *object, *coordinate;
    double tolerance = .1;
    gp_Pnt p;
    if (!PyArg_ParseTuple(args, "OO|d", &object, &coordinate, &tolerance)) {
        return nullptr;
    }
    using Ops = BRepClass3d_ImplicitBox;
    const Ops::Boundary* boundary;
    bool validated = false;
    if constexpr (Context == 2) {
        if (!PyCapsule_IsValid(object, solidsName)) {
            PyErr_SetString(PyExc_TypeError, "expected an immutable native solid snapshot");
            return nullptr;
        }
        const auto* solids = static_cast<const Ops::NativeSolids*>(PyCapsule_GetPointer(object, solidsName));
        boundary = &solids->Boundary.Source;
        validated = solids->Validated;
    }
    else if constexpr (Context == 1) {
        if (!PyCapsule_IsValid(object, shellsName)) {
            PyErr_SetString(PyExc_TypeError, "expected an immutable native shell snapshot");
            return nullptr;
        }
        boundary = &static_cast<const Ops::NativeShells*>(PyCapsule_GetPointer(object, shellsName))->Source;
    }
    else {
        if (!PyCapsule_IsValid(object, boundaryName)) {
            PyErr_SetString(PyExc_TypeError, "expected an immutable native hybrid-boundary handle");
            return nullptr;
        }
        boundary = static_cast<const Ops::Boundary*>(PyCapsule_GetPointer(object, boundaryName));
    }
    if (!point(coordinate, p)) {
        return nullptr;
    }
    const auto query = Ops::Classify(*boundary, p, tolerance);
    const char* state = "unresolved";
    switch (query.State) {
        case Ops::PointState::Inside:
            state = "inside";
            break;
        case Ops::PointState::Outside:
            state = "outside";
            break;
        case Ops::PointState::NearBoundary:
            state = "near_boundary";
            break;
        case Ops::PointState::Unresolved:
            break;
    }
    Object result(Py_BuildValue(
        "{s:s,s:d,s:d,s:O,s:O}",
        "state",
        state,
        "distance_lower_bound",
        query.DistanceLowerBound,
        "distance_tolerance",
        tolerance,
        "has_boundary_witness",
        query.HasBoundaryWitness ? Py_True : Py_False,
        "solid_validated",
        validated ? Py_True : Py_False
    ));
    if (!result) {
        return nullptr;
    }
    if (!set(result.get(), "corner_policy", PyUnicode_FromString(
            boundary->Policy == Ops::CornerPolicy::Regularized ? "regularized" : "reject"))) {
        return nullptr;
    }
    if (query.HasBoundaryWitness) {
        if (
            !set(result.get(), "witness_first", xyz(query.WitnessFirst.XYZ()))
            || !set(result.get(), "witness_last", xyz(query.WitnessLast.XYZ()))
            || !set(
                result.get(),
                "witness_distance_upper_bound",
                PyFloat_FromDouble(query.WitnessDistanceUpperBound)
            )
            || !set(result.get(), "witness_bracket_width", PyFloat_FromDouble(query.WitnessBracketWidth))
        ) {
            return nullptr;
        }
    }
    return result.release();
}

template<bool Surface, bool CheckedDisplay>
PyObject* mixedMeshReport(const BRepClass3d_ImplicitBox::Boundary* boundary,
                          const BRepMesh_ImplicitBoundary::Result& mesh,
                          Object displayChecks, Object assignmentVertices);

PyObject* checkedMeshReport(const BRepClass3d_ImplicitBox::Boundary* boundary,
                           const BRepMesh_ImplicitBoundary::Result& mesh,
                           const Implicit::CheckedDisplay& checked, double deflection)
{
    Object assignmentVertices(PyList_New(checked.assignmentNodes.size()));
    if (!assignmentVertices) { return nullptr; }
    for (size_t i = 0; i < checked.assignmentNodes.size(); ++i) {
        auto* p = xyz(checked.assignmentNodes[i].XYZ());
        if (!p) { return nullptr; }
        PyList_SET_ITEM(assignmentVertices.get(), i, p);
    }
    const auto& coverage = checked.coverage;
    const auto& audit = checked.audit;
    const double uploadBound = checked.uploadBound;
    Object displayChecks(Py_BuildValue(
        "{s:O,s:O,s:O,s:O,s:d,s:d,s:d,s:d,s:K,s:K,s:K,s:K,s:s}",
        "boundary_proximity_resolved", Py_True, "triangle_contacts_clear", Py_True,
        "topology_validated", Py_False, "solid_validated", Py_False,
        "distance_tolerance", deflection, "upload_coordinate_bound", uploadBound,
        "boundary_to_mesh_bound", coverage.BoundaryToMeshBound + uploadBound,
        "mesh_to_boundary_bound", coverage.MeshToBoundaryBound + uploadBound,
        "spatial_cells", static_cast<unsigned long long>(coverage.SpatialCells),
        "triangle_patches", static_cast<unsigned long long>(coverage.TrianglePatches),
        "pair_tests", static_cast<unsigned long long>(audit.PairTests),
        "broad_tests", static_cast<unsigned long long>(audit.BroadTests),
        "coordinate_frame", "source_local_binary32"));
    if (!displayChecks) { return nullptr; }
    return mixedMeshReport<true, true>(boundary, mesh,
        std::move(displayChecks), std::move(assignmentVertices));
}

template<bool Surface, bool CheckedDisplay = false>
PyObject* prepareMixedMesh(PyObject* args)
{
    PyObject* object;
    double deflection = .1;
    int maximumNodes = 200000, maximumTriangles = 400000, maximumCells = 256;
    int depth = 14;
    unsigned long long spatial = 2000000, patches = 1000000, pairs = 2000000, broad = 50000000;
    const bool parsed = CheckedDisplay
        ? PyArg_ParseTuple(args, "O|diiiiKKKK", &object, &deflection, &maximumCells,
                           &maximumNodes, &maximumTriangles, &depth, &spatial, &patches, &pairs, &broad)
        : Surface
        ? PyArg_ParseTuple(args, "O|diii", &object, &deflection, &maximumCells, &maximumNodes, &maximumTriangles)
        : PyArg_ParseTuple(args, "O|dii", &object, &deflection, &maximumNodes, &maximumTriangles);
    if (!parsed) {
        return nullptr;
    }
    if (!PyCapsule_IsValid(object, boundaryName)) {
        PyErr_SetString(PyExc_TypeError, "expected an immutable native hybrid-boundary handle");
        return nullptr;
    }
    const auto* boundary = static_cast<const BRepClass3d_ImplicitBox::Boundary*>(
        PyCapsule_GetPointer(object, boundaryName)
    );
    if constexpr (CheckedDisplay) {
        if (depth < 1 || depth > 20 || !spatial || spatial > 10000000
            || !patches || patches > 4000000 || !pairs || pairs > 10000000
            || !broad || broad > 100000000) {
            throw Standard_DomainError("Invalid checked display budgets");
        }
    }
    auto mesh = Surface
        ? BRepMesh_ImplicitBoundary::Tessellate(
              *boundary,
              deflection,
              maximumCells,
              maximumNodes,
              maximumTriangles
          )
        : BRepMesh_ImplicitBoundary::Prepare(*boundary, deflection, maximumNodes, maximumTriangles);
    Object displayChecks, assignmentVertices;
    if constexpr (CheckedDisplay) {
        const auto checked = Implicit::checkDisplay(*boundary, mesh, deflection, depth,
            size_t(spatial), size_t(patches), size_t(pairs), size_t(broad));
        return checkedMeshReport(boundary, mesh, checked, deflection);
    }
    return mixedMeshReport<Surface, CheckedDisplay>(boundary, mesh,
        std::move(displayChecks), std::move(assignmentVertices));
}

template<bool Surface, bool CheckedDisplay>
PyObject* mixedMeshReport(const BRepClass3d_ImplicitBox::Boundary* boundary,
                          const BRepMesh_ImplicitBoundary::Result& mesh,
                          Object displayChecks, Object assignmentVertices)
{
    Object result(PyDict_New()), vertices(PyList_New(mesh.Nodes.size()));
    Object triangles(PyList_New(mesh.CapTriangles.size()));
    Object implicitTriangles(PyList_New(mesh.ImplicitTriangles.size()));
    if (!result || !vertices || !triangles || !implicitTriangles) {
        return nullptr;
    }
    if constexpr (CheckedDisplay) {
        if (!set(result.get(), "display_checks", displayChecks.release())
            || !set(result.get(), "assignment_vertices", assignmentVertices.release())) {
            return nullptr;
        }
    }
    for (size_t i = 0; i < mesh.Nodes.size(); ++i) {
        auto* vertex = xyz(mesh.Nodes[i].XYZ());
        if (!vertex) {
            return nullptr;
        }
        PyList_SET_ITEM(vertices.get(), i, vertex);
    }
    for (size_t i = 0; i < mesh.CapTriangles.size(); ++i) {
        const auto& t = mesh.CapTriangles[i];
        auto* triangle = Py_BuildValue("(iiii)", t.Nodes[0], t.Nodes[1], t.Nodes[2], t.Cap);
        if (!triangle) {
            return nullptr;
        }
        PyList_SET_ITEM(triangles.get(), i, triangle);
    }
    for (size_t i = 0; i < mesh.ImplicitTriangles.size(); ++i) {
        const auto& t = mesh.ImplicitTriangles[i];
        auto* triangle = Py_BuildValue("(iii)", t[0], t[1], t[2]);
        if (!triangle) {
            return nullptr;
        }
        PyList_SET_ITEM(implicitTriangles.get(), i, triangle);
    }
    if constexpr (Surface) {
        // Field normals smooth the display only. Cap normals remain separate
        // so the native cap/field boundary retains its actual sharp crease.
        std::vector<bool> used(mesh.Nodes.size(), false);
        for (const auto& triangle : mesh.ImplicitTriangles) {
            for (int index : triangle) {
                used.at(size_t(index)) = true;
            }
        }
        Object normals(PyList_New(mesh.Nodes.size()));
        if (!normals) {
            return nullptr;
        }
        for (size_t i = 0; i < mesh.Nodes.size(); ++i) {
            const gp_Vec n = used[i]
                ? BRep_ImplicitTool::Normal(boundary->Faces.back(), mesh.Nodes[i])
                : gp_Vec(0, 0, 0);
            auto* item = xyz(n.XYZ());
            if (!item) {
                return nullptr;
            }
            PyList_SET_ITEM(normals.get(), i, item);
        }
        if (!set(result.get(), "implicit_normals", normals.release())) {
            return nullptr;
        }
    }
    const auto indices = [](const std::vector<std::vector<int>>& paths) -> PyObject* {
        Object result(PyList_New(paths.size()));
        if (!result) {
            return nullptr;
        }
        for (size_t i = 0; i < paths.size(); ++i) {
            Object path(PyList_New(paths[i].size()));
            if (!path) {
                return nullptr;
            }
            for (size_t j = 0; j < paths[i].size(); ++j) {
                auto* index = PyLong_FromLong(paths[i][j]);
                if (!index) {
                    return nullptr;
                }
                PyList_SET_ITEM(path.get(), j, index);
            }
            PyList_SET_ITEM(result.get(), i, path.release());
        }
        return result.release();
    };
    if (!set(result.get(), "corner_policy", PyUnicode_FromString(
            mesh.Policy == BRepClass3d_ImplicitBox::CornerPolicy::Regularized ? "regularized" : "reject"))
        || !set(result.get(), "fixed_corner_count", PyLong_FromLong(mesh.FixedCornerCount))
        || !set(result.get(), "vertices", vertices.release())
        || !set(result.get(), "cap_triangles", triangles.release())
        || !set(result.get(), "implicit_triangles", implicitTriangles.release())
        || !set(result.get(), "seams", indices(mesh.Seams))
        || !set(result.get(), "wires", indices(mesh.Wires))
        || !set(result.get(), "seam_geometric_bound", PyFloat_FromDouble(mesh.SeamGeometricBound))
        || !set(result.get(), "seam_bound_verified", PyBool_FromLong(mesh.SeamBoundVerified))
        || !set(result.get(), "native_surface_meshed", PyBool_FromLong(mesh.NativeSurfaceMeshed))
        || !set(result.get(), "mesh_closed", PyBool_FromLong(mesh.MeshClosed))
        || !set(result.get(), "surface_coverage_verified", PyBool_FromLong(mesh.SurfaceCoverageVerified))
        || !set(result.get(), "field_distance_bound", PyFloat_FromDouble(mesh.FieldDistanceBound))
        || !set(result.get(), "cells", PyLong_FromLong(mesh.Cells))
        || !set(result.get(), "solid_validated", PyBool_FromLong(mesh.SolidValidated))) {
        return nullptr;
    }
    return result.release();
}

PyObject* auditMixedMesh(PyObject* args)
{
    PyObject* object;
    double tolerance = .1;
    int cells = 256;
    unsigned long long pairs = 2000000, broad = 50000000;
    if (!PyArg_ParseTuple(args, "O|diKK", &object, &tolerance, &cells, &pairs, &broad)) {
        return nullptr;
    }
    if (!PyCapsule_IsValid(object, boundaryName)) {
        PyErr_SetString(PyExc_TypeError, "expected an immutable native hybrid-boundary handle");
        return nullptr;
    }
    if (!pairs || pairs > 10000000 || !broad || broad > 100000000) {
        throw Standard_DomainError("Invalid native mesh audit budgets");
    }
    const auto* boundary = static_cast<const BRepClass3d_ImplicitBox::Boundary*>(
        PyCapsule_GetPointer(object, boundaryName)
    );
    const auto mesh = BRepMesh_ImplicitBoundary::Tessellate(*boundary, tolerance, cells);
    const auto audit = BRepMesh_ImplicitBoundary::Audit(mesh, size_t(pairs), size_t(broad));
    using State = BRepMesh_ImplicitBoundary::MeshAudit::State;
    const char* state = audit.Status == State::Clear ? "clear"
        : audit.Status == State::Contact             ? "contact_or_unresolved"
                                                     : "limit";
    return Py_BuildValue(
        "{s:s,s:O,s:O,s:O,s:i,s:i,s:K,s:K,s:K,s:K,s:d,s:i,s:K}",
        "state",
        state,
        "triangle_contacts_clear",
        audit.Status == State::Clear ? Py_True : Py_False,
        "surface_coverage_verified",
        Py_False,
        "solid_validated",
        Py_False,
        "first_triangle",
        audit.FirstTriangle,
        "second_triangle",
        audit.SecondTriangle,
        "pair_tests",
        static_cast<unsigned long long>(audit.PairTests),
        "broad_tests",
        static_cast<unsigned long long>(audit.BroadTests),
        "cap_triangle_count",
        static_cast<unsigned long long>(mesh.CapTriangles.size()),
        "implicit_triangle_count",
        static_cast<unsigned long long>(mesh.ImplicitTriangles.size()),
        "distance_tolerance",
        tolerance,
        "cells",
        mesh.Cells,
        "node_count",
        static_cast<unsigned long long>(mesh.Nodes.size())
    );
}

PyObject* checkMixedCoverage(PyObject* args)
{
    PyObject* object;
    double tolerance = .1;
    int cells = 256, depth = 14;
    unsigned long long spatial = 2000000, patches = 1000000;
    if (!PyArg_ParseTuple(args, "O|diiKK", &object, &tolerance, &cells, &depth, &spatial, &patches)) {
        return nullptr;
    }
    if (!PyCapsule_IsValid(object, boundaryName)) {
        PyErr_SetString(PyExc_TypeError, "expected an immutable native hybrid-boundary handle");
        return nullptr;
    }
    if (depth < 1 || depth > 20 || !spatial || spatial > 10000000 || !patches || patches > 4000000) {
        throw Standard_DomainError("Invalid clipped coverage budgets");
    }
    const auto* boundary = static_cast<const BRepClass3d_ImplicitBox::Boundary*>(
        PyCapsule_GetPointer(object, boundaryName)
    );
    const auto mesh = BRepMesh_ImplicitBoundary::Tessellate(*boundary, tolerance, cells);
    const auto report = BRepMesh_ImplicitBoundary::CheckCoverage(
        *boundary,
        mesh,
        tolerance,
        depth,
        size_t(spatial),
        size_t(patches)
    );
    Object result(Py_BuildValue(
        "{s:O,s:O,s:O,s:O,s:d,s:d,s:d,s:K,s:K,s:i,s:i,s:K,s:K,s:K,s:K}",
        "boundary_proximity_resolved",
        report.Resolved ? Py_True : Py_False,
        "topology_validated",
        Py_False,
        "solid_validated",
        Py_False,
        "contact_audit_performed",
        Py_False,
        "distance_tolerance",
        tolerance,
        "boundary_to_mesh_bound",
        report.BoundaryToMeshBound,
        "mesh_to_boundary_bound",
        report.MeshToBoundaryBound,
        "spatial_cells",
        static_cast<unsigned long long>(report.SpatialCells),
        "triangle_patches",
        static_cast<unsigned long long>(report.TrianglePatches),
        "cells",
        mesh.Cells,
        "unresolved_triangle",
        report.UnresolvedTriangle,
        "regularized_field_cells",
        static_cast<unsigned long long>(report.RegularizedFieldCells),
        "regularized_cap_cells",
        static_cast<unsigned long long>(report.RegularizedCapCells),
        "corner_witnesses",
        static_cast<unsigned long long>(report.CornerWitnesses),
        "exclusion_slab_rejections",
        static_cast<unsigned long long>(report.ExclusionSlabRejections)
    ));
    if (!result || !set(result.get(), "unresolved_minimum", xyz(report.UnresolvedMinimum.XYZ()))
        || !set(result.get(), "unresolved_maximum", xyz(report.UnresolvedMaximum.XYZ()))) {
        return nullptr;
    }
    return result.release();
}

PyObject* sectionResult(const BRep_ImplicitPlaneSection::Result& section, bool lattice);

template<bool Periodic, bool Boundary = false, bool Rings = false, bool Disks = false>
PyObject* traceGyroidCylinder(PyObject* args)
{
    PyObject *object, *origin, *axis, *direction;
    BRep_ImplicitCylinderSection::Settings settings;
    gp_Pnt p, n, x;
    if (!PyArg_ParseTuple(args, "OOOOd(dd)(dd)|di", &object, &origin, &axis, &direction,
        &settings.Radius, &settings.AngleMinimum, &settings.AngleMaximum,
        &settings.HeightMinimum, &settings.HeightMaximum,
        &settings.DistanceTolerance, &settings.MaximumCells)
        || !point(origin, p) || !point(axis, n) || !point(direction, x)) {
        return nullptr;
    }
    const auto* face = getFace(object);
    if (!face) {
        return nullptr;
    }
    try {
        settings.Frame = gp_Ax2(p, gp_Dir(gp_Vec(n.XYZ())), gp_Dir(gp_Vec(x.XYZ())));
    }
    catch (const Standard_ConstructionError&) {
        throw Standard_DomainError("Cylinder axis and X direction must define a nondegenerate frame");
    }
    BRep_ImplicitCylinderSection::BoundaryResult boundary;
    BRep_ImplicitCylinderSection::RingResult rings;
    BRep_ImplicitCylinderSection::DiskResult disks;
    const auto section = [&] {
        if constexpr (Disks) {
            disks = BRep_ImplicitCylinderSection::TraceEndCapDisks(*face, settings);
            boundary = disks.Boundary;
            return boundary.Section;
        }
        else if constexpr (Rings) {
            rings = BRep_ImplicitCylinderSection::BuildBoundaryRings(*face, settings);
            boundary = rings.Boundary;
            return boundary.Section;
        }
        else if constexpr (Boundary) {
            boundary = BRep_ImplicitCylinderSection::TracePeriodicBoundary(*face, settings);
            return boundary.Section;
        }
        return Periodic ? BRep_ImplicitCylinderSection::TracePeriodic(*face, settings)
                        : BRep_ImplicitCylinderSection::Trace(*face, settings);
    }();
    Object result(sectionResult(section, false));
    if (!result || !set(result.get(), "periodic", PyBool_FromLong(Periodic))) {
        return nullptr;
    }
    if constexpr (Boundary) {
        Object roots(PyList_New(0)), curveRoots(PyList_New(0));
        if (!roots || !curveRoots) {
            return nullptr;
        }
        for (size_t index = 0; index < boundary.Roots.size(); ++index) {
            const auto& root = boundary.Roots[index];
            Object item(Py_BuildValue("{s:K,s:i,s:(dd),s:d}",
                "id", static_cast<unsigned long long>(index + 1),
                "height_boundary", root.HeightBoundary,
                "angle_bracket", root.AngleFirst, root.AngleLast,
                "vertex_tolerance", BRep_Tool::Tolerance(root.Vertex)));
            if (!item || !set(item.get(), "point", xyz(BRep_Tool::Pnt(root.Vertex).XYZ()))
                || !set(item.get(), "first", xyz(root.First.XYZ()))
                || !set(item.get(), "last", xyz(root.Last.XYZ()))
                || PyList_Append(roots.get(), item.get()) < 0) {
                return nullptr;
            }
        }
        for (const auto& ends : boundary.CurveRoots) {
            Object item(Py_BuildValue("(KK)", static_cast<unsigned long long>(ends[0]),
                                      static_cast<unsigned long long>(ends[1])));
            if (!item || PyList_Append(curveRoots.get(), item.get()) < 0) {
                return nullptr;
            }
        }
        if (!set(result.get(), "boundary_roots", roots.release())
            || !set(result.get(), "curve_boundary_roots", curveRoots.release())
            || !set(result.get(), "boundary_incidence_verified",
                    PyBool_FromLong(boundary.BoundaryIncidenceVerified))) {
            return nullptr;
        }
    }
    if constexpr (Disks) {
        Object caps(PyList_New(0));
        if (!caps) {
            return nullptr;
        }
        for (int cap = 0; cap < 2; ++cap) {
            Object item(sectionResult(disks.Disks[cap], false)), roots(PyList_New(0));
            if (!item || !roots || PyDict_DelItemString(item.get(), "allow_exact_lattice_nodes") < 0) {
                return nullptr;
            }
            for (const auto& ends : disks.CurveRoots[cap]) {
                Object pair(Py_BuildValue("(KK)", static_cast<unsigned long long>(ends[0]),
                                          static_cast<unsigned long long>(ends[1])));
                if (!pair || PyList_Append(roots.get(), pair.get()) < 0) {
                    return nullptr;
                }
            }
            if (!set(item.get(), "curve_boundary_roots", roots.release())
                || PyList_Append(caps.get(), item.get()) < 0) {
                return nullptr;
            }
        }
        if (!set(result.get(), "disks", caps.release())
            || !set(result.get(), "disk_contours_verified", PyBool_FromLong(disks.Verified))) {
            return nullptr;
        }
    }
    if constexpr (Rings) {
        Object caps(PyList_New(0));
        if (!caps) {
            return nullptr;
        }
        for (const auto& ring : rings.Rings) {
            Object arcs(PyList_New(0));
            if (!arcs) {
                return nullptr;
            }
            for (const auto& arc : ring) {
                double first, last;
                const auto curve = BRep_Tool::Curve(arc.Edge, first, last);
                Object item(Py_BuildValue("{s:K,s:K,s:O,s:O,s:(dd),s:d}",
                    "lower_root", static_cast<unsigned long long>(arc.LowerRoot),
                    "upper_root", static_cast<unsigned long long>(arc.UpperRoot),
                    "negative", arc.Negative ? Py_True : Py_False,
                    "reversed", arc.Edge.Orientation() == TopAbs_REVERSED ? Py_True : Py_False,
                    "angle_range", first, last, "edge_tolerance", BRep_Tool::Tolerance(arc.Edge)));
                if (!item || !set(item.get(), "first", xyz(curve->Value(first).XYZ()))
                    || !set(item.get(), "last", xyz(curve->Value(last).XYZ()))
                    || PyList_Append(arcs.get(), item.get()) < 0) {
                    return nullptr;
                }
            }
            if (PyList_Append(caps.get(), arcs.get()) < 0) {
                return nullptr;
            }
        }
        if (!set(result.get(), "boundary_rings", caps.release())
            || !set(result.get(), "ring_edges_verified", PyBool_FromLong(rings.Verified))) {
            return nullptr;
        }
    }
    return result.release();
}

PyObject* traceGyroidPlane(PyObject* args)
{
    PyObject *object, *origin, *normal, *direction, *lattice = Py_False;
    BRep_ImplicitPlaneSection::Settings settings;
    gp_Pnt p, n, x;
    if (!PyArg_ParseTuple(args, "OOOO(dd)(dd)|diO", &object, &origin, &normal, &direction,
        &settings.UMinimum, &settings.UMaximum, &settings.VMinimum, &settings.VMaximum,
        &settings.DistanceTolerance, &settings.MaximumCells, &lattice)
        || !point(origin, p) || !point(normal, n) || !point(direction, x)) {
        return nullptr;
    }
    if (!PyBool_Check(lattice)) {
        PyErr_SetString(PyExc_TypeError, "allow_exact_lattice_nodes must be an explicit bool");
        return nullptr;
    }
    const auto* face = getFace(object);
    if (!face) {
        return nullptr;
    }
    settings.AllowExactLatticeNodes = lattice == Py_True;
    try {
        settings.Frame = gp_Ax2(p, gp_Dir(gp_Vec(n.XYZ())), gp_Dir(gp_Vec(x.XYZ())));
    }
    catch (const Standard_ConstructionError&) {
        throw Standard_DomainError("Section normal and X direction must define a finite nondegenerate plane frame");
    }
    const auto section = BRep_ImplicitPlaneSection::Trace(*face, settings);
    return sectionResult(section, settings.AllowExactLatticeNodes);
}

PyObject* sectionResult(const BRep_ImplicitPlaneSection::Result& section, bool lattice)
{
    Object result(Py_BuildValue("{s:O,s:i,s:i,s:i,s:i,s:i,s:d,s:d,s:d,s:i,s:O,s:O,s:O}",
        "resolved", section.Resolved ? Py_True : Py_False,
        "resolution", section.Resolution, "unresolved_cells", section.UnresolvedCells,
        "potential_critical_cells", section.PotentialCriticalCells,
        "ambiguous_cells", section.AmbiguousCells, "graph_defects", section.GraphDefects,
        "geometric_bound", section.GeometricBound, "maximum_residual", section.MaximumResidual,
        "maximum_root_bracket", section.MaximumRootBracket,
        "exact_lattice_node_count", section.ExactLatticeNodeCount,
        "allow_exact_lattice_nodes", lattice ? Py_True : Py_False,
        "topology_validated", Py_False, "solid_validated", Py_False));
    Object curves(PyList_New(0)), contacts(PyList_New(0));
    if (!result || !curves || !contacts) {
        return nullptr;
    }
    for (const auto& curve : section.Curves) {
        Object points(PyList_New(0));
        Object item(Py_BuildValue("{s:O}", "closed", curve.Closed ? Py_True : Py_False));
        if (!points || !item) {
            return nullptr;
        }
        for (const auto& p : curve.Points) {
            Object value(xyz(p.XYZ()));
            if (!value || PyList_Append(points.get(), value.get()) < 0) {
                return nullptr;
            }
        }
        if (!set(item.get(), "points", points.release()) || PyList_Append(curves.get(), item.get()) < 0) {
            return nullptr;
        }
    }
    for (const auto& p : section.PointContacts) {
        Object value(xyz(p.XYZ()));
        if (!value || PyList_Append(contacts.get(), value.get()) < 0) {
            return nullptr;
        }
    }
    if (!set(result.get(), "curves", curves.release()) || !set(result.get(), "point_contacts", contacts.release())) {
        return nullptr;
    }
    return result.release();
}

const char* cornerKind(BRepClass3d_ImplicitBox::CornerKind kind)
{
    using Kind = BRepClass3d_ImplicitBox::CornerKind;
    switch (kind) {
        case Kind::Positive: return "positive";
        case Kind::Negative: return "negative";
        case Kind::PositiveCone: return "positive_cone";
        case Kind::NegativeCone: return "negative_cone";
        case Kind::SplitCone: return "split_cone";
        default: return "unresolved";
    }
}

PyObject* checkBoxCorners(PyObject* args)
{
    PyObject* object;
    double radius = .1;
    if (!PyArg_ParseTuple(args, "O|d", &object, &radius)) {
        return nullptr;
    }
    const auto* face = getFace(object);
    if (!face) {
        return nullptr;
    }
    const auto report = BRepClass3d_ImplicitBox::CheckCornerGerms(*face, radius);
    Object result(Py_BuildValue("{s:O,s:i,s:i,s:d,s:d,s:O,s:O}",
        "corner_germs_resolved", report.Resolved ? Py_True : Py_False,
        "exact_zero_count", report.ExactZeroCount, "split_count", report.SplitCount,
        "coordinate_reserve", report.CoordinateReserve, "hessian_bound", report.HessianBound,
        "topology_validated", Py_False, "solid_validated", Py_False));
    Object corners(PyList_New(8));
    if (!result || !corners) {
        return nullptr;
    }
    for (size_t index = 0; index < report.Corners.size(); ++index) {
        const auto& corner = report.Corners[index];
        Object item(Py_BuildValue("{s:i,s:s,s:O,s:d,s:s}",
            "index", int(index), "kind", cornerKind(corner.Kind),
            "exact_zero", corner.ExactZero ? Py_True : Py_False,
            "radius", corner.Radius, "reason", corner.Reason.c_str()));
        if (!item || !set(item.get(), "anchor", xyz(corner.Anchor.XYZ()))
            || !set(item.get(), "minimum", xyz(corner.Minimum.XYZ()))
            || !set(item.get(), "maximum", xyz(corner.Maximum.XYZ()))
            || !set(item.get(), "inward_derivative_lower", Py_BuildValue("(ddd)",
                corner.InwardDerivativeLower[0], corner.InwardDerivativeLower[1], corner.InwardDerivativeLower[2]))
            || !set(item.get(), "inward_derivative_upper", Py_BuildValue("(ddd)",
                corner.InwardDerivativeUpper[0], corner.InwardDerivativeUpper[1], corner.InwardDerivativeUpper[2]))) {
            return nullptr;
        }
        PyList_SET_ITEM(corners.get(), Py_ssize_t(index), item.release());
    }
    if (!set(result.get(), "corners", corners.release())) {
        return nullptr;
    }
    return result.release();
}

PyObject* classifyBoxCorner(PyObject* args)
{
    PyObject *object, *coordinate;
    int index;
    const char* operation = "common";
    double radius = .1;
    gp_Pnt p;
    if (!PyArg_ParseTuple(args, "OiO|sd", &object, &index, &coordinate, &operation, &radius)
        || !point(coordinate, p)) {
        return nullptr;
    }
    const auto* face = getFace(object);
    if (!face) {
        return nullptr;
    }
    using Ops = BRepClass3d_ImplicitBox;
    const std::string name(operation);
    if (name != "common" && name != "box_minus_field") {
        throw Standard_DomainError("expected common or box_minus_field");
    }
    const auto query = Ops::ClassifyCornerGerm(*face, index, p,
        name == "common" ? Ops::Operation::Common : Ops::Operation::BoxMinusField, radius);
    return Py_BuildValue("{s:O,s:O,s:O,s:O,s:s,s:O}",
        "resolved", query.Resolved ? Py_True : Py_False,
        "on_field", query.OnField ? Py_True : Py_False,
        "closed_retained", query.ClosedRetained ? Py_True : Py_False,
        "regularized_retained", query.RegularizedRetained ? Py_True : Py_False,
        "reason", query.Reason.c_str(), "solid_validated", Py_False);
}

template<bool Mixed>
PyObject* checkBoxRegularity(PyObject* args)
{
    PyObject* object;
    int depth = 14;
    unsigned long long cells = 2000000;
    if (!PyArg_ParseTuple(args, "O|iK", &object, &depth, &cells)) {
        return nullptr;
    }
    if (!cells || cells > 10000000) {
        throw Standard_DomainError("Invalid box regularity cell budget");
    }
    const TopoDS_Face* face;
    if constexpr (Mixed) {
        if (!PyCapsule_IsValid(object, boundaryName)) {
            PyErr_SetString(PyExc_TypeError, "expected an immutable native hybrid-boundary handle");
            return nullptr;
        }
        face = &static_cast<const BRepClass3d_ImplicitBox::Boundary*>(
                    PyCapsule_GetPointer(object, boundaryName)
        )
                    ->Faces.back();
    }
    else {
        face = getFace(object);
        if (!face) {
            return nullptr;
        }
    }
    const auto report = BRepClass3d_ImplicitBox::CheckRegularity(*face, depth, size_t(cells));
    Object result(Py_BuildValue(
        "{s:O,s:O,s:O,s:O,s:d,s:i}",
        "field_box_regularity_resolved",
        report.Resolved ? Py_True : Py_False,
        "trim_correspondence_validated",
        Py_False,
        "topology_validated",
        Py_False,
        "solid_validated",
        Py_False,
        "hessian_bound",
        report.HessianBound,
        "unresolved_dimension",
        report.UnresolvedDimension
    ));
    Object strata(PyList_New(4));
    if (!result || !strata) {
        return nullptr;
    }
    for (size_t i = 0; i < 4; ++i) {
        auto* item = Py_BuildValue(
            "{s:i,s:O,s:K,s:K,s:K,s:d}",
            "dimension",
            int(i),
            "complete",
            report.Complete[i] ? Py_True : Py_False,
            "visited",
            static_cast<unsigned long long>(report.Visited[i]),
            "excluded",
            static_cast<unsigned long long>(report.Excluded[i]),
            "regular_cells",
            static_cast<unsigned long long>(report.RegularCells[i]),
            "minimum_projected_gradient",
            report.MinimumDerivative[i]
        );
        if (!item) {
            return nullptr;
        }
        PyList_SET_ITEM(strata.get(), i, item);
    }
    if (!set(result.get(), "strata", strata.release())
        || !set(result.get(), "unresolved_minimum", xyz(report.UnresolvedMinimum.XYZ()))
        || !set(result.get(), "unresolved_maximum", xyz(report.UnresolvedMaximum.XYZ()))) {
        return nullptr;
    }
    return result.release();
}

template<class Range, class Convert>
PyObject* convertedList(const Range& values, Convert convert)
{
    Object result(PyList_New(values.size()));
    if (!result) {
        return nullptr;
    }
    for (size_t i = 0; i < values.size(); ++i) {
        auto* value = convert(values[i]);
        if (!value) {
            return nullptr;
        }
        PyList_SET_ITEM(result.get(), i, value);
    }
    return result.release();
}

PyObject* nativeShellReport(const BRepClass3d_ImplicitBox::NativeShells& data)
{
    int regions = 0;
    int implicit = 0;
    for (const auto& face : data.Faces) {
        implicit += BRep_Tool::IsImplicit(face);
    }
    for (int region : data.ShellRegions) {
        regions = std::max(regions, region + 1);
    }
    Object result(Py_BuildValue(
        "{s:O,s:O,s:O,s:O,s:O,s:O,s:O,s:s,s:i,s:i,s:i,s:i,s:i,s:K}",
        "face_attachment_validated",
        data.FacesAttached ? Py_True : Py_False,
        "native_shell_constructed",
        data.ShellsConstructed ? Py_True : Py_False,
        "topology_validated",
        data.TopologyValidated ? Py_True : Py_False,
        "solid_validated",
        Py_False,
        "geometry_accuracy_verified",
        Py_False,
        "part_compatible",
        Py_False,
        "generic_brep_check_performed",
        Py_False,
        "reason",
        data.Reason.c_str(),
        "shell_count",
        int(data.Shells.size()),
        "face_count",
        int(data.Faces.size()),
        "implicit_face_count",
        implicit,
        "region_count",
        regions,
        "separator_count",
        data.Separators,
        "separator_cells",
        static_cast<unsigned long long>(data.SeparatorCells)
    ));
    if (!result) {
        return nullptr;
    }
    const auto integer = [](int value) {
        return PyLong_FromLong(value);
    };
    if (!set(result.get(), "reference_resolution", PyLong_FromLong(data.ReferenceResolution))
        || !set(result.get(), "corner_policy", PyUnicode_FromString(
            data.Source.Policy == BRepClass3d_ImplicitBox::CornerPolicy::Regularized
                ? "regularized" : "reject"))
        || !set(result.get(), "face_sources", convertedList(data.FaceSources, integer))
        || !set(result.get(), "face_components", convertedList(data.FaceComponents, integer))
        || !set(result.get(), "face_shells", convertedList(data.FaceShells, integer))
        || !set(result.get(), "shell_regions", convertedList(data.ShellRegions, integer))
        || !set(result.get(), "shell_euler", convertedList(data.ShellEuler, integer))
        || !set(result.get(), "component_domains", convertedList(data.ComponentDomains, [](const auto& box) {
                    return Py_BuildValue(
                        "((ddd)(ddd))",
                        box[0].X(),
                        box[0].Y(),
                        box[0].Z(),
                        box[1].X(),
                        box[1].Y(),
                        box[1].Z()
                    );
                }))) {
        return nullptr;
    }
    if (data.ShellsConstructed) {
        Object faces(PyList_New(0));
        if (!faces) {
            return nullptr;
        }
        for (size_t i = 0; i < data.Faces.size(); ++i) {
            if (data.FaceComponents[i] < 0) {
                continue;
            }
            Object face(ownFace(data.Faces[i]));
            if (!face || PyList_Append(faces.get(), face.get()) < 0) {
                return nullptr;
            }
        }
        if (!set(result.get(), "implicit_faces", faces.release())) {
            return nullptr;
        }
    }
    return result.release();
}

PyObject* buildMixedShells(PyObject* args)
{
    PyObject* object;
    int resolution = 32, depth = 16;
    unsigned long long cells = 4000000, tests = 2000000, separators = 2000000;
    if (!PyArg_ParseTuple(args, "O|iiKKK", &object, &resolution, &depth, &cells, &tests, &separators)) {
        return nullptr;
    }
    if (!PyCapsule_IsValid(object, boundaryName)) {
        PyErr_SetString(PyExc_TypeError, "expected an immutable native hybrid-boundary handle");
        return nullptr;
    }
    if (!cells || cells > 10000000 || !tests || tests > 10000000 || !separators
        || separators > 10000000) {
        throw Standard_DomainError("Invalid native shell build budgets");
    }
    const auto* source = static_cast<const BRepClass3d_ImplicitBox::Boundary*>(
        PyCapsule_GetPointer(object, boundaryName)
    );
    auto data = std::make_unique<BRepClass3d_ImplicitBox::NativeShells>(
        BRepClass3d_ImplicitBox::BuildNativeShells(
            *source,
            resolution,
            depth,
            size_t(cells),
            size_t(tests),
            size_t(separators)
        )
    );
    Object result(nativeShellReport(*data));
    if (!result) {
        return nullptr;
    }
    if (data->ShellsConstructed) {
        Object capsule(PyCapsule_New(data.get(), shellsName, destroyShells));
        if (!capsule) {
            return nullptr;
        }
        data.release();
        if (!set(result.get(), "shell_handle", capsule.release())) {
            return nullptr;
        }
    }
    return result.release();
}

PyObject* inspectMixedShells(PyObject* args)
{
    PyObject* object;
    if (!PyArg_ParseTuple(args, "O", &object)) {
        return nullptr;
    }
    if (!PyCapsule_IsValid(object, shellsName)) {
        PyErr_SetString(PyExc_TypeError, "expected an immutable native shell snapshot");
        return nullptr;
    }
    return nativeShellReport(*static_cast<const BRepClass3d_ImplicitBox::NativeShells*>(
        PyCapsule_GetPointer(object, shellsName)
    ));
}

PyObject* nativeSolidReport(const BRepClass3d_ImplicitBox::NativeSolids& data)
{
    Object result(nativeShellReport(data.Boundary));
    if (!result) {
        return nullptr;
    }
    // Alias actual component seams to actual result edges by native identity,
    // never by coordinate matching or the original source compound's order.
    NCollection_IndexedMap<TopoDS_Shape, TopTools_ShapeMapHasher> allEdges, seams;
    Object seamEdges(PyList_New(0));
    if (!seamEdges) {
        return nullptr;
    }
    if (data.Constructed) {
        TopExp::MapShapes(data.Shape, TopAbs_EDGE, allEdges);
        for (const auto& face : data.Boundary.Faces) {
            if (BRep_Tool::IsImplicit(face)) {
                TopExp::MapShapes(face, TopAbs_EDGE, seams);
            }
        }
        for (const auto& seam : seams) {
            const int index = allEdges.FindIndex(seam);
            if (!index) {
                throw Standard_DomainError("Native solid seam is missing from actual result edges");
            }
            Object value(PyLong_FromLong(index - 1));
            if (!value || PyList_Append(seamEdges.get(), value.get()) < 0) {
                return nullptr;
            }
        }
    }
    if (!set(result.get(), "seam_edges", seamEdges.release())) {
        return nullptr;
    }
    const auto& geometry = data.Geometry;
    Object report(Py_BuildValue(
        "{s:O,s:s,s:d,s:d,s:d,s:d,s:(KK),s:K,s:i,s:i}",
        "resolved", geometry.Resolved ? Py_True : Py_False,
        "reason", geometry.Reason.c_str(),
        "mathematical_to_caps_bound", geometry.MathematicalToCapsBound,
        "caps_to_mathematical_bound", geometry.CapsToMathematicalBound,
        "edge_vertex_deviation", geometry.EdgeVertexDeviation,
        "boundary_bound", geometry.BoundaryBound,
        "cells", static_cast<unsigned long long>(geometry.Cells[0]),
        static_cast<unsigned long long>(geometry.Cells[1]),
        "segment_tests", static_cast<unsigned long long>(geometry.SegmentTests),
        "unresolved_side", geometry.UnresolvedSide,
        "unresolved_direction", geometry.UnresolvedDirection));
    if (!report
        || !set(report.get(), "regularized_empty_cells", PyLong_FromSize_t(geometry.RegularizedEmptyCells))
        || !set(report.get(), "corner_witnesses", PyLong_FromSize_t(geometry.CornerWitnesses))
        || !set(report.get(), "unresolved_minimum", xyz(geometry.UnresolvedMinimum.XYZ()))
        || !set(report.get(), "unresolved_maximum", xyz(geometry.UnresolvedMaximum.XYZ()))
        || !set(result.get(), "geometry", report.release())
        || !set(result.get(), "reason", PyUnicode_FromString(data.Reason.c_str()))
        || !set(result.get(), "native_solid_constructed", PyBool_FromLong(data.Constructed))
        || !set(result.get(), "solid_validated", PyBool_FromLong(data.Validated))
        || !set(result.get(), "geometry_accuracy_verified", PyBool_FromLong(data.Geometry.Resolved))
        || !set(result.get(), "solid_count", PyLong_FromSize_t(data.Solids.size()))
        || !set(result.get(), "tolerance", PyFloat_FromDouble(data.Tolerance))
        || !set(result.get(), "maximum_stored_tolerance", PyFloat_FromDouble(data.MaximumStoredTolerance))
        || !set(result.get(), "validation_policy", PyUnicode_FromString(
            "restricted implicit-aware numerical topology and whole-boundary tolerance; not directed intervals"))) {
        return nullptr;
    }
    return result.release();
}

PyObject* checkMixedCapGeometry(PyObject* args)
{
    PyObject* object;
    double tolerance = .1;
    int depth = 16;
    unsigned long long cells = 2000000, segments = 8000000;
    if (!PyArg_ParseTuple(args, "O|diKK", &object, &tolerance, &depth, &cells, &segments)) {
        return nullptr;
    }
    if (!PyCapsule_IsValid(object, boundaryName)) {
        PyErr_SetString(PyExc_TypeError, "expected an immutable native hybrid-boundary handle");
        return nullptr;
    }
    if (!cells || cells > 10000000 || !segments || segments > 50000000) {
        throw Standard_DomainError("Invalid native cap geometry budgets");
    }
    using Ops = BRepClass3d_ImplicitBox;
    const auto& source = *static_cast<const Ops::Boundary*>(PyCapsule_GetPointer(object, boundaryName));
    if (source.Faces.empty()) {
        throw Standard_DomainError("Native cap geometry requires a stored boundary");
    }
    const std::vector<TopoDS_Face> caps(source.Faces.begin(), source.Faces.end() - 1);
    const auto report = Ops::CheckCapGeometry(source, caps, tolerance, depth, size_t(cells), size_t(segments));
    Object result(Py_BuildValue(
        "{s:O,s:s,s:d,s:d,s:d,s:d,s:(KK),s:K,s:K,s:K,s:i,s:i,s:O,s:O}",
        "cap_geometry_resolved", report.Resolved ? Py_True : Py_False,
        "reason", report.Reason.c_str(),
        "mathematical_to_caps_bound", report.MathematicalToCapsBound,
        "caps_to_mathematical_bound", report.CapsToMathematicalBound,
        "edge_vertex_deviation", report.EdgeVertexDeviation,
        "boundary_bound", report.BoundaryBound,
        "cells", static_cast<unsigned long long>(report.Cells[0]),
        static_cast<unsigned long long>(report.Cells[1]),
        "segment_tests", static_cast<unsigned long long>(report.SegmentTests),
        "regularized_empty_cells", static_cast<unsigned long long>(report.RegularizedEmptyCells),
        "corner_witnesses", static_cast<unsigned long long>(report.CornerWitnesses),
        "unresolved_side", report.UnresolvedSide,
        "unresolved_direction", report.UnresolvedDirection,
        "solid_validated", Py_False,
        "topology_validated", Py_False));
    if (!result
        || !set(result.get(), "corner_policy", PyUnicode_FromString(
            source.Policy == Ops::CornerPolicy::Regularized ? "regularized" : "reject"))
        || !set(result.get(), "unresolved_minimum", xyz(report.UnresolvedMinimum.XYZ()))
        || !set(result.get(), "unresolved_maximum", xyz(report.UnresolvedMaximum.XYZ()))) {
        return nullptr;
    }
    return result.release();
}

PyObject* buildMixedSolids(PyObject* args)
{
    PyObject* object;
    double tolerance = .1;
    int resolution = 32, depth = 16, geometryDepth = -1;
    unsigned long long cells = 4000000, tests = 2000000, separators = 2000000,
                       geometryCells = 2000000, segments = 8000000;
    if (!PyArg_ParseTuple(args, "O|diiKKKKKi", &object, &tolerance, &resolution, &depth,
                          &cells, &tests, &separators, &geometryCells, &segments, &geometryDepth)) {
        return nullptr;
    }
    if (!PyCapsule_IsValid(object, boundaryName)) {
        PyErr_SetString(PyExc_TypeError, "expected an immutable native hybrid-boundary handle");
        return nullptr;
    }
    if (!cells || cells > 10000000 || !tests || tests > 10000000
        || !separators || separators > 10000000 || !geometryCells || geometryCells > 10000000
        || !segments || segments > 50000000) {
        throw Standard_DomainError("Invalid native solid build budgets");
    }
    const auto* source = static_cast<const BRepClass3d_ImplicitBox::Boundary*>(
        PyCapsule_GetPointer(object, boundaryName));
    auto data = std::make_unique<BRepClass3d_ImplicitBox::NativeSolids>(
        BRepClass3d_ImplicitBox::BuildNativeSolids(*source, tolerance, resolution, depth,
            size_t(cells), size_t(tests), size_t(separators), size_t(geometryCells), size_t(segments),
            geometryDepth == -1 ? depth : geometryDepth));
    Object result(nativeSolidReport(*data));
    if (!result) {
        return nullptr;
    }
    if (data->Constructed && data->Validated) {
        Object capsule(PyCapsule_New(data.get(), solidsName, destroySolids));
        if (!capsule) {
            return nullptr;
        }
        data.release();
        if (!set(result.get(), "solid_handle", capsule.release())) {
            return nullptr;
        }
    }
    return result.release();
}

constexpr const char* solidJobName = "ImplicitOCCT.NativeSolidJob.v1";
using SolidJobPtr = std::shared_ptr<Implicit::NativeSolidJob>;

void destroySolidJob(PyObject* capsule)
{
    if (PyCapsule_IsValid(capsule, solidJobName)) {
        auto* job = static_cast<SolidJobPtr*>(PyCapsule_GetPointer(capsule, solidJobName));
        (*job)->cancel();
        delete job;
    }
}

SolidJobPtr readSolidJob(PyObject* args)
{
    PyObject* object;
    if (!PyArg_ParseTuple(args, "O", &object)) { return {}; }
    if (!PyCapsule_IsValid(object, solidJobName)) {
        PyErr_SetString(PyExc_TypeError, "expected a native geometry job handle");
        return {};
    }
    return *static_cast<SolidJobPtr*>(PyCapsule_GetPointer(object, solidJobName));
}

PyObject* ownNativeJob(Implicit::NativeSolidRequest request)
{
    auto job = std::make_unique<SolidJobPtr>(Implicit::submitNativeSolid(std::move(request)));
    PyObject* capsule = PyCapsule_New(job.get(), solidJobName, destroySolidJob);
    if (!capsule) {
        (*job)->cancel();
        return nullptr;
    }
    job.release();
    return capsule;
}

PyObject* submitNativeJob(PyObject* object, Implicit::NativeSolidRequest request)
{
    if (!PyCapsule_IsValid(object, boundaryName)) {
        PyErr_SetString(PyExc_TypeError, "expected an immutable native hybrid-boundary handle");
        return nullptr;
    }
    const auto* source = static_cast<const BRepClass3d_ImplicitBox::Boundary*>(
        PyCapsule_GetPointer(object, boundaryName));
    std::ostringstream output;
    BRepClass3d_ImplicitBoxIO::Write(*source, output);
    request.boundary = output.str();
    return ownNativeJob(std::move(request));
}

PyObject* startBoundaryJob(PyObject* args)
{
    PyObject *object, *record;
    const char *operation = "common", *policy = "reject";
    Implicit::NativeSolidRequest request;
    Implicit::NativeBoundaryRequest tracing;
    if (!PyArg_ParseTuple(args, "OU|sdis", &object, &record, &operation,
                         &request.tolerance, &tracing.cells, &policy)) { return nullptr; }
    const auto* field = getFace(object);
    if (!field) { return nullptr; }
    const std::string name(operation), corner(policy);
    if ((name != "common" && name != "box_minus_field")
        || (corner != "reject" && corner != "regularized")
        || !std::isfinite(request.tolerance) || request.tolerance <= 0
        || tracing.cells < 4 || tracing.cells > 512 || (tracing.cells & (tracing.cells - 1))) {
        throw Standard_DomainError("Invalid native boundary job settings");
    }
    Py_ssize_t size;
    const char* text = PyUnicode_AsUTF8AndSize(record, &size);
    if (!text) { return nullptr; }
    if (size > 4 * 1024 * 1024) {
        throw Standard_DomainError("Conventional box snapshot exceeds 4 MiB");
    }
    std::ostringstream output;
    BRep_ImplicitIO::Write(*field, output);
    tracing.field = output.str();
    if (tracing.field.size() > 65536) { throw Standard_DomainError("Native field snapshot exceeds 64 KiB"); }
    tracing.box.assign(text, size_t(size));
    tracing.common = name == "common";
    tracing.regularized = corner == "regularized";
    request.tracing = std::move(tracing);
    return ownNativeJob(std::move(request));
}

PyObject* startSurfaceJob(PyObject* args)
{
    PyObject* object;
    Implicit::NativeSolidRequest request;
    Implicit::NativeSurfaceRequest display;
    int checked = 0;
    unsigned long long spatial = display.spatial, patches = display.patches,
                       pairs = display.pairs, broad = display.broad;
    if (!PyArg_ParseTuple(args, "O|diiipiKKKK", &object, &request.tolerance,
            &display.cells, &display.nodes, &display.triangles, &checked, &display.depth,
            &spatial, &patches, &pairs, &broad)) { return nullptr; }
    if (!std::isfinite(request.tolerance) || request.tolerance < 1.e-7
        || display.cells < 8 || display.cells > 256 || display.nodes < 3 || display.nodes > 1000000
        || display.triangles < 1 || display.triangles > 2000000 || display.depth < 1 || display.depth > 20
        || !spatial || spatial > 10000000 || !patches || patches > 4000000
        || !pairs || pairs > 10000000 || !broad || broad > 100000000) {
        throw Standard_DomainError("Invalid native display job settings");
    }
    display.checked = bool(checked);
    display.spatial = size_t(spatial);
    display.patches = size_t(patches);
    display.pairs = size_t(pairs);
    display.broad = size_t(broad);
    request.display = display;
    return submitNativeJob(object, std::move(request));
}

PyObject* startSolidJob(PyObject* args)
{
    PyObject* object;
    Implicit::NativeSolidRequest request;
    unsigned long long cells = request.cells, tests = request.tests, separators = request.separators,
                       geometryCells = request.geometryCells, segments = request.segments;
    if (!PyArg_ParseTuple(args, "O|diiKKKKKi", &object, &request.tolerance, &request.resolution,
            &request.depth, &cells, &tests, &separators, &geometryCells, &segments, &request.geometryDepth)) {
        return nullptr;
    }
    if (!PyCapsule_IsValid(object, boundaryName)) {
        PyErr_SetString(PyExc_TypeError, "expected an immutable native hybrid-boundary handle");
        return nullptr;
    }
    if (!std::isfinite(request.tolerance) || request.tolerance <= 0
        || request.resolution < 4 || request.resolution > 64
        || (request.resolution & (request.resolution - 1)) || request.depth < 0 || request.depth > 16
        || (request.geometryDepth != -1 && (request.geometryDepth < 1 || request.geometryDepth > 24))
        || !cells || cells > 10000000 || !tests || tests > 10000000
        || !separators || separators > 10000000 || !geometryCells || geometryCells > 10000000
        || !segments || segments > 50000000) {
        throw Standard_DomainError("Invalid native solid job settings");
    }
    request.cells = size_t(cells);
    request.tests = size_t(tests);
    request.separators = size_t(separators);
    request.geometryCells = size_t(geometryCells);
    request.segments = size_t(segments);
    return submitNativeJob(object, std::move(request));
}

PyObject* solidJobStatus(PyObject* args)
{
    const auto job = readSolidJob(args);
    if (!job) { return nullptr; }
    const auto status = job->status();
    constexpr const char* states[] = {"queued", "running", "ready", "failed", "cancelled", "consumed"};
    constexpr const char* phases[] = {"copying", "topology", "cap_attachment", "trim_attachment",
                                     "shell_assembly", "geometry", "solid_assembly", "meshing",
                                     "coverage", "contact_audit"};
    const char* state = status.cancelling && status.state == Implicit::NativeSolidJob::State::Running
        ? "cancelling" : states[static_cast<int>(status.state)];
    return Py_BuildValue("{s:s,s:s,s:K,s:s}", "state", state,
        "phase", phases[static_cast<int>(status.phase)],
        "checkpoints", static_cast<unsigned long long>(status.checkpoints), "error", status.error.c_str());
}

PyObject* cancelSolidJob(PyObject* args)
{
    const auto job = readSolidJob(args);
    if (!job) { return nullptr; }
    job->cancel();
    Py_RETURN_NONE;
}

PyObject* takeSolidJob(PyObject* args)
{
    const auto job = readSolidJob(args);
    if (!job) { return nullptr; }
    if (job->isSurfaceJob() || job->isBoundaryJob()) {
        PyErr_SetString(PyExc_TypeError, "expected a solid-construction job");
        return nullptr;
    }
    auto data = job->take();
    Object result(nativeSolidReport(*data->solid));
    if (!result) { return nullptr; }
    Object surface(data->surface
        ? mixedMeshReport<true, false>(&data->solid->Boundary.Source, *data->surface, {}, {})
        : Py_NewRef(Py_None));
    if (!surface) { return nullptr; }
    const auto& input = data->request;
    Object settings(input.geometryDepth == -1
        ? Py_BuildValue("(diiKKKKK)", input.tolerance, input.resolution, input.depth,
            static_cast<unsigned long long>(input.cells), static_cast<unsigned long long>(input.tests),
            static_cast<unsigned long long>(input.separators), static_cast<unsigned long long>(input.geometryCells),
            static_cast<unsigned long long>(input.segments))
        : Py_BuildValue("(diiKKKKKi)", input.tolerance, input.resolution, input.depth,
            static_cast<unsigned long long>(input.cells), static_cast<unsigned long long>(input.tests),
            static_cast<unsigned long long>(input.separators), static_cast<unsigned long long>(input.geometryCells),
            static_cast<unsigned long long>(input.segments), input.geometryDepth));
    if (!settings
        || !set(result.get(), "input_settings", settings.release())
        || !set(result.get(), "input_record", PyUnicode_FromStringAndSize(
            input.boundary.data(), Py_ssize_t(input.boundary.size())))
        || !set(result.get(), "surface", surface.release())
        || !set(result.get(), "surface_error", PyUnicode_FromString(data->surfaceError.c_str()))) {
        return nullptr;
    }
    Object capsule(PyCapsule_New(data->solid.get(), solidsName, destroySolids));
    if (!capsule) { return nullptr; }
    data->solid.release();
    if (!set(result.get(), "solid_handle", capsule.release())) { return nullptr; }
    return result.release();
}

PyObject* takeSurfaceJob(PyObject* args)
{
    const auto job = readSolidJob(args);
    if (!job) { return nullptr; }
    if (!job->isSurfaceJob()) {
        PyErr_SetString(PyExc_TypeError, "expected a display job");
        return nullptr;
    }
    auto data = job->take();
    const auto& input = data->request;
    const auto& display = *input.display;
    Object surface(data->checks
        ? checkedMeshReport(data->surfaceSource.get(), *data->surface, *data->checks, input.tolerance)
        : mixedMeshReport<true, false>(data->surfaceSource.get(), *data->surface, {}, {}));
    if (!surface) { return nullptr; }
    Object settings(Py_BuildValue("(diiiOiKKKK)", input.tolerance, display.cells, display.nodes,
        display.triangles, display.checked ? Py_True : Py_False, display.depth,
        static_cast<unsigned long long>(display.spatial), static_cast<unsigned long long>(display.patches),
        static_cast<unsigned long long>(display.pairs), static_cast<unsigned long long>(display.broad)));
    Object result(PyDict_New());
    if (!settings || !result
        || !set(result.get(), "surface", surface.release())
        || !set(result.get(), "input_settings", settings.release())
        || !set(result.get(), "input_record", PyUnicode_FromStringAndSize(
            input.boundary.data(), Py_ssize_t(input.boundary.size())))) { return nullptr; }
    return result.release();
}

PyObject* takeBoundaryJob(PyObject* args)
{
    const auto job = readSolidJob(args);
    if (!job) { return nullptr; }
    if (!job->isBoundaryJob()) {
        PyErr_SetString(PyExc_TypeError, "expected a boundary preparation job");
        return nullptr;
    }
    auto data = job->take();
    const auto& tracing = *data->request.tracing;
    Object result(boundaryResult(*data->preparedBoundary));
    Object settings(Py_BuildValue("(sdis)", tracing.common ? "common" : "box_minus_field",
        data->request.tolerance, tracing.cells, tracing.regularized ? "regularized" : "reject"));
    if (!result || !settings
        || !set(result.get(), "input_settings", settings.release())
        || !set(result.get(), "input_field", PyUnicode_FromStringAndSize(tracing.field.data(), Py_ssize_t(tracing.field.size())))
        || !set(result.get(), "input_box", PyUnicode_FromStringAndSize(tracing.box.data(), Py_ssize_t(tracing.box.size())))) {
        return nullptr;
    }
    return result.release();
}

PyObject* inspectMixedSolids(PyObject* args)
{
    PyObject* object;
    if (!PyArg_ParseTuple(args, "O", &object)) {
        return nullptr;
    }
    if (!PyCapsule_IsValid(object, solidsName)) {
        PyErr_SetString(PyExc_TypeError, "expected an immutable native solid snapshot");
        return nullptr;
    }
    return nativeSolidReport(*static_cast<const BRepClass3d_ImplicitBox::NativeSolids*>(
        PyCapsule_GetPointer(object, solidsName)));
}

PyObject* dumpsMixedSolids(PyObject* args)
{
    PyObject* object;
    if (!PyArg_ParseTuple(args, "O", &object)) {
        return nullptr;
    }
    if (!PyCapsule_IsValid(object, solidsName)) {
        PyErr_SetString(PyExc_TypeError, "expected an immutable native solid snapshot");
        return nullptr;
    }
    std::ostringstream output;
    BRepClass3d_ImplicitSolidIO::Write(
        *static_cast<const BRepClass3d_ImplicitBox::NativeSolids*>(PyCapsule_GetPointer(object, solidsName)),
        output);
    const auto record = output.str();
    return PyUnicode_FromStringAndSize(record.data(), Py_ssize_t(record.size()));
}

PyObject* loadsMixedSolids(PyObject* args)
{
    PyObject* object;
    if (!PyArg_ParseTuple(args, "U", &object)) {
        return nullptr;
    }
    Py_ssize_t size;
    const char* text = PyUnicode_AsUTF8AndSize(object, &size);
    if (!text) {
        return nullptr;
    }
    if (size > 32 * 1024 * 1024) {
        throw Standard_DomainError("Native solid record exceeds 32 MiB");
    }
    std::istringstream input(std::string(text, size_t(size)));
    auto data = std::make_unique<BRepClass3d_ImplicitBox::NativeSolids>();
    BRepClass3d_ImplicitSolidIO::Read(input, *data);
    Object result(nativeSolidReport(*data));
    if (!result) {
        return nullptr;
    }
    Object capsule(PyCapsule_New(data.get(), solidsName, destroySolids));
    if (!capsule) {
        return nullptr;
    }
    data.release();
    if (!set(result.get(), "solid_handle", capsule.release())) {
        return nullptr;
    }
    return result.release();
}

PyObject* sourceMixedSolids(PyObject* args)
{
    PyObject* object;
    if (!PyArg_ParseTuple(args, "O", &object)) {
        return nullptr;
    }
    if (!PyCapsule_IsValid(object, solidsName)) {
        PyErr_SetString(PyExc_TypeError, "expected an immutable native solid snapshot");
        return nullptr;
    }
    const auto& data = *static_cast<const BRepClass3d_ImplicitBox::NativeSolids*>(
        PyCapsule_GetPointer(object, solidsName));
    return boundaryResult(data.Boundary.Source);
}

PyObject* regionTopologyReport(const BRepClass3d_ImplicitBox::RegionTopologyWitness& report)
{
    Object result(Py_BuildValue(
        "{s:O,s:O,s:O,s:O,s:O,s:O,s:O,s:O,s:s,s:K,s:K,s:i,s:i}",
        "whole_box_homotopy_resolved",
        report.Surface.HomotopyResolved ? Py_True : Py_False,
        "surface_reference_manifold",
        report.Surface.ReferenceManifold ? Py_True : Py_False,
        "closed_reference_manifold",
        report.ClosedReferenceManifold ? Py_True : Py_False,
        "stored_trim_correspondence_validated",
        Py_False,
        "native_shell_constructed",
        Py_False,
        "topology_validated",
        Py_False,
        "solid_validated",
        Py_False,
        "geometry_accuracy_verified",
        Py_False,
        "reason",
        report.Reason.c_str(),
        "reference_implicit_vertex_count",
        static_cast<unsigned long long>(report.Surface.Nodes.size()),
        "reference_implicit_triangle_count",
        static_cast<unsigned long long>(report.Surface.Triangles.size()),
        "resolution",
        report.Surface.Resolution,
        "unresolved_dimension",
        report.Surface.UnresolvedDimension
    ));
    if (!result) {
        return nullptr;
    }
    const auto integer = [](int value) {
        return PyLong_FromLong(value);
    };
    if (!set(result.get(), "corner_policy", PyUnicode_FromString(
            report.Surface.Policy == BRepClass3d_ImplicitBox::CornerPolicy::Regularized
                ? "regularized" : "reject"))
        || !set(result.get(), "fixed_corner_count", PyLong_FromLong(report.Surface.FixedCornerCount))
        || !set(result.get(), "surface_point_contacts", convertedList(report.Surface.PointContacts,
            [](const gp_Pnt& p) { return xyz(p.XYZ()); }))
        || !set(
            result.get(),
            "reference_vertices",
            convertedList(report.Nodes, [](const gp_Pnt& p) { return xyz(p.XYZ()); })
        )
        || !set(
            result.get(),
            "reference_triangles",
            convertedList(
                report.Triangles,
                [](const auto& t) { return Py_BuildValue("(iii)", t[0], t[1], t[2]); }
            )
        )
        || !set(result.get(), "reference_triangle_sides", convertedList(report.TriangleSides, integer))
        || !set(
            result.get(),
            "reference_triangle_components",
            convertedList(report.TriangleComponents, integer)
        )
        || !set(result.get(), "reference_component_euler", convertedList(report.ComponentEuler, integer))
        || !set(result.get(), "reference_region_count", PyLong_FromLong(report.RegionCount))
        || !set(result.get(), "reference_component_regions", convertedList(report.ComponentRegions, integer))
        || !set(
            result.get(),
            "reference_region_volumes",
            convertedList(
                report.RegionVolumes,
                [](double value) { return PyFloat_FromDouble(value); }
            )
        )
        || !set(
            result.get(),
            "reference_component_signed_volumes",
            convertedList(
                report.ComponentSignedVolumes,
                [](double value) { return PyFloat_FromDouble(value); }
            )
        )
        || !set(
            result.get(),
            "reference_surface_component_euler",
            convertedList(report.Surface.ComponentEuler, integer)
        )
        || !set(
            result.get(),
            "reference_surface_boundary_loops",
            convertedList(
                report.Surface.BoundaryLoops,
                [&](const auto& path) { return convertedList(path, integer); }
            )
        )
        || !set(result.get(), "unresolved_minimum", xyz(report.Surface.UnresolvedMinimum.XYZ()))
        || !set(result.get(), "unresolved_maximum", xyz(report.Surface.UnresolvedMaximum.XYZ()))) {
        return nullptr;
    }
    return result.release();
}

template<bool Mixed, bool Region = false>
PyObject* checkBoxTopology(PyObject* args)
{
    using Ops = BRepClass3d_ImplicitBox;
    PyObject* object;
    int resolution = 32, depth = 16;
    unsigned long long cells = 4000000;
    const char* cornerPolicy = "auto";
    if (!PyArg_ParseTuple(args, "O|iiKs", &object, &resolution, &depth, &cells, &cornerPolicy)) {
        return nullptr;
    }
    if (!cells || cells > 10000000) {
        throw Standard_DomainError("Invalid box topology work budget");
    }
    const TopoDS_Face* face;
    auto sourcePolicy = Ops::CornerPolicy::Reject;
    if constexpr (Mixed) {
        if (!PyCapsule_IsValid(object, boundaryName)) {
            PyErr_SetString(PyExc_TypeError, "expected an immutable native hybrid-boundary handle");
            return nullptr;
        }
        const auto* boundary = static_cast<const Ops::Boundary*>(
                    PyCapsule_GetPointer(object, boundaryName)
        );
        face = &boundary->Faces.back();
        sourcePolicy = boundary->Policy;
    }
    else {
        face = getFace(object);
        if (!face) {
            return nullptr;
        }
    }
    const std::string policyName(cornerPolicy);
    auto policy = sourcePolicy;
    if (policyName == "reject") policy = Ops::CornerPolicy::Reject;
    else if (policyName == "regularized") policy = Ops::CornerPolicy::Regularized;
    else if (policyName != "auto") throw Standard_DomainError("Unknown topology corner policy");
    if constexpr (Mixed) {
        if (policy != sourcePolicy) {
            throw Standard_DomainError("Topology query cannot override the source material policy");
        }
    }
    if constexpr (Region) {
        return regionTopologyReport(
            Ops::CheckRegionTopology(*face, resolution, depth, size_t(cells), policy)
        );
    }
    const auto report = Ops::CheckTopology(*face, resolution, depth, size_t(cells), policy);
    Object result(Py_BuildValue(
        "{s:O,s:O,s:O,s:O,s:O,s:O,s:s,s:d,s:d,s:i,s:i}",
        "whole_box_homotopy_resolved",
        report.HomotopyResolved ? Py_True : Py_False,
        "reference_manifold",
        report.ReferenceManifold ? Py_True : Py_False,
        "stored_trim_correspondence_validated",
        Py_False,
        "topology_validated",
        Py_False,
        "solid_validated",
        Py_False,
        "geometry_accuracy_verified",
        Py_False,
        "reason",
        report.Reason.c_str(),
        "minimum_homotopy_derivative",
        report.MinimumHomotopyDerivative,
        "maximum_simplex_diameter",
        report.MaximumSimplexDiameter,
        "resolution",
        report.Resolution,
        "unresolved_dimension",
        report.UnresolvedDimension
    ));
    Object vertices(PyList_New(report.Nodes.size())), triangles(PyList_New(report.Triangles.size()));
    Object loops(PyList_New(report.BoundaryLoops.size())),
        euler(PyList_New(report.ComponentEuler.size()));
    Object strata(PyList_New(4));
    if (!result || !vertices || !triangles || !loops || !euler || !strata) {
        return nullptr;
    }
    for (size_t i = 0; i < report.Nodes.size(); ++i) {
        auto* point = xyz(report.Nodes[i].XYZ());
        if (!point) {
            return nullptr;
        }
        PyList_SET_ITEM(vertices.get(), i, point);
    }
    for (size_t i = 0; i < report.Triangles.size(); ++i) {
        const auto& t = report.Triangles[i];
        auto* triangle = Py_BuildValue("(iii)", t[0], t[1], t[2]);
        if (!triangle) {
            return nullptr;
        }
        PyList_SET_ITEM(triangles.get(), i, triangle);
    }
    for (size_t i = 0; i < report.BoundaryLoops.size(); ++i) {
        const auto& path = report.BoundaryLoops[i];
        Object loop(PyList_New(path.size()));
        if (!loop) {
            return nullptr;
        }
        for (size_t j = 0; j < path.size(); ++j) {
            auto* index = PyLong_FromLong(path[j]);
            if (!index) {
                return nullptr;
            }
            PyList_SET_ITEM(loop.get(), j, index);
        }
        PyList_SET_ITEM(loops.get(), i, loop.release());
    }
    for (size_t i = 0; i < report.ComponentEuler.size(); ++i) {
        auto* value = PyLong_FromLong(report.ComponentEuler[i]);
        if (!value) {
            return nullptr;
        }
        PyList_SET_ITEM(euler.get(), i, value);
    }
    for (size_t i = 0; i < 4; ++i) {
        auto* entry = Py_BuildValue(
            "{s:i,s:K,s:K,s:K}",
            "dimension",
            int(i),
            "visited",
            static_cast<unsigned long long>(report.Visited[i]),
            "excluded",
            static_cast<unsigned long long>(report.Excluded[i]),
            "transverse",
            static_cast<unsigned long long>(report.Transverse[i])
        );
        if (!entry) {
            return nullptr;
        }
        PyList_SET_ITEM(strata.get(), i, entry);
    }
    if (!set(result.get(), "corner_policy", PyUnicode_FromString(
            report.Policy == Ops::CornerPolicy::Regularized ? "regularized" : "reject"))
        || !set(result.get(), "fixed_corner_count", PyLong_FromLong(report.FixedCornerCount))
        || !set(result.get(), "point_contacts", convertedList(report.PointContacts,
            [](const gp_Pnt& p) { return xyz(p.XYZ()); }))
        || !set(result.get(), "reference_grid_edges", convertedList(report.GridEdges,
            [](const auto& edge) { return Py_BuildValue("(ii)", edge[0], edge[1]); }))
        || !set(result.get(), "reference_vertices", vertices.release())
        || !set(result.get(), "reference_triangles", triangles.release())
        || !set(result.get(), "reference_boundary_loops", loops.release())
        || !set(result.get(), "reference_component_euler", euler.release())
        || !set(result.get(), "strata", strata.release())
        || !set(result.get(), "unresolved_minimum", xyz(report.UnresolvedMinimum.XYZ()))
        || !set(result.get(), "unresolved_maximum", xyz(report.UnresolvedMaximum.XYZ()))) {
        return nullptr;
    }
    return result.release();
}

PyObject* checkMixedCapAttachment(PyObject* args)
{
    PyObject* object;
    int resolution = 32, depth = 16;
    unsigned long long cells = 4000000, tests = 2000000;
    if (!PyArg_ParseTuple(args, "O|iiKK", &object, &resolution, &depth, &cells, &tests)) {
        return nullptr;
    }
    if (!PyCapsule_IsValid(object, boundaryName)) {
        PyErr_SetString(PyExc_TypeError, "expected an immutable native hybrid-boundary handle");
        return nullptr;
    }
    if (!cells || cells > 10000000 || !tests || tests > 10000000) {
        throw Standard_DomainError("Invalid cap attachment budgets");
    }
    const auto* boundary = static_cast<const BRepClass3d_ImplicitBox::Boundary*>(
        PyCapsule_GetPointer(object, boundaryName)
    );
    const auto report = BRepClass3d_ImplicitBox::CheckCapAttachment(
        *boundary,
        resolution,
        depth,
        size_t(cells),
        size_t(tests)
    );
    Object result(Py_BuildValue(
        "{s:O,s:O,s:O,s:O,s:O,s:O,s:O,s:s,s:d,s:K,s:K,s:i,s:i,s:i}",
        "cap_regions_attached",
        report.Resolved ? Py_True : Py_False,
        "stored_graph_correspondence_resolved",
        report.StoredGraphResolved ? Py_True : Py_False,
        "region_reference_resolved",
        report.RegionReferenceResolved ? Py_True : Py_False,
        "trim_wire_attachment_validated",
        Py_False,
        "topology_validated",
        Py_False,
        "solid_validated",
        Py_False,
        "native_shell_constructed",
        Py_False,
        "reason",
        report.Reason.c_str(),
        "required_clearance",
        report.RequiredClearance,
        "witness_tests",
        static_cast<unsigned long long>(report.WitnessTests),
        "segment_tests",
        static_cast<unsigned long long>(report.SegmentTests),
        "reference_cap_count",
        report.ReferenceCapCount,
        "reference_shell_count",
        report.ReferenceShellCount,
        "reference_region_count",
        report.ReferenceRegionCount
    ));
    if (!result) {
        return nullptr;
    }
    const auto integer = [](int value) {
        return PyLong_FromLong(value);
    };
    if (!set(result.get(), "corner_policy", PyUnicode_FromString(
            boundary->Policy == BRepClass3d_ImplicitBox::CornerPolicy::Regularized ? "regularized" : "reject"))
        || !set(result.get(), "reference_resolution", PyLong_FromLong(report.Reference.Surface.Resolution))
        || !set(result.get(), "reference_caps", convertedList(report.ReferenceCaps, integer))
        || !set(result.get(), "reference_shells", convertedList(report.ReferenceShells, integer))
        || !set(result.get(), "reference_regions", convertedList(report.ReferenceRegions, integer))
        || !set(
            result.get(),
            "witness_points",
            convertedList(report.Witnesses, [](const gp_Pnt& p) { return xyz(p.XYZ()); })
        )
        || !set(result.get(), "boundary_clearance_bounds", convertedList(report.Clearances, [](double x) {
                    return PyFloat_FromDouble(x);
                }))) {
        return nullptr;
    }
    return result.release();
}

PyObject* checkMixedTrimAttachment(PyObject* args)
{
    PyObject* object;
    int resolution = 32, depth = 16;
    unsigned long long cells = 4000000, tests = 2000000;
    if (!PyArg_ParseTuple(args, "O|iiKK", &object, &resolution, &depth, &cells, &tests)) {
        return nullptr;
    }
    if (!PyCapsule_IsValid(object, boundaryName)) {
        PyErr_SetString(PyExc_TypeError, "expected an immutable native hybrid-boundary handle");
        return nullptr;
    }
    if (!cells || cells > 10000000 || !tests || tests > 10000000) {
        throw Standard_DomainError("Invalid trim attachment budgets");
    }
    const auto* boundary = static_cast<const BRepClass3d_ImplicitBox::Boundary*>(
        PyCapsule_GetPointer(object, boundaryName)
    );
    const auto report = BRepClass3d_ImplicitBox::CheckTrimAttachment(
        *boundary,
        resolution,
        depth,
        size_t(cells),
        size_t(tests)
    );
    Object result(Py_BuildValue(
        "{s:O,s:O,s:O,s:O,s:O,s:O,s:O,s:s,s:i,s:i,s:i,s:K,s:K}",
        "trim_wires_attached",
        report.Resolved ? Py_True : Py_False,
        "cap_regions_attached",
        report.CapRegionsAttached ? Py_True : Py_False,
        "complement_cap_regions_attached",
        report.ComplementCapsAttached ? Py_True : Py_False,
        "implicit_face_attachment_validated",
        Py_False,
        "topology_validated",
        Py_False,
        "native_shell_constructed",
        Py_False,
        "solid_validated",
        Py_False,
        "reason",
        report.Reason.c_str(),
        "reference_arc_count",
        report.ReferenceArcCount,
        "reference_wire_count",
        report.ReferenceWireCount,
        "reference_surface_component_count",
        report.ReferenceSurfaceComponentCount,
        "comparisons",
        static_cast<unsigned long long>(report.Comparisons),
        "curve_samples",
        static_cast<unsigned long long>(report.CurveSamples)
    ));
    if (!result) {
        return nullptr;
    }
    const auto integer = [](int value) {
        return PyLong_FromLong(value);
    };
    if (!set(result.get(), "corner_policy", PyUnicode_FromString(
            boundary->Policy == BRepClass3d_ImplicitBox::CornerPolicy::Regularized ? "regularized" : "reject"))
        || !set(result.get(), "reference_resolution", PyLong_FromLong(report.RetainedCaps.Reference.Surface.Resolution))
        || !set(result.get(), "surface_component_euler", convertedList(report.SurfaceComponentEuler, integer))
        || !set(result.get(), "surface_component_shells", convertedList(report.SurfaceComponentShells, integer))
        || !set(result.get(), "surface_component_regions", convertedList(report.SurfaceComponentRegions, integer))
        || !set(result.get(), "seam_reference_arcs", convertedList(report.SeamReferenceArcs, integer))
        || !set(result.get(), "wire_reference_loops", convertedList(report.WireReferenceLoops, integer))
        || !set(
            result.get(),
            "wire_surface_components",
            convertedList(report.WireSurfaceComponents, integer)
        )) {
        return nullptr;
    }
    return result.release();
}

PyObject* checkMixedCorrespondence(PyObject* args)
{
    PyObject* object;
    int cells = 512;
    unsigned long long comparisons = 2000000;
    if (!PyArg_ParseTuple(args, "O|iK", &object, &cells, &comparisons)) {
        return nullptr;
    }
    if (!PyCapsule_IsValid(object, boundaryName)) {
        PyErr_SetString(PyExc_TypeError, "expected an immutable native hybrid-boundary handle");
        return nullptr;
    }
    if (!comparisons || comparisons > 10000000) {
        throw Standard_DomainError("Invalid correspondence comparison budget");
    }
    const auto* boundary = static_cast<const BRepClass3d_ImplicitBox::Boundary*>(
        PyCapsule_GetPointer(object, boundaryName)
    );
    const auto report
        = BRepClass3d_ImplicitBox::CheckCorrespondence(*boundary, cells, size_t(comparisons));
    return Py_BuildValue(
        "{s:s,s:s,s:O,s:O,s:O,s:O,s:s,s:i,s:i,s:i,s:i,s:K,s:K,s:d,s:d,s:d,s:d,s:d}",
        "corner_policy",
        boundary->Policy == BRepClass3d_ImplicitBox::CornerPolicy::Regularized ? "regularized" : "reject",
        "regularity_policy",
        boundary->Policy == BRepClass3d_ImplicitBox::CornerPolicy::Regularized ? "fixed_corner_homotopy" : "strict_strata",
        "stored_graph_correspondence_resolved",
        report.Resolved ? Py_True : Py_False,
        "field_box_regularity_resolved",
        report.RegularityResolved ? Py_True : Py_False,
        "topology_validated",
        Py_False,
        "solid_validated",
        Py_False,
        "reason",
        report.Reason.c_str(),
        "matched_edges",
        report.MatchedEdges,
        "matched_vertices",
        report.MatchedVertices,
        "matched_caps",
        report.MatchedCaps,
        "matched_wires",
        report.MatchedWires,
        "comparisons",
        static_cast<unsigned long long>(report.Comparisons),
        "sample_tests",
        static_cast<unsigned long long>(report.SampleTests),
        "matching_tolerance",
        report.MatchingTolerance,
        "curve_deviation_bound",
        report.CurveDeviationBound,
        "reference_seam_bound",
        report.ReferenceSeamBound,
        "minimum_tangent_alignment",
        report.MinimumTangentAlignment,
        "cap_parameter_deviation_bound",
        report.CapParameterDeviationBound
    );
}

PyMethodDef methods[] = {
    {"dumps_mixed_solids", checked<dumpsMixedSolids>, METH_VARARGS,
     "dumps_mixed_solids(solid_handle) -> explicit native solid topology record, not a recipe/mesh."},
    {"loads_mixed_solids", checked<loadsMixedSolids>, METH_VARARGS,
     "loads_mixed_solids(record) -> owned actual solid topology without retracing; validation "
     "flags remain false. Does not make a Part shape or restore numerical certification."},
    {"source_mixed_solids", checked<sourceMixedSolids>, METH_VARARGS,
     "source_mixed_solids(solid_handle) -> owned authoritative SOURCE boundary, not the result "
     "solids. Explicitly rebuild/recheck using this source; source flags are not proof."},
    {"start_solid_job", checked<startSolidJob>, METH_VARARGS,
     "Start a bounded native solid/initial-display job from a private boundary snapshot."},
    {"start_boundary_job", checked<startBoundaryJob>, METH_VARARGS,
     "Prepare a mixed boundary on the shared worker from private field/box snapshots."},
    {"take_boundary_job", checked<takeBoundaryJob>, METH_VARARGS,
     "Consume prepared boundary plus exact input_field/input_box/input_settings descriptors."},
    {"start_surface_job", checked<startSurfaceJob>, METH_VARARGS,
     "start_surface_job(boundary, tolerance=.1, cells=256, nodes=200000, triangles=400000, "
     "checked=False, depth=14, spatial=2000000, patches=1000000, pairs=2000000, broad=50000000)"},
    {"take_surface_job", checked<takeSurfaceJob>, METH_VARARGS,
     "Consume a display job once: surface, input_record and input_settings."},
    {"native_job_status", checked<solidJobStatus>, METH_VARARGS,
     "Read native boundary/solid/display work state, phase and checkpoint count."},
    {"cancel_native_job", checked<cancelSolidJob>, METH_VARARGS,
     "Request cooperative cancellation of a native boundary/solid/display job."},
    {"solid_job_status", checked<solidJobStatus>, METH_VARARGS,
     "Read native work state, phase and checkpoint count without waiting."},
    {"cancel_solid_job", checked<cancelSolidJob>, METH_VARARGS,
     "Request cooperative cancellation; queued/ready results are discarded."},
    {"take_solid_job", checked<takeSolidJob>, METH_VARARGS,
     "Consume a completed fresh solid and initial display candidate exactly once."},
    {"build_mixed_solids", checked<buildMixedSolids>, METH_VARARGS,
     "build_mixed_solids(boundary_handle, tolerance=.1, resolution=32, maximum_depth=16, "
     "maximum_cells=4000000, maximum_tests=2000000, maximum_separator_cells=2000000, "
     "maximum_geometry_cells=2000000, maximum_segment_tests=8000000, maximum_geometry_depth=-1) "
     "(-1 inherits reference depth) -> restricted native "
     "solids gated by numerical topology and whole-boundary geometry checks; NOT Part shapes."},
    {"inspect_mixed_solids", checked<inspectMixedSolids>, METH_VARARGS,
     "inspect_mixed_solids(solid_handle) -> owned native solid diagnostics and field faces."},
    {"classify_mixed_solids", checked<classifyMixed<2>>, METH_VARARGS,
     "classify_mixed_solids(solid_handle, point, tolerance=.1) -> classification of the "
     "authoritative material-region union, not per-solid selection or generic UV classification."},
    {"build_mixed_shells",
     checked<buildMixedShells>,
     METH_VARARGS,
     "build_mixed_shells(boundary_handle, resolution=32, maximum_depth=16, maximum_cells=4000000, "
     "maximum_tests=2000000, maximum_separator_cells=2000000) "
     "-> owned genuine field-backed shells after whole-face/component attachment and native "
     "topology checks. "
     "NOT geometric/solid validation or a Part-compatible shape."},
    {"inspect_mixed_shells",
     checked<inspectMixedShells>,
     METH_VARARGS,
     "inspect_mixed_shells(shell_handle) -> immutable native shell snapshot diagnostics and owned "
     "field-face handles."},
    {"classify_mixed_shells",
     checked<classifyMixed<true>>,
     METH_VARARGS,
     "classify_mixed_shells(shell_handle, point, tolerance=.1) -> authoritative source "
     "mathematical-region classification, NOT solid validity."},
    {"check_mixed_trim_attachment",
     checked<checkMixedTrimAttachment>,
     METH_VARARGS,
     "check_mixed_trim_attachment(boundary_handle, resolution=32, maximum_depth=16, "
     "maximum_cells=4000000, maximum_tests=2000000) "
     "-> dual cap/root contour identities and complete directed trim-wire correspondence. "
     "Not whole implicit-face attachment or native-shell/solid validity."},
    {"check_mixed_cap_attachment",
     checked<checkMixedCapAttachment>,
     METH_VARARGS,
     "check_mixed_cap_attachment(boundary_handle, resolution=32, maximum_depth=16, "
     "maximum_cells=4000000, maximum_witness_tests=2000000) "
     "-> cap-region bijection using common F/L retained points beyond retraced seam uncertainty. "
     "Not trim-wire attachment or native-shell/solid validation."},
    {"check_mixed_cap_geometry", checked<checkMixedCapGeometry>, METH_VARARGS,
     "check_mixed_cap_geometry(boundary_handle, tolerance=.1, maximum_depth=16, "
     "maximum_cells=2000000, maximum_segment_tests=8000000) -> both directed cap-region "
     "distance bounds, lifted p-curve/edge/vertex checks and corner-regularization diagnostics. "
     "No topology or native-solid validity promotion."},
    {"check_box_region_topology",
     checked<checkBoxTopology<false, true>>,
     METH_VARARGS,
     "check_box_region_topology(native_gyroid_face, resolution=32, maximum_depth=16, "
     "maximum_cells=4000000) "
     "-> closed nodal-linear field-and-box-cap reference, component grouping and signed volume "
     "diagnostics. "
     "NOT stored-native correspondence, geometric accuracy or native shell/solid construction."},
    {"check_mixed_region_topology",
     checked<checkBoxTopology<true, true>>,
     METH_VARARGS,
     "check_mixed_region_topology(boundary_handle, resolution=32, maximum_depth=16, "
     "maximum_cells=4000000) "
     "-> checks its mathematical box region, not stored trim/cap equivalence or native-solid "
     "validity."},
    {"check_box_topology",
     checked<checkBoxTopology<false>>,
     METH_VARARGS,
     "check_box_topology(native_gyroid_face, resolution=32, maximum_depth=16, "
     "maximum_cells=4000000) "
     "-> whole BOX field-to-nodal-linear homotopy check and transient topology witness. "
     "Not stored-trim/preview equivalence, geometric accuracy or native-solid validation."},
    {"check_mixed_topology",
     checked<checkBoxTopology<true>>,
     METH_VARARGS,
     "check_mixed_topology(boundary_handle, resolution=32, maximum_depth=16, "
     "maximum_cells=4000000) "
     "-> checks its mathematical BOX zero set, NOT stored trim/cap or preview correspondence."},
    {"check_mixed_correspondence",
     checked<checkMixedCorrespondence>,
     METH_VARARGS,
     "check_mixed_correspondence(boundary_handle, maximum_cells=512, maximum_comparisons=2000000) "
     "-> private reference trace and bijective stored curve/vertex/directed wire/cap graph match. "
     "Not surface isotopy, reach or native-solid validation; source is never replaced."},
    {"check_mixed_regularity",
     checked<checkBoxRegularity<true>>,
     METH_VARARGS,
     "check_mixed_regularity(boundary_handle, maximum_depth=14, maximum_cells=2000000) -> "
     "mesh-independent whole-box volume/face/edge/corner regularity. Floating reserves, "
     "NOT stored trim correspondence or solid validation."},
    {"trace_gyroid_cylinder_disks", checked<traceGyroidCylinder<true, true, false, true>>, METH_VARARGS,
     "Trace disk contours with accepted cells/shared circle roots; not cap regions or solids."},
    {"build_gyroid_cylinder_rings", checked<traceGyroidCylinder<true, true, true>>, METH_VARARGS,
     "Build analytic boundary-circle edges sharing side root vertices; report only, not cap regions/solids."},
    {"trace_gyroid_cylinder_boundary", checked<traceGyroidCylinder<true, true>>, METH_VARARGS,
     "Trace a full cylinder and retain end-cap root brackets/curve endpoint IDs; not native trims or solids."},
    {"trace_gyroid_cylinder_periodic", checked<traceGyroidCylinder<true>>, METH_VARARGS,
     "Trace a full cylindrical chart with one shared seam; curves, not native trim/solid topology."},
    {"trace_gyroid_cylinder", checked<traceGyroidCylinder<false>>, METH_VARARGS,
     "Trace a finite open cylinder chart; bounded polylines, not trim topology or solids."},
    {"trace_gyroid_plane", checked<traceGyroidPlane>, METH_VARARGS,
     "Trace a bounded plane rectangle; polylines and isolated point contacts, not native trim B-Reps. "
     "Exact lattice-node mode is explicit and requires identity field placement/coordinate planes."},
    {"check_box_corners", checked<checkBoxCorners>, METH_VARARGS,
     "check_box_corners(native_gyroid_face, maximum_radius=.1) -> local corner germs; "
     "NOT strict box regularity, trim topology or solid validation. Corner bits encode high XYZ."},
    {"classify_box_corner", checked<classifyBoxCorner>, METH_VARARGS,
     "classify_box_corner(face, corner_index, point, operation='common', maximum_radius=.1) -> "
     "closed versus regularized LOCAL membership; not whole-solid distance classification."},
    {"check_box_regularity",
     checked<checkBoxRegularity<false>>,
     METH_VARARGS,
     "check_box_regularity(native_gyroid_face, maximum_depth=14, maximum_cells=2000000) -> "
     "regularity in its BOX DOMAIN (stored trim wires ignored). Identity placement only."},
    {"check_mixed_coverage",
     checked<checkMixedCoverage>,
     METH_VARARGS,
     "check_mixed_coverage(boundary_handle, tolerance=.1, maximum_cells=256, maximum_depth=14, "
     "maximum_spatial_cells=2000000, maximum_triangle_patches=1000000) -> whole-box/face and "
     "mesh-to-clipped-boundary proximity bounds with floating reserves; NOT topology/solid "
     "validation."},
    {"audit_mixed_mesh",
     checked<auditMixedMesh>,
     METH_VARARGS,
     "audit_mixed_mesh(boundary_handle, tolerance=.1, maximum_cells=256, "
     "maximum_pair_tests=2000000, "
     "maximum_broad_tests=50000000) -> exact stored-coordinate triangle contact audit; "
     "not field coverage or native-solid validation. Caps precede implicit triangle IDs."},
    {"tessellate_mixed",
     checked<prepareMixedMesh<true>>,
     METH_VARARGS,
     "tessellate_mixed(boundary_handle, tolerance=.1, maximum_cells=256, maximum_nodes=200000, "
     "maximum_triangles=400000) -> trim-conforming closed mesh candidate. One-sided "
     "triangle-to-untrimmed-field distance bound, NOT coverage, embeddedness or solid validation."},
    {"tessellate_mixed_checked", checked<prepareMixedMesh<true, true>>, METH_VARARGS,
     "tessellate_mixed_checked(handle, tolerance=.1, maximum_cells=256, maximum_nodes=200000, "
     "maximum_triangles=400000, maximum_depth=14, maximum_spatial_cells=2000000, "
     "maximum_triangle_patches=1000000, maximum_pair_tests=2000000, maximum_broad_tests=50000000) "
     "-> same-buffer binary32 display with two-way clipped proximity and exact contact checks; "
     "unresolved checks reject, NOT native topology/solid validation or world-placement precision."},
    {"prepare_mixed_mesh",
     checked<prepareMixedMesh<false>>,
     METH_VARARGS,
     "prepare_mixed_mesh(boundary_handle, cap_deflection=.1, maximum_nodes=200000, "
     "maximum_triangles=400000) -> cap triangles/shared native seam constraints; "
     "NO implicit surface mesh or validated solid. Indices are zero-based; cap triangles "
     "are (a,b,c,cap_index), wires repeat the closing node."},
    {"inspect_mixed",
     checked<inspectMixed>,
     METH_VARARGS,
     "inspect_mixed(boundary_handle) -> snapshot metadata/cap copies; no rebuilding"},
    {"dumps_mixed",
     checked<dumpMixed>,
     METH_VARARGS,
     "dumps_mixed(boundary_handle) -> explicit shared-topology record"},
    {"loads_mixed",
     checked<loadMixed>,
     METH_VARARGS,
     "loads_mixed(record) -> native hybrid boundary; stored error bound is not re-certified"},
    {"classify_mixed",
     checked<classifyMixed<false>>,
     METH_VARARGS,
     "classify_mixed(boundary_handle, point, distance_tolerance=.1) -> conservative region "
     "classification"},
    {"mixed_box",
     checked<mixedBox>,
     METH_VARARGS,
     "mixed_box(gyroid, box_brep, operation, tolerance=.1, maximum_cells=512) -> hybrid boundary, "
     "NOT a solid"},
    {"sphere", checked<sphere>, METH_VARARGS, "sphere(center, radius, tolerance=0.1) -> native face"},
    {"restrict_cylinder_local", checked<restrictCylinderLocal>, METH_VARARGS,
     "Restrict an owned primitive face to a finite field-local cylinder; no trim topology/solid proof."},
    {"gyroid",
     checked<gyroid>,
     METH_VARARGS,
     "gyroid(period, iso, minimum, maximum, tolerance=0.1) -> native face"},
    {"value",
     checked<query<0>>,
     METH_VARARGS,
     "value(face, point) -> field value, not necessarily a distance"},
    {"gradient", checked<query<1>>, METH_VARARGS, "gradient(face, point) -> placed gradient"},
    {"normal", checked<query<2>>, METH_VARARGS, "normal(face, point) -> oriented unit normal"},
    {"in_domain", checked<query<3>>, METH_VARARGS, "in_domain(face, point) -> domain/trim predicate"},
    {"info", checked<info>, METH_VARARGS, "info(face) -> representation/bounds/tolerance metadata"},
    {"intersect_ray",
     checked<ray>,
     METH_VARARGS,
     "intersect_ray(face, origin, direction, min, max, samples=512, tolerance=0) -> sampled roots"},
    {"dumps",
     checked<dumps>,
     METH_VARARGS,
     "dumps(face) -> explicit schema-1 primitive record; trims reject"},
    {"loads", checked<loads>, METH_VARARGS, "loads(record) -> fresh immutable native face"},
    {"translated", checked<translated>, METH_VARARGS, "translated(face, offset) -> new placed snapshot"},
    {"trim", checked<trim>, METH_VARARGS, "trim(sphere, normal, offset) -> restricted native plane patch"},
    {"boolean_faces",
     checked<booleanFaces>,
     METH_VARARGS,
     "boolean_faces(a, b, operation) -> (face, source) boundary pairs, NOT a solid"},
    {"tessellate",
     checked<mesh>,
     METH_VARARGS,
     "tessellate(sphere_or_patch, tolerance=0.1) -> transient bounded display mesh"},
    {nullptr, nullptr, 0, nullptr}
};
PyModuleDef definition = {
    PyModuleDef_HEAD_INIT,
    "_ImplicitOCCT",
    "Private OCCT 8 native-face binding.",
    -1,
    methods,
    nullptr,
    nullptr,
    nullptr,
    nullptr
};
}  // namespace

PyMODINIT_FUNC PyInit__ImplicitOCCT()
{
    Object module(PyModule_Create(&definition));
    if (!module
        || PyModule_AddStringConstant(module.get(), "kernel_version", OCC_VERSION_COMPLETE) < 0) {
        return nullptr;
    }
    return module.release();
}
