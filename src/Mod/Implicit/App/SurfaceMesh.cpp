// SPDX-License-Identifier: LGPL-2.1-or-later

#include "SurfaceMesh.h"

#include <algorithm>
#include <cmath>
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
    Extractor(const Shape& shape, unsigned int resolution)
        : shape(shape)
        , resolution(resolution)
        , width(static_cast<std::size_t>(resolution) + 1)
    {}

    SurfaceMesh run()
    {
        samples.resize(width * width * width);
        mesh.sampleCount = samples.size();
        for (std::size_t id = 0; id < samples.size(); ++id) {
            samples[id] = checkedValue(point(id));
        }

        for (std::size_t z = 0; z < resolution; ++z) {
            for (std::size_t y = 0; y < resolution; ++y) {
                for (std::size_t x = 0; x < resolution; ++x) {
                    const std::size_t base = z * width * width + y * width + x;
                    const std::array<std::size_t, 8> cube {{
                        base,
                        base + 1,
                        base + width + 1,
                        base + width,
                        base + width * width,
                        base + width * width + 1,
                        base + width * width + width + 1,
                        base + width * width + width,
                    }};
                    for (const auto& tetrahedron : tetrahedra) {
                        polygonise(cube, tetrahedron);
                    }
                }
            }
        }
        return std::move(mesh);
    }

private:
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
        mesh.vertices.push_back(position);
        mesh.normals.push_back(normal);
        edges.emplace(key, index);
        return index;
    }

    void triangle(std::size_t a, std::size_t b, std::size_t c)
    {
        if (a == b || b == c || c == a) {
            return;
        }
        const auto normal
            = (mesh.vertices[b] - mesh.vertices[a]).Cross(mesh.vertices[c] - mesh.vertices[a]);
        if (normal.Sqr() == 0.0) {
            return;
        }
        if (normal.Dot(mesh.normals[a] + mesh.normals[b] + mesh.normals[c]) < 0.0) {
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
        if (count == 1 || count == 3) {
            const auto singleton = count == 1 ? inside[0] : outside[0];
            const auto& others = count == 1 ? outside : inside;
            const auto a = vertex(singleton, others[0]);
            const auto b = vertex(singleton, others[1]);
            const auto c = vertex(singleton, others[2]);
            triangle(a, b, c);
            return;
        }
        const auto a = vertex(inside[0], outside[0]);
        const auto b = vertex(inside[0], outside[1]);
        const auto c = vertex(inside[1], outside[0]);
        const auto d = vertex(inside[1], outside[1]);
        triangle(a, b, c);
        triangle(b, d, c);
    }

    const Shape& shape;
    unsigned int resolution;
    std::size_t width;
    SurfaceMesh mesh;
    std::vector<double> samples;
    std::unordered_map<Edge, std::size_t, EdgeHash> edges;
};

}  // namespace

SurfaceMesh tessellate(const Shape& shape, unsigned int resolution)
{
    if (resolution < 2 || resolution > 64) {
        throw std::invalid_argument("tessellation resolution must be between 2 and 64");
    }
    return Extractor(shape, resolution).run();
}

}  // namespace Implicit
