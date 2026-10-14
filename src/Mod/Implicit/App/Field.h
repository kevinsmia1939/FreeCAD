// SPDX-License-Identifier: LGPL-2.1-or-later

#pragma once

#include <memory>

#include <Base/Vector3D.h>
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
};

using FieldPtr = std::shared_ptr<const Field>;

class ImplicitExport SphereField final: public Field
{
public:
    SphereField(Base::Vector3d center, double radius);

    double value(const Base::Vector3d& point) const override;
    Base::Vector3d gradient(const Base::Vector3d& point) const override;

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

private:
    FieldPtr field;
    double amount;
};

}  // namespace Implicit
