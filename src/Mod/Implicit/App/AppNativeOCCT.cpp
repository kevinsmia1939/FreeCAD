// SPDX-License-Identifier: LGPL-2.1-or-later
// Private OCCT 8-only binding. Import through the ABI-checking ImplicitOCCT facade.
#include <Python.h>
#include <BRep_Builder.hxx>
#include <BRep_Tool.hxx>
#include <BRep_ImplicitIO.hxx>
#include <BRep_ImplicitTool.hxx>
#include <BRep_ImplicitSphereOps.hxx>
#include <BRepClass3d_ImplicitBox.hxx>
#include <BRepClass3d_ImplicitBoxIO.hxx>
#include <BRepMesh_ImplicitBoundary.hxx>
#include <BRep_TImplicitFace.hxx>
#include <BRepTools.hxx>
#include <Geom_ImplicitSphere.hxx>
#include <Geom_ImplicitGyroid.hxx>
#include <Geom_BSplineCurve.hxx>
#include <TopExp.hxx>
#include <NCollection_IndexedMap.hxx>
#include <TopTools_ShapeMapHasher.hxx>
#include <Standard_DomainError.hxx>
#include <Standard_NotImplemented.hxx>
#include <Standard_Version.hxx>
#include <TopoDS.hxx>
#include <gp_Trsf.hxx>
#include <cmath>
#include <memory>
#include <sstream>
#include <string>

namespace
{
constexpr const char* faceName = "ImplicitOCCT.NativeFace.v1";
constexpr const char* boundaryName = "ImplicitOCCT.HybridBoundary.v1";
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
        "{s:O,s:O,s:O,s:d,s:(ddd),s:(ddd)}",
        "is_implicit",
        BRep_Tool::IsImplicit(*face) ? Py_True : Py_False,
        "has_parametric_surface",
        BRep_Tool::HasParametricSurface(*face) ? Py_True : Py_False,
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
    double tolerance = .1;
    int maximumCells = 512;
    if (!PyArg_ParseTuple(args, "OUs|di", &object, &record, &operation, &tolerance, &maximumCells)) {
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
        maximumCells
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

PyObject* classifyMixed(PyObject* args)
{
    PyObject *object, *coordinate;
    double tolerance = .1;
    gp_Pnt p;
    if (!PyArg_ParseTuple(args, "OO|d", &object, &coordinate, &tolerance)) {
        return nullptr;
    }
    if (!PyCapsule_IsValid(object, boundaryName)) {
        PyErr_SetString(PyExc_TypeError, "expected an immutable native hybrid-boundary handle");
        return nullptr;
    }
    if (!point(coordinate, p)) {
        return nullptr;
    }
    using Ops = BRepClass3d_ImplicitBox;
    const auto* boundary = static_cast<const Ops::Boundary*>(
        PyCapsule_GetPointer(object, boundaryName)
    );
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
        Py_False
    ));
    if (!result) {
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

template<bool Surface>
PyObject* prepareMixedMesh(PyObject* args)
{
    PyObject* object;
    double deflection = .1;
    int maximumNodes = 200000, maximumTriangles = 400000, maximumCells = 256;
    const bool parsed = Surface
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
    const auto mesh = Surface
        ? BRepMesh_ImplicitBoundary::Tessellate(
              *boundary,
              deflection,
              maximumCells,
              maximumNodes,
              maximumTriangles
          )
        : BRepMesh_ImplicitBoundary::Prepare(*boundary, deflection, maximumNodes, maximumTriangles);
    Object result(PyDict_New()), vertices(PyList_New(mesh.Nodes.size()));
    Object triangles(PyList_New(mesh.CapTriangles.size()));
    Object implicitTriangles(PyList_New(mesh.ImplicitTriangles.size()));
    if (!result || !vertices || !triangles || !implicitTriangles) {
        return nullptr;
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
    if (!set(result.get(), "vertices", vertices.release())
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
        "{s:O,s:O,s:O,s:O,s:d,s:d,s:d,s:K,s:K,s:i,s:i}",
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
        report.UnresolvedTriangle
    ));
    if (!result || !set(result.get(), "unresolved_minimum", xyz(report.UnresolvedMinimum.XYZ()))
        || !set(result.get(), "unresolved_maximum", xyz(report.UnresolvedMaximum.XYZ()))) {
        return nullptr;
    }
    return result.release();
}

PyMethodDef methods[] = {
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
     checked<classifyMixed>,
     METH_VARARGS,
     "classify_mixed(boundary_handle, point, distance_tolerance=.1) -> conservative region "
     "classification"},
    {"mixed_box",
     checked<mixedBox>,
     METH_VARARGS,
     "mixed_box(gyroid, box_brep, operation, tolerance=.1, maximum_cells=512) -> hybrid boundary, "
     "NOT a solid"},
    {"sphere", checked<sphere>, METH_VARARGS, "sphere(center, radius, tolerance=0.1) -> native face"},
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
