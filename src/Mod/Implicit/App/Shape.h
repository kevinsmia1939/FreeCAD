// SPDX-License-Identifier: LGPL-2.1-or-later

#pragma once

#include "Field.h"
#include <atomic>
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
    struct Chart
    {
        Base::Vector3d center, u, v, normal;
        std::vector<Base::Vector3d> points;
        double maxResidual = 0;
        double minimumAlignment = 1;
        int count = 0;
    };

    // Experimental fixed-normal height chart; sampled uniqueness only.
    Chart sampleChart(
        const Base::Vector3d& seed,
        double width,
        double height,
        double depth,
        int pointCount = 9,
        int raySamples = 128,
        double distanceTolerance = 1e-9,
        double minimumAlignment = 0.2,
        const std::atomic_bool* cancelled = nullptr
    ) const;

    struct Projection
    {
        Base::Vector3d point;
        double residual = 0;
        double distance = 0;
        double stationarity = 0;
        int iterations = 0;
        bool converged = false;
        const char* status = "iteration_limit";
    };

    // Local constrained stationary point, not a certified global nearest point.
    Projection project(
        const Base::Vector3d& query,
        double distanceTolerance = 1e-7,
        double fieldTolerance = 1e-9,
        int maxIterations = 64,
        double gradientStep = 1e-5
    ) const;

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
