// SPDX-License-Identifier: LGPL-2.1-or-later

#pragma once

#include <array>
#include <atomic>
#include <cstddef>
#include <vector>

#include "Shape.h"

namespace Implicit
{

// Transient, indexed display data in feature-local coordinates.
// The domain clips the zero surface; no domain boundary caps are generated.
struct ImplicitExport SurfaceMesh
{
    std::vector<Base::Vector3d> vertices;
    std::vector<Base::Vector3d> normals;
    std::vector<std::array<std::size_t, 3>> triangles;
    std::size_t sampleCount = 0;
    std::size_t prunedBlocks = 0;
};

struct ImplicitExport MeshQuality
{
    double maxTriangleResidualBound = 0;
    double maxVertexResidual = 0;
    double maxCentroidResidual = 0;
    double maxEdgeMidpointResidual = 0;
    std::size_t boundaryEdges = 0;
    std::size_t nonManifoldEdges = 0;
    std::size_t inconsistentEdges = 0;
    std::size_t degenerateTriangles = 0;
};

// Sampled field residuals, not a geometric/Hausdorff error certificate.
ImplicitExport MeshQuality
inspectMesh(const Shape& shape, const SurfaceMesh& mesh, const std::atomic_bool* cancelled = nullptr);

struct ImplicitExport RefinementStep
{
    unsigned int resolution;
    std::size_t triangles;
    double residualBound;
};

struct ImplicitExport ControlledMesh
{
    SurfaceMesh mesh;
    MeshQuality quality;
    std::vector<RefinementStep> history;
    bool toleranceMet = false;
    const char* status = "resolution_limit";
};

// Global grid refinement, not variable-resolution cells or a coverage guarantee.
ImplicitExport ControlledMesh tessellateControlled(
    const Shape& shape,
    double fieldTolerance,
    unsigned int minimumResolution = 8,
    unsigned int maximumResolution = 64,
    const std::atomic_bool* cancelled = nullptr
);

ImplicitExport SurfaceMesh tessellate(
    const Shape& shape,
    unsigned int resolution = 24,
    const std::atomic_bool* cancelled = nullptr
);
// Conservative empty-space octree pruning. All surviving surface cells have
// the same finest resolution, so no coarse/fine transition faces are required.
ImplicitExport SurfaceMesh tessellateAdaptive(
    const Shape& shape,
    unsigned int resolution = 32,
    const std::atomic_bool* cancelled = nullptr
);

}  // namespace Implicit
