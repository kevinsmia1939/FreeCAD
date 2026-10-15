// SPDX-License-Identifier: LGPL-2.1-or-later
#include "ViewProviderShape.h"

#include <Inventor/nodes/SoCoordinate3.h>
#include <Inventor/nodes/SoDrawStyle.h>
#include <Inventor/nodes/SoIndexedFaceSet.h>
#include <Inventor/nodes/SoMaterial.h>
#include <Inventor/nodes/SoNormal.h>
#include <Inventor/nodes/SoNormalBinding.h>
#include <Inventor/nodes/SoSeparator.h>
#include <Inventor/nodes/SoShapeHints.h>
#include <Base/Console.h>
#include <Mod/Implicit/App/Feature.h>
#include <QFutureWatcher>
#include <QThreadPool>
#include <QtConcurrent/QtConcurrentRun>
#include <optional>
#include <stdexcept>

namespace
{
// Bound simultaneous extraction memory/CPU independently of Qt's global pool.
QThreadPool& meshPool()
{
    struct Pool: QThreadPool
    {
        Pool()
        {
            setMaxThreadCount(1);
        }
    };
    static Pool pool;
    return pool;
}
}  // namespace

struct ImplicitGui::ViewProviderShape::BackgroundState
{
    struct Request
    {
        Implicit::Shape shape;
        unsigned int resolution;
        bool adaptive;
        long generation;
        std::shared_ptr<std::atomic_bool> cancelled;
    };
    struct Result
    {
        std::shared_ptr<const Implicit::SurfaceMesh> mesh;
        std::string error;
    };
    QObject context;
    QFutureWatcher<Result> watcher {&context};
    std::optional<Request> active;
    std::optional<Request> pending;
};

using namespace ImplicitGui;
PROPERTY_SOURCE(ImplicitGui::ViewProviderShape, Gui::ViewProviderGeometryObject)

ViewProviderShape::ViewProviderShape()
{
    background = std::make_unique<BackgroundState>();
    QObject::connect(
        &background->watcher,
        &QFutureWatcher<BackgroundState::Result>::finished,
        &background->context,
        [this] { finishBackground(); }
    );
    const auto output = static_cast<App::PropertyType>(
        App::Prop_ReadOnly | App::Prop_Transient | App::Prop_Output
    );
    ADD_PROPERTY_TYPE(
        BackgroundMeshing,
        (false),
        "Meshing",
        App::Prop_None,
        "Extract display meshes on a bounded background worker (experimental)"
    );
    ADD_PROPERTY_TYPE(
        CancelMeshing,
        (false),
        "Meshing",
        App::Prop_Transient,
        "Cancel background extraction; automatically resets to false"
    );
    ADD_PROPERTY_TYPE(Meshing, (false), "Meshing", output, "Background work remains outstanding");
    ADD_PROPERTY_TYPE(MeshStatus, ("Idle"), "Meshing", output, "Display extraction status");
    ADD_PROPERTY_TYPE(MeshRequestId, (0), "Meshing", output, "Latest display request generation");
    ADD_PROPERTY_TYPE(DisplayedRequestId, (0), "Meshing", output, "Uploaded generation, or zero");
    ADD_PROPERTY_TYPE(MeshJobCount, (0), "Meshing", output, "Background jobs dispatched this session");
    static const App::PropertyIntegerConstraint::Constraints range = {2, 64, 1};
    ADD_PROPERTY_TYPE(Resolution, (24), "Display", App::Prop_None, "Grid cells per domain axis");
    Resolution.setConstraints(&range);
    ADD_PROPERTY_TYPE(
        AdaptiveSampling,
        (true),
        "Display",
        App::Prop_None,
        "Octree empty-space pruning; resolution rounds up to a power of two"
    );
    ADD_PROPERTY_TYPE(
        SurfaceColor,
        (Base::Color(0.2f, 0.7f, 0.85f)),
        "Display",
        App::Prop_None,
        "Implicit surface color"
    );
    ADD_PROPERTY_TYPE(
        TriangleCount,
        (0),
        "Display",
        static_cast<App::PropertyType>(App::Prop_ReadOnly | App::Prop_Transient),
        "Display cache triangle count"
    );
    ADD_PROPERTY_TYPE(
        CacheBuildCount,
        (0),
        "Display",
        static_cast<App::PropertyType>(App::Prop_ReadOnly | App::Prop_Transient),
        "Display buffer uploads this session"
    );

    coordinates = new SoCoordinate3;
    coordinates->setName("ImplicitCoordinates");
    normals = new SoNormal;
    faces = new SoIndexedFaceSet;
    faces->setName("ImplicitFaces");
    auto* binding = new SoNormalBinding;
    binding->value = SoNormalBinding::PER_VERTEX_INDEXED;
    auto* hints = new SoShapeHints;
    hints->vertexOrdering = SoShapeHints::COUNTERCLOCKWISE;
    shaded = new SoSeparator;
    shaded->ref();
    for (SoNode* node :
         std::array<SoNode*, 6> {pcShapeMaterial, hints, coordinates, normals, binding, faces}) {
        shaded->addChild(node);
    }
    wire = new SoSeparator;
    wire->ref();
    auto* style = new SoDrawStyle;
    style->style = SoDrawStyle::LINES;
    auto* material = new SoMaterial;
    material->diffuseColor.setValue(0.05f, 0.05f, 0.05f);
    wire->addChild(material);
    wire->addChild(style);
    wire->addChild(coordinates);
    wire->addChild(faces);
    combined = new SoSeparator;
    combined->ref();
    combined->addChild(shaded);
    combined->addChild(wire);
    pcShapeMaterial->diffuseColor.setValue(0.2f, 0.7f, 0.85f);
}

ViewProviderShape::~ViewProviderShape()
{
    if (background->active) {
        background->active->cancelled->store(true, std::memory_order_relaxed);
    }
    // Disconnect queued GUI delivery without waiting for the pure-native worker.
    // The job owns its immutable field snapshot and cancellation token.
    background.reset();
    combined->unref();
    wire->unref();
    shaded->unref();
}

void ViewProviderShape::attach(App::DocumentObject* object)
{
    Gui::ViewProviderGeometryObject::attach(object);
    addDisplayMaskMode(shaded, "Shaded");
    addDisplayMaskMode(wire, "Wireframe");
    addDisplayMaskMode(combined, "Flat Lines");
    updateMesh();
}

void ViewProviderShape::setDisplayMode(const char* mode)
{
    setDisplayMaskMode(mode);
    Gui::ViewProviderGeometryObject::setDisplayMode(mode);
}

std::vector<std::string> ViewProviderShape::getDisplayModes() const
{
    return {"Shaded", "Wireframe", "Flat Lines"};
}

const char* ViewProviderShape::getDefaultDisplayMode() const
{
    return "Shaded";
}

void ViewProviderShape::updateData(const App::Property* property)
{
    Gui::ViewProviderGeometryObject::updateData(property);
    const auto* feature = freecad_cast<Implicit::Feature*>(getObject());
    if (feature && property == &feature->CacheRevision) {
        updateMesh();
    }
    else if (feature && BackgroundMeshing.getValue() && feature->affectsField(property)) {
        cancelBackground();
        clearMesh();
        MeshStatus.setValue("Waiting for recompute");
    }
}

void ViewProviderShape::startRestoring()
{
    cancelBackground();
    clearMesh();
    Gui::ViewProviderGeometryObject::startRestoring();
}

void ViewProviderShape::finishRestoring()
{
    Gui::ViewProviderGeometryObject::finishRestoring();
    uploadedMesh.reset();
    updateMesh();
}

void ViewProviderShape::onChanged(const App::Property* property)
{
    Gui::ViewProviderGeometryObject::onChanged(property);
    if ((property == &Resolution || property == &AdaptiveSampling || property == &BackgroundMeshing
         || (property == &Visibility && BackgroundMeshing.getValue()))
        && getObject() && !isRestoring()) {
        updateMesh();
    }
    if (property == &CancelMeshing && CancelMeshing.getValue()) {
        if (background->active || background->pending) {
            cancelBackground();
            MeshStatus.setValue("Cancelled");
        }
        CancelMeshing.setValue(false);
    }
    if (property == &SurfaceColor && pcShapeMaterial) {
        const auto color = SurfaceColor.getValue();
        pcShapeMaterial->diffuseColor.setValue(color.r, color.g, color.b);
    }
}

void ViewProviderShape::updateMesh()
{
    if (isRestoring()) {
        return;
    }
    auto* feature = freecad_cast<Implicit::Feature*>(getObject());
    if (!feature) {
        return;
    }
    cancelBackground();
    try {
        if (Resolution.getValue() < 2 || Resolution.getValue() > 64) {
            throw std::invalid_argument("display resolution must be between 2 and 64");
        }
        auto resolution = static_cast<unsigned int>(Resolution.getValue());
        const bool adaptive = AdaptiveSampling.getValue();
        if (adaptive) {
            unsigned int effective = 2;
            while (effective < resolution) {
                effective *= 2;
            }
            resolution = effective;
        }
        if (!BackgroundMeshing.getValue()) {
            uploadMesh(feature->getDisplayMesh(resolution, adaptive));
            DisplayedRequestId.setValue(MeshRequestId.getValue());
            MeshStatus.setValue("Ready");
            return;
        }
        if (!Visibility.getValue()) {
            clearMesh();
            MeshStatus.setValue("Hidden");
            return;
        }
        // Only this main-thread region touches document objects. No worker ever
        // receives a document/view-provider pointer or accesses Coin/Python.
        const auto snapshot = feature->makeShape();
        if (const auto cached = feature->cachedDisplayMesh(resolution, adaptive)) {
            uploadMesh(cached);
            DisplayedRequestId.setValue(MeshRequestId.getValue());
            MeshStatus.setValue("Ready");
            return;
        }
        clearMesh();
        background->pending.emplace(
            BackgroundState::Request {
                snapshot,
                resolution,
                adaptive,
                MeshRequestId.getValue(),
                std::make_shared<std::atomic_bool>(false)
            }
        );
        Meshing.setValue(true);
        MeshStatus.setValue("Queued");
        startBackground();
    }
    catch (const std::exception& error) {
        clearMesh();
        MeshStatus.setValue((std::string("Error: ") + error.what()).c_str());
        Base::Console().error("Implicit display: {}\n", error.what());
    }
}

void ViewProviderShape::cancelBackground()
{
    MeshRequestId.setValue(MeshRequestId.getValue() + 1);
    background->pending.reset();
    if (background->active) {
        background->active->cancelled->store(true, std::memory_order_relaxed);
    }
    Meshing.setValue(background->active.has_value());
}

void ViewProviderShape::startBackground()
{
    if (background->active || !background->pending) {
        return;
    }
    background->active = std::move(background->pending);
    background->pending.reset();
    const auto request = *background->active;
    MeshStatus.setValue("Meshing");
    MeshJobCount.setValue(MeshJobCount.getValue() + 1);
    background->watcher.setFuture(QtConcurrent::run(&meshPool(), [request] {
        BackgroundState::Result result;
        try {
            result.mesh = std::make_shared<Implicit::SurfaceMesh>(
                request.adaptive
                    ? Implicit::tessellateAdaptive(
                          request.shape,
                          request.resolution,
                          request.cancelled.get()
                      )
                    : Implicit::tessellate(request.shape, request.resolution, request.cancelled.get())
            );
        }
        catch (const std::exception& error) {
            result.error = error.what();
        }
        catch (...) {
            result.error = "unknown background extraction failure";
        }
        return result;
    }));
}

void ViewProviderShape::finishBackground()
{
    if (!background->active) {
        return;
    }
    const auto request = *background->active;
    background->active.reset();
    const bool current = request.generation == MeshRequestId.getValue()
        && BackgroundMeshing.getValue() && !request.cancelled->load(std::memory_order_relaxed);
    try {
        // Consume even obsolete results: otherwise the watcher can retain a
        // large discarded mesh indefinitely after an error/cancellation.
        auto future = background->watcher.future();
        const auto result = future.takeResult();
        if (current) {
            if (!result.error.empty()) {
                throw std::runtime_error(result.error);
            }
            auto* feature = freecad_cast<Implicit::Feature*>(getObject());
            if (feature
                && feature->storeDisplayMesh(
                    request.shape,
                    request.resolution,
                    request.adaptive,
                    result.mesh
                )) {
                uploadMesh(result.mesh);
                DisplayedRequestId.setValue(request.generation);
                MeshStatus.setValue("Ready");
            }
            else {
                clearMesh();
                MeshStatus.setValue("Waiting for recompute");
            }
        }
    }
    catch (const std::exception& error) {
        if (current) {
            clearMesh();
            MeshStatus.setValue((std::string("Error: ") + error.what()).c_str());
        }
    }
    Meshing.setValue(background->pending.has_value());
    startBackground();
}

void ViewProviderShape::clearMesh()
{
    coordinates->point.setNum(0);
    normals->vector.setNum(0);
    faces->coordIndex.setNum(0);
    uploadedMesh.reset();
    TriangleCount.setValue(0);
    DisplayedRequestId.setValue(0);
}

void ViewProviderShape::uploadMesh(std::shared_ptr<const Implicit::SurfaceMesh> mesh)
{
    if (mesh == uploadedMesh) {
        return;
    }
    coordinates->point.setNum(static_cast<int>(mesh->vertices.size()));
    normals->vector.setNum(static_cast<int>(mesh->normals.size()));
    auto* points = coordinates->point.startEditing();
    auto* directions = normals->vector.startEditing();
    for (std::size_t i = 0; i < mesh->vertices.size(); ++i) {
        const auto& point = mesh->vertices[i];
        const auto& normal = mesh->normals[i];
        points[i].setValue(point.x, point.y, point.z);
        directions[i].setValue(normal.x, normal.y, normal.z);
    }
    coordinates->point.finishEditing();
    normals->vector.finishEditing();
    faces->coordIndex.setNum(static_cast<int>(mesh->triangles.size() * 4));
    auto* indices = faces->coordIndex.startEditing();
    std::size_t offset = 0;
    for (const auto& triangle : mesh->triangles) {
        for (auto index : triangle) {
            indices[offset++] = static_cast<int32_t>(index);
        }
        indices[offset++] = -1;
    }
    faces->coordIndex.finishEditing();
    TriangleCount.setValue(static_cast<long>(mesh->triangles.size()));
    CacheBuildCount.setValue(CacheBuildCount.getValue() + 1);
    uploadedMesh = mesh;
}
