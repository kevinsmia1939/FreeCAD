// SPDX-License-Identifier: LGPL-2.1-or-later

#pragma once

#include "Field.h"

namespace Implicit
{

struct ImplicitExport Domain
{
    Base::Vector3d minimum;
    Base::Vector3d maximum;

    bool isValid() const;
    bool contains(const Base::Vector3d& point) const;
};

class ImplicitExport Shape
{
public:
    Shape(FieldPtr field, Domain domain, double tolerance, bool insideNegative = true);

    double value(const Base::Vector3d& point) const;
    Base::Vector3d gradient(const Base::Vector3d& point) const;
    PointClassification classify(const Base::Vector3d& point) const;
    bool contains(const Base::Vector3d& point) const;
    double lipschitzBound() const
    {
        return field->lipschitzBound();
    }

    const Domain& getDomain() const
    {
        return domain;
    }

    bool isInsideNegative() const
    {
        return insideNegative;
    }

private:
    FieldPtr field;
    Domain domain;
    double tolerance;
    bool insideNegative;
};

}  // namespace Implicit
