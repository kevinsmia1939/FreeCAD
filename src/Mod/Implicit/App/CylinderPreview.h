// SPDX-License-Identifier: LGPL-2.1-or-later
#pragma once
#include "CylinderGeometry.h"
#include <array>
#include <string>
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
    // Directed distance of every uploaded field triangle to the masked sheet.
    // This does not certify reverse coverage or the other two faces.
    bool fieldTriangleDistanceVerified = false;
    double fieldTriangleDistanceBound = 0;
    size_t fieldTrianglesChecked = 0;
    std::string fieldTriangleReason;
    bool capDiskDistanceVerified = false;
    double capDiskDistanceBound = 0;
    std::string capDiskReason;
    bool sheetReverseDistanceVerified = false;
    double sheetReverseDistanceBound = 0;
    size_t sheetReverseTrianglesChecked = 0;
    std::string sheetReverseReason;
    bool sideDistanceVerified = false;
    double sideDistanceBound = 0;
    size_t sideTrianglesChecked = 0;
    std::string sideDistanceReason;
};
// Transient conforming preview, not a global surface-distance certificate.
CylinderPreview buildCylinderPreview(const CylinderGeometry::Solid&, unsigned resolution);
}  // namespace Implicit
