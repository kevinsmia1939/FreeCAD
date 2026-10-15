// SPDX-License-Identifier: LGPL-2.1-or-later

#include "Feature.h"

#include "FieldGraph.h"

#include <memory>
#include <stdexcept>
#include <string>
#include <algorithm>
#include <vector>
#include <unordered_set>
#include <functional>

#include <App/DocumentObject.h>
#include <App/Document.h>

#ifdef IMPLICIT_WITH_PART_BRIDGE
# include <Mod/Part/App/PartFeature.h>
# include <BRepTools.hxx>
# include <BRepBndLib.hxx>
# include <Bnd_Box.hxx>
# include <Standard_Failure.hxx>
# include <TopLoc_Location.hxx>
# include <sstream>
# include "BRepField.h"
#endif

using namespace Implicit;

PROPERTY_SOURCE(Implicit::Feature, App::GeoFeature)

const char* Feature::FunctionEnums[] = {"Gyroid", "Sphere", nullptr};
const char* Feature::OperationEnums[]
    = {"Definition", "Union", "Intersection", "Difference", "Band", "Offset", "BRep", nullptr};

Feature::Feature()
{
    ADD_PROPERTY_TYPE(
        Operation,
        (0L),
        "Composition",
        App::Prop_None,
        "Definition or live linked field operation"
    );
    Operation.setEnums(OperationEnums);
    ADD_PROPERTY_TYPE(Left, (nullptr), "Composition", App::Prop_None, "First live field operand");
    ADD_PROPERTY_TYPE(Right, (nullptr), "Composition", App::Prop_None, "Second live field operand");
    ADD_PROPERTY_TYPE(
        Amount,
        (0.3),
        "Composition",
        App::Prop_None,
        "Band half-width or offset, in input field units"
    );
    ADD_PROPERTY_TYPE(
        AutoDomain,
        (true),
        "Composition",
        App::Prop_None,
        "Use transformed operand domain bounds for linked operations"
    );
    ADD_PROPERTY_TYPE(Function, (0L), "Field", App::Prop_None, "Implicit field primitive");
    Function.setEnums(FunctionEnums);
    ADD_PROPERTY_TYPE(Center, (Base::Vector3d()), "Field", App::Prop_None, "Sphere center");
    ADD_PROPERTY_TYPE(Radius, (10.0), "Field", App::Prop_None, "Sphere radius");
    ADD_PROPERTY_TYPE(Period, (10.0), "Field", App::Prop_None, "Gyroid period");
    ADD_PROPERTY_TYPE(IsoValue, (0.0), "Field", App::Prop_None, "Field isovalue");
    ADD_PROPERTY_TYPE(
        DomainMin,
        (Base::Vector3d(-10.0, -10.0, -10.0)),
        "Domain",
        App::Prop_None,
        "Finite evaluation domain minimum"
    );
    ADD_PROPERTY_TYPE(
        DomainMax,
        (Base::Vector3d(10.0, 10.0, 10.0)),
        "Domain",
        App::Prop_None,
        "Finite evaluation domain maximum"
    );
    ADD_PROPERTY_TYPE(Tolerance, (1.0e-9), "Domain", App::Prop_None, "Classification tolerance");
    ADD_PROPERTY_TYPE(
        InsideNegative,
        (true),
        "Domain",
        App::Prop_None,
        "Treat negative field values as inside"
    );
    ADD_PROPERTY_TYPE(
        FieldGraph,
        (""),
        "Field",
        App::Prop_None,
        "Versioned JSON field graph; empty uses the primitive properties"
    );
    ADD_PROPERTY_TYPE(
        SchemaVersion,
        (3),
        "Persistence",
        App::Prop_ReadOnly,
        "Serialized implicit feature schema"
    );
    ADD_PROPERTY_TYPE(
        CacheRevision,
        (0),
        "Display",
        static_cast<App::PropertyType>(App::Prop_Transient | App::Prop_Output | App::Prop_ReadOnly),
        "Transient geometry cache revision"
    );
    ADD_PROPERTY_TYPE(
        StatusMessage,
        (""),
        "Diagnostics",
        static_cast<App::PropertyType>(App::Prop_Transient | App::Prop_Output | App::Prop_ReadOnly),
        "Last implicit execution or dependency error"
    );
}

void Feature::onSettingDocument()
{
    App::GeoFeature::onSettingDocument();
    recomputedConnection.disconnect();
    if (getDocument()) {
        recomputedConnection = getDocument()->signalRecomputed.connect(
            [this](const App::Document&, const std::vector<App::DocumentObject*>&) {
                if (Operation.getValue() == 0 || isRestoring()) {
                    return;
                }
                try {
                    validateDependencies();
                }
                catch (const std::exception& error) {
                    // Document skips downstream execution after a source fails.
                    // Invalidate these skipped results explicitly rather than
                    // leaving a valid-looking cache from a previous recompute.
                    compiledShape.reset();
                    displayMesh.reset();
                    const bool changed = !isError()
                        || std::string(StatusMessage.getValue()) != error.what();
                    setError();
                    StatusMessage.setValue(error.what());
                    if (changed) {
                        CacheRevision.setValue(CacheRevision.getValue() + 1);
                    }
                }
            }
        );
    }
}

void Feature::validateDependencies() const
{
    std::unordered_set<const Feature*> visiting, visited;
    std::function<void(const Feature*, unsigned)> check = [&](const Feature* node, unsigned depth) {
        if (depth >= 128 || visiting.contains(node)) {
            throw std::invalid_argument("cyclic or excessively deep implicit feature dependencies");
        }
        if (visited.contains(node)) {
            return;
        }
        visiting.insert(node);
        const auto operation = node->Operation.getValue();
        if (operation != 0) {
            auto input = [&](const App::DocumentObject* source) {
                if (!source) {
                    throw std::invalid_argument("linked implicit operand is missing");
                }
                if (const auto* field = dynamic_cast<const Feature*>(source)) {
                    check(field, depth + 1);
                }
                if (source->isError()) {
                    throw std::invalid_argument("linked implicit operand is in an error state");
                }
            };
            input(node->Left.getValue());
            if (operation <= 3) {
                input(node->Right.getValue());
            }
        }
        visiting.erase(node);
        visited.insert(node);
    };
    check(this, 0);
}

short Feature::mustExecute() const
{
    return Function.isTouched() || Center.isTouched() || Radius.isTouched() || Period.isTouched()
            || IsoValue.isTouched() || DomainMin.isTouched() || DomainMax.isTouched()
            || Tolerance.isTouched() || InsideNegative.isTouched() || FieldGraph.isTouched()
            || Operation.isTouched() || Left.isTouched() || Right.isTouched() || Amount.isTouched()
            || AutoDomain.isTouched()
        ? 1
        : App::GeoFeature::mustExecute();
}

App::DocumentObjectExecReturn* Feature::execute()
{
    try {
        // Upstream edits schedule this object through PropertyLink dependencies,
        // without necessarily touching one of our own properties.
        if (Operation.getValue() != 0) {
            compiledShape.reset();
        }
        (void)makeShape();
        StatusMessage.setValue("");
        if (Function.isTouched() || Center.isTouched() || Radius.isTouched() || Period.isTouched()
            || IsoValue.isTouched() || DomainMin.isTouched() || DomainMax.isTouched()
            || Tolerance.isTouched() || InsideNegative.isTouched() || FieldGraph.isTouched()
            || Operation.getValue() != 0 || Operation.isTouched() || Left.isTouched()
            || Right.isTouched() || Amount.isTouched() || AutoDomain.isTouched()) {
            displayMesh.reset();
            CacheRevision.setValue(CacheRevision.getValue() + 1);
        }
    }
    catch (const std::exception& error) {
        compiledShape.reset();
        displayMesh.reset();
        StatusMessage.setValue(error.what());
        CacheRevision.setValue(CacheRevision.getValue() + 1);
        return new App::DocumentObjectExecReturn(error.what());
    }
    return App::DocumentObject::StdReturn;
}

std::shared_ptr<const SurfaceMesh> Feature::getDisplayMesh(unsigned int resolution, bool adaptive) const
{
    // Even a cached mesh must not be returned after an upstream failure.
    validateDependencies();
    if (resolution < 2 || resolution > 64) {
        throw std::invalid_argument("display resolution must be between 2 and 64");
    }
    if (adaptive) {
        unsigned int effective = 2;
        while (effective < resolution) {
            effective *= 2;
        }
        resolution = effective;
    }
    if (!displayMesh || displayResolution != resolution || displayAdaptive != adaptive) {
        displayMesh = std::make_shared<SurfaceMesh>(
            adaptive ? Implicit::tessellateAdaptive(makeShape(), resolution)
                     : Implicit::tessellate(makeShape(), resolution)
        );
        displayResolution = resolution;
        displayAdaptive = adaptive;
    }
    return displayMesh;
}

std::shared_ptr<const SurfaceMesh> Feature::cachedDisplayMesh(unsigned int resolution, bool adaptive) const
{
    validateDependencies();
    return displayResolution == resolution && displayAdaptive == adaptive ? displayMesh : nullptr;
}

bool Feature::storeDisplayMesh(
    const Shape& snapshot,
    unsigned int resolution,
    bool adaptive,
    std::shared_ptr<const SurfaceMesh> mesh
)
{
    const auto current = makeShape();
    if (!mesh || current.getField() != snapshot.getField()
        || current.getDomain().minimum != snapshot.getDomain().minimum
        || current.getDomain().maximum != snapshot.getDomain().maximum
        || current.isInsideNegative() != snapshot.isInsideNegative()) {
        return false;
    }
    displayMesh = std::move(mesh);
    displayResolution = resolution;
    displayAdaptive = adaptive;
    return true;
}

Shape Feature::makeShape() const
{
    // Defend API queries as well as document recompute against malformed links.
    static thread_local std::vector<const Feature*> active;
    if (active.empty()) {
        validateDependencies();
    }
    if (std::find(active.begin(), active.end(), this) != active.end() || active.size() >= 128) {
        throw std::invalid_argument("cyclic or excessively deep implicit feature dependencies");
    }
    struct Guard
    {
        std::vector<const Feature*>& stack;
        ~Guard()
        {
            stack.pop_back();
        }
    };
    active.push_back(this);
    Guard guard {active};
    if (compiledShape) {
        return *compiledShape;
    }
    FieldPtr field;
    Domain domain {DomainMin.getValue(), DomainMax.getValue()};
    const auto operation = Operation.getValue();
    const std::string serializedGraph = FieldGraph.getValue();
    if (operation != 0) {
        bool firstDomain = true;
        // Operands are assembled in this object's parent frame. Its own
        // Placement is an additional object transform, not a change of basis
        // that would cancel the user's attempt to move the result.
        const auto targetPlacement = App::GeoFeature::getGlobalPlacement(this)
            * Placement.getValue().inverse();
        auto includeDomain = [&](const Domain& bounds, const Base::Placement& placement) {
            if (!AutoDomain.getValue()) {
                return;
            }
            for (unsigned corner = 0; corner < 8; ++corner) {
                Base::Vector3d point;
                placement.multVec(
                    Base::Vector3d(
                        corner & 1 ? bounds.maximum.x : bounds.minimum.x,
                        corner & 2 ? bounds.maximum.y : bounds.minimum.y,
                        corner & 4 ? bounds.maximum.z : bounds.minimum.z
                    ),
                    point
                );
                if (firstDomain) {
                    domain = {point, point};
                    firstDomain = false;
                }
                else {
                    domain.minimum.x = std::min(domain.minimum.x, point.x);
                    domain.minimum.y = std::min(domain.minimum.y, point.y);
                    domain.minimum.z = std::min(domain.minimum.z, point.z);
                    domain.maximum.x = std::max(domain.maximum.x, point.x);
                    domain.maximum.y = std::max(domain.maximum.y, point.y);
                    domain.maximum.z = std::max(domain.maximum.z, point.z);
                }
            }
        };
        auto brepOperand = [&](App::DocumentObject* object) -> FieldPtr {
#ifdef IMPLICIT_WITH_PART_BRIDGE
            try {
                const auto* source = dynamic_cast<const Part::Feature*>(object);
                if (!source || source->isError()) {
                    throw std::invalid_argument("BRep operation requires a valid Part feature");
                }
                auto shape = source->Shape.getValue();
                if (shape.IsNull()) {
                    throw std::invalid_argument("live BRep source has no shape");
                }
                // Part's top-level location mirrors its Placement. Strip it before
                // applying the global document placement exactly once below.
                shape.Location(TopLoc_Location());
                std::ostringstream stream;
                BRepTools::Write(shape, stream);
                const auto placement = targetPlacement.inverse()
                    * App::GeoFeature::getGlobalPlacement(source);
                const auto distance = std::make_shared<BRepField>(stream.str(), Tolerance.getValue());
                if (AutoDomain.getValue()) {
                    Bnd_Box bounds;
                    BRepBndLib::Add(shape, bounds);
                    double xmin, ymin, zmin, xmax, ymax, zmax;
                    bounds.Get(xmin, ymin, zmin, xmax, ymax, zmax);
                    const double margin = std::max(
                        Base::Vector3d(xmax - xmin, ymax - ymin, zmax - zmin).Length() * 0.05,
                        1.0
                    );
                    includeDomain(
                        {Base::Vector3d(xmin - margin, ymin - margin, zmin - margin),
                         Base::Vector3d(xmax + margin, ymax + margin, zmax + margin)},
                        placement
                    );
                }
                return std::make_shared<PlacedField>(distance, placement);
            }
            catch (const Standard_Failure& error) {
                throw std::invalid_argument(error.GetMessageString());
            }
#else
            (void)object;
            throw std::invalid_argument("live BRep support requires Part and the OCCT bridge");
#endif
        };
        auto operand = [&](App::DocumentObject* object) -> FieldPtr {
            const auto* source = dynamic_cast<const Feature*>(object);
            if (!source) {
                return brepOperand(object);
            }
            if (source->isError()) {
                throw std::invalid_argument("linked implicit operand is in an error state");
            }
            const auto shape = source->makeShape();
            const auto placement = targetPlacement.inverse()
                * App::GeoFeature::getGlobalPlacement(source);
            includeDomain(shape.getDomain(), placement);
            return std::make_shared<PlacedField>(
                shape.getField(),
                placement,
                shape.isInsideNegative() ? 1.0 : -1.0
            );
        };
        if (operation == 6) {
            field = brepOperand(Left.getValue());
        }
        else if (operation <= 3) {
            const auto boolean = operation == 1 ? BooleanOperation::Union
                : operation == 2                ? BooleanOperation::Intersection
                                                : BooleanOperation::Difference;
            field = std::make_shared<BooleanField>(
                boolean,
                operand(Left.getValue()),
                operand(Right.getValue())
            );
        }
        else if (operation == 4) {
            field = std::make_shared<BandField>(operand(Left.getValue()), Amount.getValue());
        }
        else {
            field = std::make_shared<OffsetField>(operand(Left.getValue()), Amount.getValue());
        }
        // Linked operations canonicalize operands but retain this feature's
        // explicitly selected inside convention in both value and classification.
        if (!InsideNegative.getValue()) {
            field = std::make_shared<PlacedField>(field, Base::Placement(), -1.0);
        }
    }
    else if (!serializedGraph.empty()) {
        field = Implicit::FieldGraph::parse(serializedGraph);
    }
    else if (Function.getValue() == 0) {
        field = std::make_shared<GyroidField>(Period.getValue(), IsoValue.getValue());
    }
    else {
        field = std::make_shared<SphereField>(Center.getValue(), Radius.getValue());
    }
    compiledShape.emplace(std::move(field), domain, Tolerance.getValue(), InsideNegative.getValue());
    return *compiledShape;
}

bool Feature::affectsField(const App::Property* property) const
{
    return property == &Function || property == &Center || property == &Radius || property == &Period
        || property == &IsoValue || property == &DomainMin || property == &DomainMax
        || property == &Tolerance || property == &InsideNegative || property == &FieldGraph
        || property == &Operation || property == &Left || property == &Right || property == &Amount
        || property == &AutoDomain || (property == &Placement && Operation.getValue() != 0);
}

void Feature::onChanged(const App::Property* property)
{
    if (affectsField(property)) {
        compiledShape.reset();
        displayMesh.reset();
    }
    App::GeoFeature::onChanged(property);
}
