// SPDX-License-Identifier: LGPL-2.1-or-later
#pragma once
#include "CylinderGeometry.h"
#include <array>
namespace Implicit
{
struct CylinderPreview
{
    std::vector<Base::Vector3d> points;
    std::vector<std::array<uint32_t, 3>> triangles;
    std::vector<unsigned> faces;
    std::vector<Base::Vector3d> cornerNormals;
    std::vector<std::vector<uint32_t>> edges;
    unsigned nativeVertices = 0;
    double rootPointBound = 0, curveDeflection = 0, uploadBound = 0;
    size_t rootTests = 0;
};
// Transient conforming preview, not a global surface-distance certificate.
CylinderPreview buildCylinderPreview(const CylinderGeometry::Solid&, unsigned resolution);
}  // namespace Implicit
