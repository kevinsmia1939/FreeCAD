// SPDX-License-Identifier: LGPL-2.1-or-later

#include "SurfaceMesh.h"

#include <algorithm>
#include <cmath>
#include <limits>
#include <stdexcept>
#include <unordered_map>
#include <utility>

namespace Implicit
{
namespace
{

constexpr std::array<std::array<unsigned int, 4>, 6> tetrahedra {{
    {{0, 5, 1, 6}},
    {{0, 1, 2, 6}},
    {{0, 2, 3, 6}},
    {{0, 3, 7, 6}},
    {{0, 7, 4, 6}},
    {{0, 4, 5, 6}},
}};
constexpr std::size_t maxMeshElements = 1000000;
using Edge = std::pair<std::size_t, std::size_t>;

struct EdgeHash
{
    std::size_t operator()(const Edge& edge) const
    {
        return std::hash<std::size_t>()(edge.first) ^ (std::hash<std::size_t>()(edge.second) << 1);
    }
};

class Extractor
{
public:
    Extractor(const Shape& shape, unsigned int resolution, bool adaptive, const std::atomic_bool* cancelled)
        : shape(shape)
        , resolution(resolution)
        , width(static_cast<std::size_t>(resolution) + 1)
        , adaptive(adaptive)
        , cancelled(cancelled)
    {}

    SurfaceMesh run()
    {
        checkCancellation();
        samples.resize(width * width * width, std::numeric_limits<double>::quiet_NaN());
        if (adaptive) {
            block(0, 0, 0, resolution);
            return std::move(mesh);
        }
        for (std::size_t id = 0; id < samples.size(); ++id) {
            sample(id);
        }

        for (std::size_t z = 0; z < resolution; ++z) {
            for (std::size_t y = 0; y < resolution; ++y) {
                for (std::size_t x = 0; x < resolution; ++x) {
                    cell(x, y, z);
                }
            }
        }
        return std::move(mesh);
    }

private:
    void checkCancellation() const
    {
        if (cancelled && cancelled->load(std::memory_order_relaxed)) {
            throw std::runtime_error("implicit operation cancelled");
        }
    }

    double sample(std::size_t id)
    {
        if (std::isnan(samples[id])) {
            samples[id] = checkedValue(point(id));
            ++mesh.sampleCount;
        }
        return samples[id];
    }

    void cell(std::size_t x, std::size_t y, std::size_t z)
    {
        checkCancellation();
        const std::size_t base = z * width * width + y * width + x;
        const std::array<std::size_t, 8> cube {
            {base,
             base + 1,
             base + width + 1,
             base + width,
             base + width * width,
             base + width * width + 1,
             base + width * width + width + 1,
             base + width * width + width}
        };
        for (const auto id : cube) {
            sample(id);
        }
        for (const auto& tetrahedron : tetrahedra) {
            polygonise(cube, tetrahedron);
        }
    }

    void block(std::size_t x, std::size_t y, std::size_t z, std::size_t span)
    {
        checkCancellation();
        if (span == 1) {
            cell(x, y, z);
            return;
        }
        const auto half = span / 2;
        const double bound = shape.lipschitzBound();
        if (std::isfinite(bound)) {
            const auto center = (z + half) * width * width + (y + half) * width + x + half;
            const auto diagonal = point((z + span) * width * width + (y + span) * width + x + span)
                - point(z * width * width + y * width + x);
            const double radiusBound = bound * diagonal.Length() * 0.5;
            // A small relative margin accommodates ordinary floating-point error;
            // this is not an interval-arithmetic proof for arbitrary coordinates.
            if (std::abs(sample(center)) > radiusBound * (1.0 + 1.0e-12) + 1.0e-12) {
                ++mesh.prunedBlocks;
                return;
            }
        }
        for (std::size_t dz = 0; dz < 2; ++dz) {
            for (std::size_t dy = 0; dy < 2; ++dy) {
                for (std::size_t dx = 0; dx < 2; ++dx) {
                    block(x + dx * half, y + dy * half, z + dz * half, half);
                }
            }
        }
    }

    Base::Vector3d point(std::size_t id) const
    {
        const auto& domain = shape.getDomain();
        const Base::Vector3d extent = domain.maximum - domain.minimum;
        return domain.minimum
            + Base::Vector3d(
                   extent.x * static_cast<double>(id % width) / resolution,
                   extent.y * static_cast<double>((id / width) % width) / resolution,
                   extent.z * static_cast<double>(id / (width * width)) / resolution
            );
    }

    double checkedValue(const Base::Vector3d& position) const
    {
        checkCancellation();
        const double value = shape.value(position);
        if (!std::isfinite(value)) {
            throw std::runtime_error("non-finite field value during tessellation");
        }
        return value;
    }

    std::size_t vertex(std::size_t a, std::size_t b)
    {
        if (a > b) {
            std::swap(a, b);
        }
        // Every edge ending on a zero-valued grid node must share that node.
        const Edge key = samples[a] == 0.0 ? Edge {a, a}
            : samples[b] == 0.0            ? Edge {b, b}
                                           : Edge {a, b};
        if (const auto found = edges.find(key); found != edges.end()) {
            return found->second;
        }
        if (mesh.vertices.size() >= maxMeshElements) {
            throw std::runtime_error("tessellation vertex budget exceeded; lower resolution");
        }

        Base::Vector3d position = point(key.first);
        if (key.first != key.second) {
            Base::Vector3d low = point(a);
            Base::Vector3d high = point(b);
            double lowValue = samples[a];
            // Fixed bisection gives deterministic, bounded edge-root refinement.
            // It does not guarantee finding multiple roots along a sampled edge.
            for (unsigned int iteration = 0; iteration < 24; ++iteration) {
                position = low + (high - low) * 0.5;
                const double value = checkedValue(position);
                if (value == 0.0) {
                    break;
                }
                if ((value < 0.0) == (lowValue < 0.0)) {
                    low = position;
                    lowValue = value;
                }
                else {
                    high = position;
                }
            }
        }

        Base::Vector3d normal = shape.gradient(position);
        const double length = normal.Length();
        if (!std::isfinite(length)) {
            throw std::runtime_error("non-finite field gradient during tessellation");
        }
        if (length > 0.0) {
            normal /= shape.isInsideNegative() ? length : -length;
        }
        const std::size_t index = mesh.vertices.size();
        // Preserve the linear tetrahedron's orientation even when root
        // refinement crosses a hard field-gradient branch boundary.
        referenceVertices.push_back(
            key.first == key.second
                ? point(key.first)
                : point(a) + (point(b) - point(a)) * (samples[a] / (samples[a] - samples[b]))
        );
        mesh.vertices.push_back(position);
        mesh.normals.push_back(normal);
        edges.emplace(key, index);
        return index;
    }

    void triangle(std::size_t a, std::size_t b, std::size_t c, const Base::Vector3d& outward)
    {
        if (a == b || b == c || c == a) {
            return;
        }
        const auto normal
            = (mesh.vertices[b] - mesh.vertices[a]).Cross(mesh.vertices[c] - mesh.vertices[a]);
        if (normal.Sqr() == 0.0) {
            return;
        }
        const auto referenceNormal = (referenceVertices[b] - referenceVertices[a])
                                         .Cross(referenceVertices[c] - referenceVertices[a]);
        if (referenceNormal.Dot(outward) < 0.0) {
            std::swap(b, c);
        }
        if (mesh.triangles.size() >= maxMeshElements) {
            throw std::runtime_error("tessellation triangle budget exceeded; lower resolution");
        }
        mesh.triangles.push_back({a, b, c});
    }

    void polygonise(const std::array<std::size_t, 8>& cube, const std::array<unsigned int, 4>& tetrahedron)
    {
        std::array<std::size_t, 4> inside {};
        std::array<std::size_t, 4> outside {};
        std::size_t count = 0;
        std::size_t otherCount = 0;
        for (const auto corner : tetrahedron) {
            const auto id = cube[corner];
            if (samples[id] <= 0.0) {
                inside[count++] = id;
            }
            else {
                outside[otherCount++] = id;
            }
        }
        if (count == 0 || count == 4) {
            return;
        }
        const auto outward = (point(outside[0]) - point(inside[0]))
            * (shape.isInsideNegative() ? 1.0 : -1.0);
        if (count == 1 || count == 3) {
            const auto singleton = count == 1 ? inside[0] : outside[0];
            const auto& others = count == 1 ? outside : inside;
            const auto a = vertex(singleton, others[0]);
            const auto b = vertex(singleton, others[1]);
            const auto c = vertex(singleton, others[2]);
            triangle(a, b, c, outward);
            return;
        }
        const auto a = vertex(inside[0], outside[0]);
        const auto b = vertex(inside[0], outside[1]);
        const auto c = vertex(inside[1], outside[0]);
        const auto d = vertex(inside[1], outside[1]);
        triangle(a, b, c, outward);
        triangle(b, d, c, outward);
    }

    const Shape& shape;
    unsigned int resolution;
    std::size_t width;
    bool adaptive;
    const std::atomic_bool* cancelled;
    SurfaceMesh mesh;
    std::vector<Base::Vector3d> referenceVertices;
    std::vector<double> samples;
    std::unordered_map<Edge, std::size_t, EdgeHash> edges;
};

}  // namespace

SurfaceMesh tessellate(const Shape& shape, unsigned int resolution, const std::atomic_bool* cancelled)
{
    if (resolution < 2 || resolution > 64) {
        throw std::invalid_argument("tessellation resolution must be between 2 and 64");
    }
    return Extractor(shape, resolution, false, cancelled).run();
}

SurfaceMesh tessellateAdaptive(const Shape& shape, unsigned int resolution, const std::atomic_bool* cancelled)
{
    if (resolution < 2 || resolution > 64 || (resolution & (resolution - 1)) != 0) {
        throw std::invalid_argument("adaptive resolution must be a power of two between 2 and 64");
    }
    return Extractor(shape, resolution, true, cancelled).run();
}

MeshQuality inspectMesh(const Shape& shape, const SurfaceMesh& mesh, const std::atomic_bool* cancelled)
{
    MeshQuality quality;
    const auto check = [cancelled] {
        if (cancelled && cancelled->load(std::memory_order_relaxed)) {
            throw std::runtime_error("implicit operation cancelled");
        }
    };
    check();
    const double lipschitz = shape.lipschitzBound();
    const bool bounded = std::isfinite(lipschitz) && lipschitz >= 0;
    if (!bounded) {
        quality.maxTriangleResidualBound = std::numeric_limits<double>::infinity();
    }
    struct Incidence
    {
        std::size_t count = 0;
        long orientation = 0;
    };
    std::unordered_map<Edge, Incidence, EdgeHash> edges;
    for (const auto& vertex : mesh.vertices) {
        check();
        quality.maxVertexResidual = std::max(quality.maxVertexResidual, std::abs(shape.value(vertex)));
    }
    for (const auto& triangle : mesh.triangles) {
        check();
        const auto& a = mesh.vertices.at(triangle[0]);
        const auto& b = mesh.vertices.at(triangle[1]);
        const auto& c = mesh.vertices.at(triangle[2]);
        const auto normal = (b - a).Cross(c - a);
        if (std::hypot(normal.x, normal.y, normal.z) == 0) {
            ++quality.degenerateTriangles;
        }
        const auto center = a / 3 + b / 3 + c / 3;
        const double residual = std::abs(shape.value(center));
        quality.maxCentroidResidual = std::max(quality.maxCentroidResidual, residual);
        if (bounded) {
            const auto norm = [](const Base::Vector3d& v) {
                return std::hypot(v.x, v.y, v.z);
            };
            const double radius = std::max({norm(a - center), norm(b - center), norm(c - center)});
            // Every point of the triangle lies within this radius of its centroid.
            // Floating-point allowance, not an interval-arithmetic certificate.
            const double bound = (residual + lipschitz * radius) * (1 + 1e-12) + 1e-12;
            quality.maxTriangleResidualBound = std::max(quality.maxTriangleResidualBound, bound);
        }
        for (int side = 0; side < 3; ++side) {
            const auto first = triangle[side];
            const auto second = triangle[(side + 1) % 3];
            const Edge key(std::min(first, second), std::max(first, second));
            auto& edge = edges[key];
            if (edge.count == 0) {
                quality.maxEdgeMidpointResidual = std::max(
                    quality.maxEdgeMidpointResidual,
                    std::abs(shape.value(mesh.vertices[first] / 2 + mesh.vertices[second] / 2))
                );
            }
            ++edge.count;
            edge.orientation += first < second ? 1 : -1;
        }
    }
    for (const auto& [key, edge] : edges) {
        check();
        if (edge.count == 1) {
            ++quality.boundaryEdges;
        }
        else if (edge.count != 2) {
            ++quality.nonManifoldEdges;
        }
        else if (edge.orientation != 0) {
            ++quality.inconsistentEdges;
        }
    }
    return quality;
}

ControlledMesh tessellateControlled(
    const Shape& shape,
    double fieldTolerance,
    unsigned int minimumResolution,
    unsigned int maximumResolution,
    const std::atomic_bool* cancelled
)
{
    const auto validResolution = [](unsigned int resolution) {
        return resolution >= 2 && resolution <= 64 && (resolution & (resolution - 1)) == 0;
    };
    if (!std::isfinite(fieldTolerance) || fieldTolerance <= 0 || !validResolution(minimumResolution)
        || !validResolution(maximumResolution) || minimumResolution > maximumResolution) {
        throw std::invalid_argument(
            "controlled extraction requires a positive finite field tolerance "
            "and ordered power-of-two resolutions in 2..64"
        );
    }
    if (!std::isfinite(shape.lipschitzBound()) || shape.lipschitzBound() < 0) {
        throw std::invalid_argument(
            "controlled extraction requires a finite conservative field Lipschitz bound"
        );
    }
    ControlledMesh result;
    for (unsigned int resolution = minimumResolution; resolution <= maximumResolution;
         resolution *= 2) {
        // Drop the previous full mesh before allocating the next level.
        result.mesh = SurfaceMesh();
        result.mesh = tessellateAdaptive(shape, resolution, cancelled);
        result.quality = inspectMesh(shape, result.mesh, cancelled);
        result.history.push_back(
            {resolution, result.mesh.triangles.size(), result.quality.maxTriangleResidualBound}
        );
        if (!result.mesh.triangles.empty()
            && result.quality.maxTriangleResidualBound <= fieldTolerance) {
            result.toleranceMet = true;
            result.status = "field_bound_met";
            return result;
        }
    }
    if (result.mesh.triangles.empty()) {
        result.status = "empty_unverified";
    }
    return result;
}

}  // namespace Implicit
