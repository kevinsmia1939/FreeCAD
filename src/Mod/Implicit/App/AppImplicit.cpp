// SPDX-License-Identifier: LGPL-2.1-or-later

#include <App/DocumentObjectPy.h>
#include <Base/Interpreter.h>
#include <Base/PyObjectBase.h>

#include "Feature.h"
#include "FieldGraph.h"

namespace Implicit
{

namespace
{

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
    return Base::Vector3d(
        PyFloat_AsDouble(args[offset].ptr()),
        PyFloat_AsDouble(args[offset + 1].ptr()),
        PyFloat_AsDouble(args[offset + 2].ptr())
    );
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
        add_varargs_method("gradient", &Module::gradient, "gradient(feature, x, y, z) -> (dx, dy, dz)");
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
        initialize("Native implicit geometry primitives for FreeCAD.");
    }

private:
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
    PyMOD_Return(module);
}
