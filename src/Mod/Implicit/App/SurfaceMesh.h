// SPDX-License-Identifier: LGPL-2.1-or-later

#pragma once

#include <array>
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

ImplicitExport SurfaceMesh tessellate(const Shape& shape, unsigned int resolution = 24);
// Conservative empty-space octree pruning. All surviving surface cells have
// the same finest resolution, so no coarse/fine transition faces are required.
ImplicitExport SurfaceMesh tessellateAdaptive(const Shape& shape, unsigned int resolution = 32);

}  // namespace Implicit
