// SPDX-License-Identifier: LGPL-2.1-or-later

#include "Field.h"

#include <algorithm>
#include <cmath>
#include <numbers>
#include <stdexcept>
#include <utility>

Implicit::PlacedField::PlacedField(FieldPtr field, Base::Placement sourceToTarget, double sign)
    : field(std::move(field))
    , toSource(sourceToTarget.inverse())
    , toTargetRotation(sourceToTarget.getRotation())
    , sign(sign)
{
    if (!this->field || (sign != 1.0 && sign != -1.0)) {
        throw std::invalid_argument("invalid placed field");
    }
    const auto& position = sourceToTarget.getPosition();
    const double* rotation = sourceToTarget.getRotation().getValue();
    if (!std::isfinite(position.x) || !std::isfinite(position.y) || !std::isfinite(position.z)
        || !std::all_of(rotation, rotation + 4, [](double value) { return std::isfinite(value); })) {
        throw std::invalid_argument("field placement must be finite");
    }
}

double Implicit::PlacedField::value(const Base::Vector3d& point) const
{
    Base::Vector3d local;
    toSource.multVec(point, local);
    return sign * field->value(local);
}

Base::Vector3d Implicit::PlacedField::gradient(const Base::Vector3d& point) const
{
    Base::Vector3d local, result;
    toSource.multVec(point, local);
    toTargetRotation.multVec(field->gradient(local), result);
    return sign * result;
}

using namespace Implicit;

LinearField::LinearField(Base::Vector3d slope, double intercept)
    : slope(slope)
    , intercept(intercept)
{
    if (!std::isfinite(slope.x) || !std::isfinite(slope.y) || !std::isfinite(slope.z)
        || !std::isfinite(intercept)) {
        throw std::invalid_argument("linear scalar field coefficients must be finite");
    }
}

double LinearField::value(const Base::Vector3d& point) const
{
    return slope.Dot(point) + intercept;
}

double LinearField::lipschitzBound() const
{
    return std::hypot(slope.x, slope.y, slope.z);
}

VariableBandField::VariableBandField(FieldPtr field, FieldPtr width)
    : field(std::move(field))
    , width(std::move(width))
{
    if (!this->field || !this->width) {
        throw std::invalid_argument("variable band requires a field and scalar width field");
    }
}

double VariableBandField::value(const Base::Vector3d& point) const
{
    return std::abs(field->value(point)) - width->value(point);
}

Base::Vector3d VariableBandField::gradient(const Base::Vector3d& point) const
{
    return (field->value(point) < 0 ? -field->gradient(point) : field->gradient(point))
        - width->gradient(point);
}

double VariableBandField::lipschitzBound() const
{
    return field->lipschitzBound() + width->lipschitzBound();
}

SmoothUnionField::SmoothUnionField(FieldPtr left, FieldPtr right, double blend)
    : left(std::move(left))
    , right(std::move(right))
    , blend(blend)
{
    if (!this->left || !this->right || !std::isfinite(blend) || blend <= 0) {
        throw std::invalid_argument("smooth union requires two fields and a positive finite blend");
    }
}

double SmoothUnionField::weight(const Base::Vector3d& point) const
{
    return std::clamp(0.5 + 0.5 * ((right->value(point) - left->value(point)) / blend), 0.0, 1.0);
}

double SmoothUnionField::value(const Base::Vector3d& point) const
{
    const double a = left->value(point), b = right->value(point);
    const double h = std::clamp(0.5 + 0.5 * ((b - a) / blend), 0.0, 1.0);
    return std::lerp(b, a, h) - blend * h * (1 - h);
}

Base::Vector3d SmoothUnionField::gradient(const Base::Vector3d& point) const
{
    const double h = weight(point);
    return left->gradient(point) * h + right->gradient(point) * (1 - h);
}

double SmoothUnionField::lipschitzBound() const
{
    return std::max(left->lipschitzBound(), right->lipschitzBound());
}

BoxField::BoxField(Base::Vector3d center, Base::Vector3d halfSize)
    : center(center)
    , halfSize(halfSize)
{
    if (!std::isfinite(center.x) || !std::isfinite(center.y) || !std::isfinite(center.z)
        || !std::isfinite(halfSize.x) || !std::isfinite(halfSize.y) || !std::isfinite(halfSize.z)
        || halfSize.x <= 0 || halfSize.y <= 0 || halfSize.z <= 0) {
        throw std::invalid_argument("box requires a finite center and positive finite half-size");
    }
}

double BoxField::value(const Base::Vector3d& point) const
{
    const auto p = point - center;
    const Base::Vector3d q(
        std::abs(p.x) - halfSize.x,
        std::abs(p.y) - halfSize.y,
        std::abs(p.z) - halfSize.z
    );
    return Base::Vector3d(std::max(q.x, 0.0), std::max(q.y, 0.0), std::max(q.z, 0.0)).Length()
        + std::min(std::max({q.x, q.y, q.z}), 0.0);
}

Base::Vector3d BoxField::gradient(const Base::Vector3d& point) const
{
    const auto p = point - center;
    const Base::Vector3d q(
        std::abs(p.x) - halfSize.x,
        std::abs(p.y) - halfSize.y,
        std::abs(p.z) - halfSize.z
    );
    Base::Vector3d result(std::max(q.x, 0.0), std::max(q.y, 0.0), std::max(q.z, 0.0));
    const auto sign = [](double value) {
        return value < 0.0 ? -1.0 : 1.0;
    };
    if (const double length = result.Length(); length > 0.0) {
        return Base::Vector3d(result.x * sign(p.x), result.y * sign(p.y), result.z * sign(p.z))
            / length;
    }
    if (q.x >= q.y && q.x >= q.z) {
        return Base::Vector3d(sign(p.x), 0, 0);
    }
    return q.y >= q.z ? Base::Vector3d(0, sign(p.y), 0) : Base::Vector3d(0, 0, sign(p.z));
}

BandField::BandField(FieldPtr field, double halfWidth)
    : field(std::move(field))
    , halfWidth(halfWidth)
{
    if (!this->field || !std::isfinite(halfWidth) || halfWidth <= 0) {
        throw std::invalid_argument("band requires a field and positive finite half-width");
    }
}
double BandField::value(const Base::Vector3d& point) const
{
    return std::abs(field->value(point)) - halfWidth;
}
Base::Vector3d BandField::gradient(const Base::Vector3d& point) const
{
    return field->value(point) < 0.0 ? -field->gradient(point) : field->gradient(point);
}

namespace
{

double gyroidWaveNumber(double period)
{
    if (!std::isfinite(period) || period <= 0.0) {
        throw std::invalid_argument("gyroid period must be finite and positive");
    }
    return 2.0 * std::numbers::pi / period;
}

}  // namespace

SphereField::SphereField(Base::Vector3d center, double radius)
    : center(center)
    , radius(radius)
{
    if (!std::isfinite(radius) || radius <= 0.0 || !std::isfinite(center.x)
        || !std::isfinite(center.y) || !std::isfinite(center.z)) {
        throw std::invalid_argument("sphere requires a finite center and positive finite radius");
    }
}

double SphereField::value(const Base::Vector3d& point) const
{
    return (point - center).Length() - radius;
}

Base::Vector3d SphereField::gradient(const Base::Vector3d& point) const
{
    Base::Vector3d direction = point - center;
    const double length = direction.Length();
    if (length == 0.0) {
        return Base::Vector3d();
    }
    return direction / length;
}

GyroidField::GyroidField(double period, double isoValue)
    : waveNumber(gyroidWaveNumber(period))
    , isoValue(isoValue)
{
    if (!std::isfinite(isoValue)) {
        throw std::invalid_argument("gyroid iso value must be finite");
    }
}

double GyroidField::lipschitzBound() const
{
    return 2.0 * std::sqrt(3.0) * waveNumber;
}

double BooleanField::lipschitzBound() const
{
    return std::max(left->lipschitzBound(), right->lipschitzBound());
}

double GyroidField::value(const Base::Vector3d& point) const
{
    const double x = waveNumber * point.x;
    const double y = waveNumber * point.y;
    const double z = waveNumber * point.z;
    return std::sin(x) * std::cos(y) + std::sin(y) * std::cos(z) + std::sin(z) * std::cos(x)
        - isoValue;
}

Base::Vector3d GyroidField::gradient(const Base::Vector3d& point) const
{
    const double x = waveNumber * point.x;
    const double y = waveNumber * point.y;
    const double z = waveNumber * point.z;
    return Base::Vector3d(
        waveNumber * (std::cos(x) * std::cos(y) - std::sin(z) * std::sin(x)),
        waveNumber * (std::cos(y) * std::cos(z) - std::sin(x) * std::sin(y)),
        waveNumber * (std::cos(z) * std::cos(x) - std::sin(y) * std::sin(z))
    );
}

BooleanField::BooleanField(BooleanOperation operation, FieldPtr left, FieldPtr right)
    : operation(operation)
    , left(std::move(left))
    , right(std::move(right))
{
    if (!this->left || !this->right) {
        throw std::invalid_argument("Boolean field requires two operands");
    }
}

bool BooleanField::selectLeft(double leftValue, double rightValue) const
{
    switch (operation) {
        case BooleanOperation::Union:
            return leftValue <= rightValue;
        case BooleanOperation::Intersection:
            return leftValue >= rightValue;
        case BooleanOperation::Difference:
            return leftValue >= -rightValue;
    }
    throw std::logic_error("unknown Boolean field operation");
}

double BooleanField::value(const Base::Vector3d& point) const
{
    const double leftValue = left->value(point);
    const double rightValue = right->value(point);
    switch (operation) {
        case BooleanOperation::Union:
            return std::min(leftValue, rightValue);
        case BooleanOperation::Intersection:
            return std::max(leftValue, rightValue);
        case BooleanOperation::Difference:
            return std::max(leftValue, -rightValue);
    }
    throw std::logic_error("unknown Boolean field operation");
}

Base::Vector3d BooleanField::gradient(const Base::Vector3d& point) const
{
    const double leftValue = left->value(point);
    const double rightValue = right->value(point);
    if (selectLeft(leftValue, rightValue)) {
        return left->gradient(point);
    }
    const Base::Vector3d result = right->gradient(point);
    return operation == BooleanOperation::Difference ? -result : result;
}

TranslateField::TranslateField(FieldPtr field, Base::Vector3d offset)
    : field(std::move(field))
    , offset(offset)
{
    if (!this->field) {
        throw std::invalid_argument("translated field requires an operand");
    }
    if (!std::isfinite(offset.x) || !std::isfinite(offset.y) || !std::isfinite(offset.z)) {
        throw std::invalid_argument("translation must be finite");
    }
}

double TranslateField::value(const Base::Vector3d& point) const
{
    return field->value(point - offset);
}

Base::Vector3d TranslateField::gradient(const Base::Vector3d& point) const
{
    return field->gradient(point - offset);
}

OffsetField::OffsetField(FieldPtr field, double amount)
    : field(std::move(field))
    , amount(amount)
{
    if (!this->field) {
        throw std::invalid_argument("offset field requires an operand");
    }
    if (!std::isfinite(amount)) {
        throw std::invalid_argument("field offset must be finite");
    }
}

double OffsetField::value(const Base::Vector3d& point) const
{
    return field->value(point) - amount;
}

Base::Vector3d OffsetField::gradient(const Base::Vector3d& point) const
{
    return field->gradient(point);
}
