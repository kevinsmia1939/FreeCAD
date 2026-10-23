// SPDX-License-Identifier: LGPL-2.1-or-later
#pragma once
#include <BRepClass3d_ImplicitBox.hxx>
#include <BRepMesh_ImplicitBoundary.hxx>
#include <vector>

namespace Implicit
{
// Pure native result: safe to compute on private worker geometry, without Python.
struct CheckedDisplay
{
    std::vector<gp_Pnt> assignmentNodes;
    BRepMesh_ImplicitBoundary::Coverage coverage;
    BRepMesh_ImplicitBoundary::MeshAudit audit;
    double uploadBound = 0;
};

// The candidate must be privately owned. On success its coordinates are exactly
// the binary32 upload values and its field bound includes the upload displacement.
// Coverage/solid proof flags on the candidate remain unchanged. On failure the
// caller must discard the candidate; no partial report is returned.
CheckedDisplay checkDisplay(const BRepClass3d_ImplicitBox::Boundary& source,
    BRepMesh_ImplicitBoundary::Result& mesh, double tolerance, int depth = 14,
    std::size_t spatial = 2000000, std::size_t patches = 1000000,
    std::size_t pairs = 2000000, std::size_t broad = 50000000);
}
