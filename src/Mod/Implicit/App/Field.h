// SPDX-License-Identifier: LGPL-2.1-or-later

#pragma once

#include <memory>
#include <limits>

#include <Base/Vector3D.h>
#include <Base/Placement.h>
#include <Mod/Implicit/ImplicitGlobal.h>

namespace Implicit
{

enum class PointClassification
{
    Outside = 1,
    OnSurface = 0,
    Inside = -1
};

class ImplicitExport Field
{
public:
    virtual ~Field() = default;

    virtual double value(const Base::Vector3d& point) const = 0;
    virtual Base::Vector3d gradient(const Base::Vector3d& point) const = 0;
    // Conservative global bound; infinity disables spatial pruning.
    virtual double lipschitzBound() const
    {
        return std::numeric_limits<double>::infinity();
    }
};

using FieldPtr = std::shared_ptr<const Field>;

// Evaluate an immutable operand in another feature's local coordinates.
// sign converts positive-inside operands to the canonical negative-inside set.
class ImplicitExport PlacedField final: public Field
{
public:
    PlacedField(FieldPtr field, Base::Placement sourceToTarget, double sign = 1.0);
    double value(const Base::Vector3d& point) const override;
    Base::Vector3d gradient(const Base::Vector3d& point) const override;
    double lipschitzBound() const override
    {
        return field->lipschitzBound();
    }

private:
    FieldPtr field;
    Base::Placement toSource;
    Base::Rotation toTargetRotation;
    double sign;
};

class ImplicitExport BoxField final: public Field
{
public:
    BoxField(Base::Vector3d center, Base::Vector3d halfSize);
    double value(const Base::Vector3d& point) const override;
    Base::Vector3d gradient(const Base::Vector3d& point) const override;
    double lipschitzBound() const override
    {
        return 1.0;
    }

private:
    Base::Vector3d center;
    Base::Vector3d halfSize;
};

class ImplicitExport BandField final: public Field
{
public:
    BandField(FieldPtr field, double halfWidth);
    double value(const Base::Vector3d& point) const override;
    Base::Vector3d gradient(const Base::Vector3d& point) const override;
    double lipschitzBound() const override
    {
        return field->lipschitzBound();
    }

private:
    FieldPtr field;
    double halfWidth;
};

class ImplicitExport SphereField final: public Field
{
public:
    SphereField(Base::Vector3d center, double radius);

    double value(const Base::Vector3d& point) const override;
    Base::Vector3d gradient(const Base::Vector3d& point) const override;
    double lipschitzBound() const override
    {
        return 1.0;
    }

private:
    Base::Vector3d center;
    double radius;
};

class ImplicitExport GyroidField final: public Field
{
public:
    GyroidField(double period, double isoValue);

    double value(const Base::Vector3d& point) const override;
    Base::Vector3d gradient(const Base::Vector3d& point) const override;
    double lipschitzBound() const override;

private:
    double waveNumber;
    double isoValue;
};

enum class BooleanOperation
{
    Union,
    Intersection,
    Difference
};

class ImplicitExport BooleanField final: public Field
{
public:
    BooleanField(BooleanOperation operation, FieldPtr left, FieldPtr right);

    double value(const Base::Vector3d& point) const override;
    Base::Vector3d gradient(const Base::Vector3d& point) const override;
    double lipschitzBound() const override;

private:
    bool selectLeft(double leftValue, double rightValue) const;

    BooleanOperation operation;
    FieldPtr left;
    FieldPtr right;
};

class ImplicitExport TranslateField final: public Field
{
public:
    TranslateField(FieldPtr field, Base::Vector3d offset);

    double value(const Base::Vector3d& point) const override;
    Base::Vector3d gradient(const Base::Vector3d& point) const override;
    double lipschitzBound() const override
    {
        return field->lipschitzBound();
    }

private:
    FieldPtr field;
    Base::Vector3d offset;
};

class ImplicitExport OffsetField final: public Field
{
public:
    OffsetField(FieldPtr field, double amount);

    double value(const Base::Vector3d& point) const override;
    Base::Vector3d gradient(const Base::Vector3d& point) const override;
    double lipschitzBound() const override
    {
        return field->lipschitzBound();
    }

private:
    FieldPtr field;
    double amount;
};

}  // namespace Implicit
