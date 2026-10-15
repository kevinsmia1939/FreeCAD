// SPDX-License-Identifier: LGPL-2.1-or-later

#pragma once

#include "Field.h"
#include <vector>

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
    struct RayHit
    {
        double distance;
        Base::Vector3d point;
        double residual;
        double bracketWidth;
    };

    Shape(FieldPtr field, Domain domain, double tolerance, bool insideNegative = true);

    // Direction is normalized; distances and tolerance are in local model units.
    // Sampled sign brackets are not a completeness guarantee (e.g. tangencies).
    std::vector<RayHit> intersectRay(const Base::Vector3d& origin,
                                   const Base::Vector3d& direction,
                                   double minimumDistance,
                                   double maximumDistance,
                                   int samples = 512,
                                   double distanceTolerance = 1e-7) const;

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

    FieldPtr getField() const
    {
        return field;
    }

private:
    FieldPtr field;
    Domain domain;
    double tolerance;
    bool insideNegative;
};

}  // namespace Implicit
