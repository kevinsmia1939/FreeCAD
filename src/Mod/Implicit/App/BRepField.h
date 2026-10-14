// SPDX-License-Identifier: LGPL-2.1-or-later
#pragma once
#include "Field.h"
#include <string>

namespace Implicit
{
// A self-contained B-Rep snapshot. The owning graph persists its BRep text.
// Numerical distances are in model length units; gradients use finite differences.
class ImplicitExport BRepField final: public Field
{
public:
    BRepField(const std::string& data, double tolerance);
    ~BRepField() override;
    double value(const Base::Vector3d& point) const override;
    Base::Vector3d gradient(const Base::Vector3d& point) const override;

private:
    struct Implementation;
    std::unique_ptr<Implementation> implementation;
};
}  // namespace Implicit
