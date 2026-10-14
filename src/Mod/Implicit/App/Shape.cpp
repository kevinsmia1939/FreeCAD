// SPDX-License-Identifier: LGPL-2.1-or-later

#include "Shape.h"

#include <cmath>
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
    return field->value(point);
}

Base::Vector3d Shape::gradient(const Base::Vector3d& point) const
{
    return field->gradient(point);
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
