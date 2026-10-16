// SPDX-License-Identifier: LGPL-2.1-or-later

#include <App/DocumentObjectPy.h>
#include <Base/Interpreter.h>
#include <Base/PyObjectBase.h>
#include <cmath>
#include <atomic>
#include <vector>

#include "Feature.h"
#include "FieldGraph.h"
#include "SurfaceMesh.h"
#ifdef IMPLICIT_WITH_NATIVE_GEOMETRY
# include "NativeGeometry.h"
#endif

namespace Implicit
{

namespace
{

constexpr const char* cancellationName = "Implicit.CancellationToken";

std::atomic_bool* cancellationFromPython(PyObject* object)
{
    auto* token = static_cast<std::atomic_bool*>(PyCapsule_GetPointer(object, cancellationName));
    if (!token) {
        throw Py::Exception();
    }
    return token;
}

void deleteCancellation(PyObject* capsule)
{
    delete static_cast<std::atomic_bool*>(PyCapsule_GetPointer(capsule, cancellationName));
}

Feature* featureFromPython(PyObject* object)
{
    if (!PyObject_TypeCheck(object, &App::DocumentObjectPy::Type)) {
        throw Py::TypeError("expected an Implicit::Feature document object");
    }
    auto* documentObject = static_cast<App::DocumentObjectPy*>(object)->getDocumentObjectPtr();
    auto* feature = freecad_cast<Feature*>(documentObject);
    if (!feature) {
        throw Py::TypeError("expected an Implicit::Feature document object");
    }
    return feature;
}

Base::Vector3d vectorFromTuple(const Py::Tuple& args, Py_ssize_t offset)
{
    double coordinates[3];
    for (Py_ssize_t axis = 0; axis < 3; ++axis) {
        coordinates[axis] = PyFloat_AsDouble(args[offset + axis].ptr());
        if (PyErr_Occurred()) {
            throw Py::Exception();
        }
    }
    return Base::Vector3d(coordinates[0], coordinates[1], coordinates[2]);
}

Py::Tuple vectorToPython(const Base::Vector3d& point)
{
    Py::Tuple tuple(3);
    tuple[0] = Py::Float(point.x);
    tuple[1] = Py::Float(point.y);
    tuple[2] = Py::Float(point.z);
    return tuple;
}

}  // namespace

class Module: public Py::ExtensionModule<Module>
{
public:
    Module()
        : Py::ExtensionModule<Module>("Implicit")
    {
        add_varargs_method(
            "evaluate",
            &Module::evaluate,
            "evaluate(feature, x, y, z) -> scalar field value"
        );
        add_varargs_method(
            "evaluateBatch",
            &Module::evaluateBatch,
            "evaluateBatch(feature, points) -> scalar values in feature-local coordinates"
        );
        add_varargs_method("gradient", &Module::gradient, "gradient(feature, x, y, z) -> (dx, dy, dz)");
        add_varargs_method(
            "sampleChart",
            &Module::sampleChart,
            "sampleChart(feature, seed, width, height, depth, pointCount=9, raySamples=128, "
            "distanceTolerance=1e-9, minimumAlignment=0.2, cancellationToken=None) -> local height "
            "chart"
        );
        add_varargs_method(
            "project",
            &Module::project,
            "project(feature, point, distanceTolerance=1e-7, fieldTolerance=1e-9, "
            "maxIterations=64, gradientStep=1e-5) -> local stationary projection diagnostics"
        );
        add_varargs_method(
            "inspectTessellation",
            &Module::inspectTessellation,
            "inspectTessellation(feature, resolution=24, adaptive=False) -> sampled mesh quality "
            "report"
        );
        add_varargs_method(
            "tessellateControlled",
            &Module::tessellateControlled,
            "tessellateControlled(feature, fieldTolerance, minResolution=8, maxResolution=64, "
            "cancellationToken=None) -> mesh, triangle field bound and refinement history"
        );
        add_varargs_method(
            "intersectRay",
            &Module::intersectRay,
            "intersectRay(feature, origin, direction, minDistance, maxDistance, samples=512, "
            "distanceTolerance=1e-7) -> local sampled root dictionaries; direction is normalized"
        );
        add_varargs_method(
            "bounds",
            &Module::bounds,
            "bounds(feature) -> effective local domain (minimum, maximum)"
        );
        add_varargs_method(
            "classify",
            &Module::classify,
            "classify(feature, x, y, z) -> 'inside', 'surface', or 'outside'"
        );
        add_varargs_method(
            "setFieldGraph",
            &Module::setFieldGraph,
            "setFieldGraph(feature, json) -> canonical JSON"
        );
        add_varargs_method(
            "getFieldGraph",
            &Module::getFieldGraph,
            "getFieldGraph(feature) -> canonical JSON, or an empty string"
        );
        add_varargs_method(
            "validateFieldGraph",
            &Module::validateFieldGraph,
            "validateFieldGraph(json) -> canonical JSON"
        );
        add_varargs_method(
            "tessellate",
            &Module::tessellate,
            "tessellate(feature, resolution=24) -> local vertices, normals, triangles, sample_count"
        );
        add_varargs_method(
            "tessellateAdaptive",
            &Module::tessellateAdaptive,
            "tessellateAdaptive(feature, resolution=32) -> mesh with conservative block pruning"
        );
        add_varargs_method(
            "newCancellationToken",
            &Module::newCancellationToken,
            "newCancellationToken() -> one-shot thread-safe extraction token"
        );
        add_varargs_method(
            "cancel",
            &Module::cancel,
            "cancel(token) -> request cancellation of extraction using token"
        );
        add_varargs_method(
            "isCancelled",
            &Module::isCancelled,
            "isCancelled(token) -> current one-shot cancellation state"
        );
        initialize("Native implicit geometry primitives for FreeCAD.");
    }

private:
    Py::Object isCancelled(const Py::Tuple& args)
    {
        if (args.size() != 1) {
            throw Py::TypeError("isCancelled expects (token)");
        }
        return Py::Boolean(cancellationFromPython(args[0].ptr())->load(std::memory_order_relaxed));
    }

    Py::Object sampleChart(const Py::Tuple& args)
    {
        PyObject* object = nullptr;
        PyObject* token = Py_None;
        Base::Vector3d seed;
        double width, height, depth, tolerance = 1e-9, alignment = 0.2;
        int count = 9, samples = 128;
        if (!PyArg_ParseTuple(
                args.ptr(),
                "O(ddd)ddd|iiddO",
                &object,
                &seed.x,
                &seed.y,
                &seed.z,
                &width,
                &height,
                &depth,
                &count,
                &samples,
                &tolerance,
                &alignment,
                &token
            )) {
            throw Py::Exception();
        }
        const Shape shape = featureFromPython(object)->makeShape();
        const auto* cancelled = token == Py_None ? nullptr : cancellationFromPython(token);
        Shape::Chart chart;
        {
            Base::PyGILStateRelease release;
            chart = shape.sampleChart(
                seed,
                width,
                height,
                depth,
                count,
                samples,
                tolerance,
                alignment,
                cancelled
            );
        }
        Py::List points;
        for (int u = 0; u < chart.count; ++u) {
            Py::List row;
            for (int v = 0; v < chart.count; ++v) {
                row.append(vectorToPython(chart.points[u * chart.count + v]));
            }
            points.append(row);
        }
        Py::Dict result;
        result["points"] = points;
        result["center"] = vectorToPython(chart.center);
        result["u_axis"] = vectorToPython(chart.u);
        result["v_axis"] = vectorToPython(chart.v);
        result["normal"] = vectorToPython(chart.normal);
        result["max_residual"] = Py::Float(chart.maxResidual);
        result["minimum_alignment"] = Py::Float(chart.minimumAlignment);
        return result;
    }

    Py::Object tessellateControlled(const Py::Tuple& args)
    {
        PyObject* object = nullptr;
        PyObject* token = Py_None;
        double tolerance;
        int minimum = 8, maximum = 64;
        if (!PyArg_ParseTuple(args.ptr(), "Od|iiO", &object, &tolerance, &minimum, &maximum, &token)) {
            throw Py::Exception();
        }
        const Shape shape = featureFromPython(object)->makeShape();
        const auto* cancelled = token == Py_None ? nullptr : cancellationFromPython(token);
        ControlledMesh extraction;
        {
            Base::PyGILStateRelease release;
            extraction = Implicit::tessellateControlled(shape, tolerance, minimum, maximum, cancelled);
        }
        Py::Dict result = meshToPython(extraction.mesh);
        result["quality"] = qualityToPython(extraction.mesh, extraction.quality);
        result["tolerance_met"] = Py::Boolean(extraction.toleranceMet);
        result["surface_coverage_verified"] = Py::Boolean(false);
        result["status"] = Py::String(extraction.status);
        Py::List history;
        for (const auto& step : extraction.history) {
            Py::Dict entry;
            entry["resolution"] = Py::Long(static_cast<unsigned long>(step.resolution));
            entry["triangles"] = Py::Long(step.triangles);
            entry["residual_bound"] = Py::Float(step.residualBound);
            history.append(entry);
        }
        result["history"] = history;
        return result;
    }

    Py::Object inspectTessellation(const Py::Tuple& args)
    {
        PyObject* object = nullptr;
        int resolution = 24;
        int adaptive = 0;
        if (!PyArg_ParseTuple(args.ptr(), "O|ip", &object, &resolution, &adaptive)) {
            throw Py::Exception();
        }
        const Shape shape = featureFromPython(object)->makeShape();
        SurfaceMesh mesh;
        MeshQuality quality;
        {
            Base::PyGILStateRelease release;
            mesh = adaptive ? Implicit::tessellateAdaptive(shape, resolution)
                            : Implicit::tessellate(shape, resolution);
            quality = inspectMesh(shape, mesh);
        }
        return qualityToPython(mesh, quality);
    }

    Py::Dict qualityToPython(const SurfaceMesh& mesh, const MeshQuality& quality)
    {
        Py::Dict result;
        result["max_triangle_residual_bound"] = Py::Float(quality.maxTriangleResidualBound);
        result["vertices"] = Py::Long(mesh.vertices.size());
        result["triangles"] = Py::Long(mesh.triangles.size());
        result["max_vertex_residual"] = Py::Float(quality.maxVertexResidual);
        result["max_centroid_residual"] = Py::Float(quality.maxCentroidResidual);
        result["max_edge_midpoint_residual"] = Py::Float(quality.maxEdgeMidpointResidual);
        result["boundary_edges"] = Py::Long(quality.boundaryEdges);
        result["non_manifold_edges"] = Py::Long(quality.nonManifoldEdges);
        result["inconsistent_edges"] = Py::Long(quality.inconsistentEdges);
        result["degenerate_triangles"] = Py::Long(quality.degenerateTriangles);
        return result;
    }

    Py::Object project(const Py::Tuple& args)
    {
        PyObject* object = nullptr;
        Base::Vector3d point;
        double distanceTolerance = 1e-7, fieldTolerance = 1e-9, gradientStep = 1e-5;
        int iterations = 64;
        if (!PyArg_ParseTuple(
                args.ptr(),
                "O(ddd)|ddid",
                &object,
                &point.x,
                &point.y,
                &point.z,
                &distanceTolerance,
                &fieldTolerance,
                &iterations,
                &gradientStep
            )) {
            throw Py::Exception();
        }
        const Shape shape = featureFromPython(object)->makeShape();
        Shape::Projection projection;
        {
            Base::PyGILStateRelease release;
            projection
                = shape.project(point, distanceTolerance, fieldTolerance, iterations, gradientStep);
        }
        Py::Dict result;
        result["point"] = vectorToPython(projection.point);
        result["distance"] = Py::Float(projection.distance);
        result["residual"] = Py::Float(projection.residual);
        result["stationarity"] = Py::Float(projection.stationarity);
        result["iterations"] = Py::Long(projection.iterations);
        result["converged"] = Py::Boolean(projection.converged);
        result["status"] = Py::String(projection.status);
        return result;
    }

    Py::Object intersectRay(const Py::Tuple& args)
    {
        PyObject* object = nullptr;
        Base::Vector3d origin, direction;
        double minimum, maximum, tolerance = 1e-7;
        int samples = 512;
        if (!PyArg_ParseTuple(
                args.ptr(),
                "O(ddd)(ddd)dd|id",
                &object,
                &origin.x,
                &origin.y,
                &origin.z,
                &direction.x,
                &direction.y,
                &direction.z,
                &minimum,
                &maximum,
                &samples,
                &tolerance
            )) {
            throw Py::Exception();
        }
        const Shape shape = featureFromPython(object)->makeShape();
        std::vector<Shape::RayHit> hits;
        {
            Base::PyGILStateRelease release;
            hits = shape.intersectRay(origin, direction, minimum, maximum, samples, tolerance);
        }
        Py::List result;
        for (const auto& hit : hits) {
            Py::Dict item;
            item["distance"] = Py::Float(hit.distance);
            item["point"] = vectorToPython(hit.point);
            item["residual"] = Py::Float(hit.residual);
            item["bracket_width"] = Py::Float(hit.bracketWidth);
            result.append(item);
        }
        return result;
    }

    Py::Object bounds(const Py::Tuple& args)
    {
        if (args.size() != 1) {
            throw Py::TypeError("bounds expects (feature)");
        }
        const auto shape = featureFromPython(args[0].ptr())->makeShape();
        Py::Tuple result(2);
        result[0] = vectorToPython(shape.getDomain().minimum);
        result[1] = vectorToPython(shape.getDomain().maximum);
        return result;
    }

    Py::Object newCancellationToken(const Py::Tuple& args)
    {
        if (args.size() != 0) {
            throw Py::TypeError("newCancellationToken expects no arguments");
        }
        auto token = std::make_unique<std::atomic_bool>(false);
        PyObject* capsule = PyCapsule_New(token.get(), cancellationName, deleteCancellation);
        if (!capsule) {
            throw Py::Exception();
        }
        token.release();
        return Py::Object(capsule, true);
    }

    Py::Object cancel(const Py::Tuple& args)
    {
        if (args.size() != 1) {
            throw Py::TypeError("cancel expects (token)");
        }
        cancellationFromPython(args[0].ptr())->store(true, std::memory_order_relaxed);
        return Py::None();
    }

    Py::Object evaluateBatch(const Py::Tuple& args)
    {
        if (args.size() != 2) {
            throw Py::TypeError("evaluateBatch expects (feature, points)");
        }
        const Shape shape = featureFromPython(args[0].ptr())->makeShape();
        PyObject* rawSequence = PySequence_Fast(args[1].ptr(), "points must be a sequence");
        if (!rawSequence) {
            throw Py::Exception();
        }
        Py::Object sequence(rawSequence, true);
        const auto count = PySequence_Fast_GET_SIZE(sequence.ptr());
        if (count > 1000000) {
            throw Py::ValueError("batch point budget exceeded");
        }
        std::vector<Base::Vector3d> points;
        points.reserve(static_cast<std::size_t>(count));
        for (Py_ssize_t index = 0; index < count; ++index) {
            PyObject* rawCoordinates = PySequence_Fast(
                PySequence_Fast_GET_ITEM(sequence.ptr(), index),
                "each point must be a sequence"
            );
            if (!rawCoordinates) {
                throw Py::Exception();
            }
            Py::Object coordinates(rawCoordinates, true);
            if (PySequence_Fast_GET_SIZE(coordinates.ptr()) != 3) {
                throw Py::ValueError("each point must have three coordinates");
            }
            double point[3];
            for (Py_ssize_t axis = 0; axis < 3; ++axis) {
                point[axis] = PyFloat_AsDouble(PySequence_Fast_GET_ITEM(coordinates.ptr(), axis));
                if (PyErr_Occurred()) {
                    throw Py::Exception();
                }
                if (!std::isfinite(point[axis])) {
                    throw Py::ValueError("point coordinates must be finite");
                }
            }
            points.emplace_back(point[0], point[1], point[2]);
        }
        std::vector<double> results(points.size());
        {
            Base::PyGILStateRelease release;
            for (std::size_t index = 0; index < points.size(); ++index) {
                results[index] = shape.value(points[index]);
            }
        }
        Py::List values;
        for (const auto value : results) {
            values.append(Py::Float(value));
        }
        return values;
    }

    Py::Object tessellate(const Py::Tuple& args)
    {
        return extractMesh(args, false);
    }
    Py::Object tessellateAdaptive(const Py::Tuple& args)
    {
        return extractMesh(args, true);
    }

    Py::Object extractMesh(const Py::Tuple& args, bool adaptive)
    {
        if (args.size() < 1 || args.size() > 3) {
            throw Py::TypeError("tessellate expects (feature, resolution=24, cancellationToken=None)");
        }
        long resolution = adaptive ? 32 : 24;
        if (args.size() >= 2) {
            if (!PyLong_Check(args[1].ptr()) || PyBool_Check(args[1].ptr())) {
                throw Py::TypeError("tessellation resolution must be an integer");
            }
            resolution = PyLong_AsLong(args[1].ptr());
            if (PyErr_Occurred()) {
                throw Py::Exception();
            }
        }
        if (resolution < 2 || resolution > 64) {
            throw Py::ValueError("tessellation resolution must be between 2 and 64");
        }
        const Shape shape = featureFromPython(args[0].ptr())->makeShape();
        const auto* cancelled = args.size() == 3 && args[2].ptr() != Py_None
            ? cancellationFromPython(args[2].ptr())
            : nullptr;
        SurfaceMesh mesh;
        {
            // Capture immutable geometry while holding the GIL; never access
            // FreeCAD document objects or Python containers in the released region.
            Base::PyGILStateRelease release;
            mesh = adaptive
                ? Implicit::tessellateAdaptive(shape, static_cast<unsigned int>(resolution), cancelled)
                : Implicit::tessellate(shape, static_cast<unsigned int>(resolution), cancelled);
        }
        return meshToPython(mesh);
    }

    Py::Dict meshToPython(const SurfaceMesh& mesh)
    {
        Py::List vertices;
        Py::List normals;
        Py::List triangles;
        for (const auto& vertex : mesh.vertices) {
            Py::Tuple tuple(3);
            tuple[0] = Py::Float(vertex.x);
            tuple[1] = Py::Float(vertex.y);
            tuple[2] = Py::Float(vertex.z);
            vertices.append(tuple);
        }
        for (const auto& normal : mesh.normals) {
            Py::Tuple tuple(3);
            tuple[0] = Py::Float(normal.x);
            tuple[1] = Py::Float(normal.y);
            tuple[2] = Py::Float(normal.z);
            normals.append(tuple);
        }
        for (const auto& triangle : mesh.triangles) {
            Py::Tuple tuple(3);
            for (std::size_t i = 0; i < 3; ++i) {
                tuple[i] = Py::Long(static_cast<unsigned long>(triangle[i]));
            }
            triangles.append(tuple);
        }
        Py::Dict result;
        result["vertices"] = vertices;
        result["normals"] = normals;
        result["triangles"] = triangles;
        result["sample_count"] = Py::Long(static_cast<unsigned long>(mesh.sampleCount));
        result["pruned_blocks"] = Py::Long(static_cast<unsigned long>(mesh.prunedBlocks));
        return result;
    }

    Py::Object invoke_method_varargs(void* methodDefinition, const Py::Tuple& args) override
    {
        try {
            return Py::ExtensionModule<Module>::invoke_method_varargs(methodDefinition, args);
        }
        catch (const Base::Exception& error) {
            throw Py::RuntimeError(error.what());
        }
        catch (const std::exception& error) {
            throw Py::RuntimeError(error.what());
        }
    }

    Py::Object evaluate(const Py::Tuple& args)
    {
        if (args.size() != 4) {
            throw Py::TypeError("evaluate expects (feature, x, y, z)");
        }
        const Shape shape = featureFromPython(args[0].ptr())->makeShape();
        return Py::Float(shape.value(vectorFromTuple(args, 1)));
    }

    Py::Object gradient(const Py::Tuple& args)
    {
        if (args.size() != 4) {
            throw Py::TypeError("gradient expects (feature, x, y, z)");
        }
        const Shape shape = featureFromPython(args[0].ptr())->makeShape();
        const Base::Vector3d result = shape.gradient(vectorFromTuple(args, 1));
        Py::Tuple tuple(3);
        tuple[0] = Py::Float(result.x);
        tuple[1] = Py::Float(result.y);
        tuple[2] = Py::Float(result.z);
        return tuple;
    }

    Py::Object classify(const Py::Tuple& args)
    {
        if (args.size() != 4) {
            throw Py::TypeError("classify expects (feature, x, y, z)");
        }
        const Shape shape = featureFromPython(args[0].ptr())->makeShape();
        switch (shape.classify(vectorFromTuple(args, 1))) {
            case PointClassification::Inside:
                return Py::String("inside");
            case PointClassification::OnSurface:
                return Py::String("surface");
            case PointClassification::Outside:
                return Py::String("outside");
        }
        throw Py::RuntimeError("invalid implicit classification");
    }

    Py::Object setFieldGraph(const Py::Tuple& args)
    {
        if (args.size() != 2 || !PyUnicode_Check(args[1].ptr())) {
            throw Py::TypeError("setFieldGraph expects (feature, json)");
        }
        Feature* feature = featureFromPython(args[0].ptr());
        const std::string canonical = FieldGraph::canonicalize(PyUnicode_AsUTF8(args[1].ptr()));
        feature->FieldGraph.setValue(canonical);
        return Py::String(canonical);
    }

    Py::Object getFieldGraph(const Py::Tuple& args)
    {
        if (args.size() != 1) {
            throw Py::TypeError("getFieldGraph expects (feature)");
        }
        const std::string serialized = featureFromPython(args[0].ptr())->FieldGraph.getValue();
        if (serialized.empty()) {
            return Py::String();
        }
        return Py::String(FieldGraph::canonicalize(serialized));
    }

    Py::Object validateFieldGraph(const Py::Tuple& args)
    {
        if (args.size() != 1 || !PyUnicode_Check(args[0].ptr())) {
            throw Py::TypeError("validateFieldGraph expects (json)");
        }
        return Py::String(FieldGraph::canonicalize(PyUnicode_AsUTF8(args[0].ptr())));
    }
};

PyObject* initModule()
{
    return Base::Interpreter().addModule(new Module);
}

}  // namespace Implicit

PyMOD_INIT_FUNC(Implicit)
{
    PyObject* module = Implicit::initModule();
    Implicit::Feature::init();
#ifdef IMPLICIT_WITH_NATIVE_GEOMETRY
    Implicit::NativeGeometry::init();
    Implicit::PropertyNativeGeometry::init();
    Implicit::NativeFeature::init();
    Implicit::NativeFeaturePython::init();
#endif
    PyMOD_Return(module);
}
