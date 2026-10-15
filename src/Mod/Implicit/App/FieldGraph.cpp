// SPDX-License-Identifier: LGPL-2.1-or-later

#include "FieldGraph.h"
#ifdef IMPLICIT_WITH_OCCT_BRIDGE
# include "BRepField.h"
#endif

#include <cmath>
#include <initializer_list>
#include <stdexcept>
#include <string_view>
#include <utility>

#include <nlohmann/json.hpp>

using Json = nlohmann::json;

namespace Implicit
{

namespace
{

void requireOnlyMembers(const Json& object, std::initializer_list<std::string_view> allowed)
{
    for (const auto& member : object.items()) {
        bool found = false;
        for (const std::string_view name : allowed) {
            if (member.key() == name) {
                found = true;
                break;
            }
        }
        if (!found) {
            throw std::invalid_argument("unexpected field graph member '" + member.key() + "'");
        }
    }
}

double requiredNumber(const Json& object, std::string_view name)
{
    const auto iterator = object.find(name);
    if (iterator == object.end() || !iterator->is_number()) {
        throw std::invalid_argument("field graph member '" + std::string(name) + "' must be a number");
    }
    const double result = iterator->get<double>();
    if (!std::isfinite(result)) {
        throw std::invalid_argument("field graph numbers must be finite");
    }
    return result;
}

Base::Vector3d requiredVector(const Json& object, std::string_view name)
{
    const auto iterator = object.find(name);
    if (iterator == object.end() || !iterator->is_array() || iterator->size() != 3) {
        throw std::invalid_argument(
            "field graph member '" + std::string(name) + "' must be a 3-vector"
        );
    }
    for (const auto& coordinate : *iterator) {
        if (!coordinate.is_number() || !std::isfinite(coordinate.get<double>())) {
            throw std::invalid_argument("field graph vector coordinates must be finite numbers");
        }
    }
    return Base::Vector3d(
        (*iterator)[0].get<double>(),
        (*iterator)[1].get<double>(),
        (*iterator)[2].get<double>()
    );
}

FieldPtr parseNode(const Json& node, std::size_t depth, std::size_t& nodeCount)
{
    if (depth > FieldGraph::MaximumDepth) {
        throw std::invalid_argument("field graph exceeds maximum nesting depth");
    }
    if (++nodeCount > FieldGraph::MaximumNodes) {
        throw std::invalid_argument("field graph exceeds maximum node count");
    }
    if (!node.is_object()) {
        throw std::invalid_argument("field graph node must be an object");
    }
    const auto typeIterator = node.find("type");
    if (typeIterator == node.end() || !typeIterator->is_string()) {
        throw std::invalid_argument("field graph node requires a string 'type'");
    }
    const std::string type = typeIterator->get<std::string>();

    if (type == "constant") {
        requireOnlyMembers(node, {"type", "value"});
        return std::make_shared<LinearField>(Base::Vector3d(), requiredNumber(node, "value"));
    }
    if (type == "linear") {
        requireOnlyMembers(node, {"type", "slope", "intercept"});
        return std::make_shared<LinearField>(
            requiredVector(node, "slope"),
            requiredNumber(node, "intercept")
        );
    }
    if (type == "variable_band" || type == "smooth_union") {
        requireOnlyMembers(
            node,
            type == "variable_band"
                ? std::initializer_list<std::string_view> {"type", "field", "width"}
                : std::initializer_list<std::string_view> {"type", "left", "right", "blend"}
        );
        const char* first = type == "variable_band" ? "field" : "left";
        const char* second = type == "variable_band" ? "width" : "right";
        if (!node.contains(first) || !node.contains(second)) {
            throw std::invalid_argument("composed scalar node requires both operand fields");
        }
        auto a = parseNode(node.at(first), depth + 1, nodeCount);
        auto b = parseNode(node.at(second), depth + 1, nodeCount);
        if (type == "variable_band") {
            return std::make_shared<VariableBandField>(std::move(a), std::move(b));
        }
        return std::make_shared<SmoothUnionField>(
            std::move(a),
            std::move(b),
            requiredNumber(node, "blend")
        );
    }

    if (type == "box") {
        requireOnlyMembers(node, {"type", "center", "halfSize"});
        return std::make_shared<BoxField>(
            requiredVector(node, "center"),
            requiredVector(node, "halfSize")
        );
    }
    if (type == "band") {
        requireOnlyMembers(node, {"type", "field", "halfWidth"});
        if (!node.contains("field")) {
            throw std::invalid_argument("band requires 'field'");
        }
        return std::make_shared<BandField>(
            parseNode(node.at("field"), depth + 1, nodeCount),
            requiredNumber(node, "halfWidth")
        );
    }

#ifdef IMPLICIT_WITH_OCCT_BRIDGE
    if (type == "brep") {
        requireOnlyMembers(node, {"type", "data", "tolerance"});
        if (!node.contains("data") || !node.at("data").is_string()) {
            throw std::invalid_argument("B-Rep node requires a string 'data' snapshot");
        }
        return std::make_shared<BRepField>(
            node.at("data").get<std::string>(),
            requiredNumber(node, "tolerance")
        );
    }
#endif

    if (type == "sphere") {
        requireOnlyMembers(node, {"type", "center", "radius"});
        return std::make_shared<SphereField>(
            requiredVector(node, "center"),
            requiredNumber(node, "radius")
        );
    }
    if (type == "gyroid") {
        requireOnlyMembers(node, {"type", "period", "iso"});
        return std::make_shared<GyroidField>(
            requiredNumber(node, "period"),
            requiredNumber(node, "iso")
        );
    }
    if (type == "translate" || type == "offset") {
        requireOnlyMembers(
            node,
            type == "translate" ? std::initializer_list<std::string_view> {"type", "field", "offset"}
                                : std::initializer_list<std::string_view> {"type", "field", "amount"}
        );
        const auto fieldIterator = node.find("field");
        if (fieldIterator == node.end()) {
            throw std::invalid_argument("unary field graph node requires 'field'");
        }
        FieldPtr field = parseNode(*fieldIterator, depth + 1, nodeCount);
        if (type == "translate") {
            return std::make_shared<TranslateField>(std::move(field), requiredVector(node, "offset"));
        }
        return std::make_shared<OffsetField>(std::move(field), requiredNumber(node, "amount"));
    }

    BooleanOperation operation;
    if (type == "union") {
        operation = BooleanOperation::Union;
    }
    else if (type == "intersection") {
        operation = BooleanOperation::Intersection;
    }
    else if (type == "difference") {
        operation = BooleanOperation::Difference;
    }
    else {
        throw std::invalid_argument("unsupported field graph node type '" + type + "'");
    }

    requireOnlyMembers(node, {"type", "left", "right"});

    const auto leftIterator = node.find("left");
    const auto rightIterator = node.find("right");
    if (leftIterator == node.end() || rightIterator == node.end()) {
        throw std::invalid_argument("Boolean field graph node requires 'left' and 'right'");
    }
    FieldPtr left = parseNode(*leftIterator, depth + 1, nodeCount);
    FieldPtr right = parseNode(*rightIterator, depth + 1, nodeCount);
    return std::make_shared<BooleanField>(operation, std::move(left), std::move(right));
}

Json parseDocument(const std::string& serialized)
{
    if (serialized.empty()) {
        throw std::invalid_argument("field graph JSON must not be empty");
    }
    if (serialized.size() > FieldGraph::MaximumBytes) {
        throw std::invalid_argument("field graph JSON exceeds maximum document size");
    }
    Json document;
    try {
        document = Json::parse(serialized);
    }
    catch (const Json::exception& error) {
        throw std::invalid_argument(std::string("invalid field graph JSON: ") + error.what());
    }
    if (!document.is_object()) {
        throw std::invalid_argument("field graph document must be an object");
    }
    requireOnlyMembers(document, {"schema", "root"});
    const auto schemaIterator = document.find("schema");
    if (schemaIterator == document.end() || !schemaIterator->is_number_integer()
        || schemaIterator->get<int>() != FieldGraph::CurrentSchema) {
        throw std::invalid_argument("unsupported field graph schema");
    }
    if (!document.contains("root")) {
        throw std::invalid_argument("field graph document requires 'root'");
    }
    return document;
}

}  // namespace

FieldPtr FieldGraph::parse(const std::string& serialized)
{
    const Json document = parseDocument(serialized);
    std::size_t nodeCount = 0;
    return parseNode(document.at("root"), 1, nodeCount);
}

std::string FieldGraph::canonicalize(const std::string& serialized)
{
    Json document = parseDocument(serialized);
    std::size_t nodeCount = 0;
    (void)parseNode(document.at("root"), 1, nodeCount);
    return document.dump();
}

}  // namespace Implicit
