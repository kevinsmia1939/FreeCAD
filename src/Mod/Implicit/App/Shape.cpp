// SPDX-License-Identifier: LGPL-2.1-or-later

#include "Shape.h"

#include <cmath>
#include <algorithm>
#include <stdexcept>
#include <utility>

using namespace Implicit;

bool Domain::isValid() const
{
    return std::isfinite(minimum.x) && std::isfinite(minimum.y) && std::isfinite(minimum.z)
        && std::isfinite(maximum.x) && std::isfinite(maximum.y) && std::isfinite(maximum.z)
        && minimum.x < maximum.x && minimum.y < maximum.y && minimum.z < maximum.z;
}

bool Domain::contains(const Base::Vector3d& point) const
{
    return point.x >= minimum.x && point.x <= maximum.x && point.y >= minimum.y
        && point.y <= maximum.y && point.z >= minimum.z && point.z <= maximum.z;
}

Shape::Shape(FieldPtr field, Domain domain, double tolerance, bool insideNegative)
    : field(std::move(field))
    , domain(domain)
    , tolerance(tolerance)
    , insideNegative(insideNegative)
{
    if (!this->field) {
        throw std::invalid_argument("implicit shape requires a field");
    }
    if (!domain.isValid()) {
        throw std::invalid_argument("implicit shape domain must be finite and non-empty");
    }
    if (!std::isfinite(tolerance) || tolerance < 0.0) {
        throw std::invalid_argument("implicit shape tolerance must be finite and non-negative");
    }
}

double Shape::value(const Base::Vector3d& point) const
{
    if (!std::isfinite(point.x) || !std::isfinite(point.y) || !std::isfinite(point.z)) {
        throw std::invalid_argument("implicit query point must be finite");
    }
    const double result = field->value(point);
    if (!std::isfinite(result)) {
        throw std::runtime_error("implicit field returned a non-finite value");
    }
    return result;
}

Base::Vector3d Shape::gradient(const Base::Vector3d& point) const
{
    if (!std::isfinite(point.x) || !std::isfinite(point.y) || !std::isfinite(point.z)) {
        throw std::invalid_argument("implicit query point must be finite");
    }
    const auto result = field->gradient(point);
    if (!std::isfinite(result.x) || !std::isfinite(result.y) || !std::isfinite(result.z)) {
        throw std::runtime_error("implicit field returned a non-finite gradient");
    }
    return result;
}

PointClassification Shape::classify(const Base::Vector3d& point) const
{
    const double signedValue = insideNegative ? value(point) : -value(point);
    if (signedValue < -tolerance) {
        return PointClassification::Inside;
    }
    if (signedValue > tolerance) {
        return PointClassification::Outside;
    }
    return PointClassification::OnSurface;
}

bool Shape::contains(const Base::Vector3d& point) const
{
    return domain.contains(point) && classify(point) != PointClassification::Outside;
}

std::vector<Shape::RayHit> Shape::intersectRay(const Base::Vector3d& origin,
                                             const Base::Vector3d& direction,
                                             double minimumDistance,
                                             double maximumDistance,
                                             int samples,
                                             double distanceTolerance) const
{
    const auto finite = [](const Base::Vector3d& v) {
        return std::isfinite(v.x) && std::isfinite(v.y) && std::isfinite(v.z);
    };
    const double length = std::hypot(direction.x, direction.y, direction.z);
    if (!finite(origin) || !finite(direction) || !std::isfinite(length) || length <= 0
        || !std::isfinite(minimumDistance) || !std::isfinite(maximumDistance)
        || minimumDistance > maximumDistance
        || !std::isfinite(maximumDistance - minimumDistance)
        || samples < 1 || samples > 65536
        || !std::isfinite(distanceTolerance) || distanceTolerance <= 0) {
        throw std::invalid_argument("ray requires finite coordinates, nonzero direction, ordered finite "
                                    "distances, 1..65536 samples and a positive distance tolerance");
    }
    const auto unit = direction / length;
    // Slab clipping bounds sampling; the domain boundary itself is not a surface.
    for (int axis = 0; axis < 3; ++axis) {
        if (unit[axis] == 0) {
            if (origin[axis] < domain.minimum[axis] || origin[axis] > domain.maximum[axis]) {
                return {};
            }
            continue;
        }
        double a = (domain.minimum[axis] - origin[axis]) / unit[axis];
        double b = (domain.maximum[axis] - origin[axis]) / unit[axis];
        if (a > b) {
            std::swap(a, b);
        }
        minimumDistance = std::max(minimumDistance, a);
        maximumDistance = std::min(maximumDistance, b);
        if (minimumDistance > maximumDistance) {
            return {};
        }
    }
    std::vector<RayHit> hits;
    const auto append = [&](double distance, double width) {
        if (!hits.empty() && distance - hits.back().distance <= distanceTolerance) {
            return;
        }
        const auto point = origin + unit * distance;
        hits.push_back({distance, point, std::abs(value(point)), width});
    };
    double previousDistance = minimumDistance;
    double previousValue = value(origin + unit * previousDistance);
    if (previousValue == 0) {
        append(previousDistance, 0);
    }
    if (minimumDistance == maximumDistance) {
        return hits;
    }
    for (int sample = 1; sample <= samples; ++sample) {
        const double distance = sample == samples ? maximumDistance
            : minimumDistance + (maximumDistance - minimumDistance) * (double(sample) / samples);
        const double currentValue = value(origin + unit * distance);
        if (currentValue == 0 && previousValue == 0) {
            throw std::runtime_error("ray has adjacent zero samples; isolated intersections are ambiguous");
        }
        if (currentValue == 0) {
            append(distance, 0);
        }
        else if (previousValue != 0 && std::signbit(previousValue) != std::signbit(currentValue)) {
            double low = previousDistance;
            double high = distance;
            double lowValue = previousValue;
            for (int iteration = 0; high - low > distanceTolerance && iteration < 100; ++iteration) {
                const double middle = low + (high - low) * 0.5;
                if (middle == low || middle == high) {
                    break;
                }
                const double middleValue = value(origin + unit * middle);
                if (middleValue == 0) {
                    low = high = middle;
                }
                else if (std::signbit(lowValue) != std::signbit(middleValue)) {
                    high = middle;
                }
                else {
                    low = middle;
                    lowValue = middleValue;
                }
            }
            if (high - low > distanceTolerance) {
                throw std::runtime_error("ray root refinement could not reach the requested distance tolerance");
            }
            append(low + (high - low) * 0.5, high - low);
        }
        previousDistance = distance;
        previousValue = currentValue;
    }
    return hits;
}
