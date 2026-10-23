// SPDX-License-Identifier: LGPL-2.1-or-later
#include "CheckedDisplay.h"
#include <BRepClass3d_ImplicitWork.hxx>
#include <Standard_DomainError.hxx>
#include <Standard_NotImplemented.hxx>
#include <algorithm>
#include <cmath>
#include <limits>
#include <utility>

Implicit::CheckedDisplay Implicit::checkDisplay(const BRepClass3d_ImplicitBox::Boundary& source,
    BRepMesh_ImplicitBoundary::Result& mesh, double tolerance, int depth,
    std::size_t spatial, std::size_t patches, std::size_t pairs, std::size_t broad)
{
    BRepClass3d_ImplicitWork::Checkpoint();
    if (depth < 1 || depth > 20 || !spatial || spatial > 10000000
        || !patches || patches > 4000000 || !pairs || pairs > 10000000
        || !broad || broad > 100000000) {
        throw Standard_DomainError("Invalid checked display budgets");
    }
    if (!mesh.MeshClosed || !mesh.NativeSurfaceMeshed) {
        throw Standard_NotImplemented("Checked display requires a closed surface candidate");
    }
    CheckedDisplay result;
    auto uploaded = mesh.Nodes;
    double magnitude = 1;
    for (std::size_t i = 0; i < uploaded.size(); ++i) {
        BRepClass3d_ImplicitWork::Checkpoint();
        for (int axis = 1; axis <= 3; ++axis) {
            const double value = mesh.Nodes[i].Coord(axis);
            if (!std::isfinite(value) || std::abs(value) > std::numeric_limits<float>::max()) {
                throw Standard_DomainError("Display coordinate exceeds binary32 range");
            }
            magnitude = std::max(magnitude, std::abs(value));
            uploaded[i].SetCoord(axis, static_cast<double>(static_cast<float>(value)));
        }
        result.uploadBound = std::max(result.uploadBound, mesh.Nodes[i].Distance(uploaded[i]));
    }
    result.uploadBound += 256 * std::numeric_limits<double>::epsilon() * magnitude;
    if (!std::isfinite(result.uploadBound) || !(tolerance > 4096 * result.uploadBound)) {
        throw Standard_DomainError("Display upload precision exhausted");
    }
    result.coverage = BRepMesh_ImplicitBoundary::CheckCoverage(
        source, mesh, tolerance - result.uploadBound, depth, spatial, patches);
    if (!result.coverage.Resolved) {
        throw Standard_NotImplemented("Checked display clipped proximity unresolved");
    }
    result.assignmentNodes = std::move(mesh.Nodes);
    mesh.Nodes = std::move(uploaded);
    result.audit = BRepMesh_ImplicitBoundary::Audit(mesh, pairs, broad);
    using State = BRepMesh_ImplicitBoundary::MeshAudit::State;
    if (result.audit.Status != State::Clear) {
        throw Standard_NotImplemented(result.audit.Status == State::Limit
            ? "Checked display contact audit budget exhausted"
            : "Checked display upload creates triangle contacts or degeneracies");
    }
    BRepClass3d_ImplicitWork::Checkpoint();
    mesh.FieldDistanceBound += result.uploadBound;
    return result;
}
