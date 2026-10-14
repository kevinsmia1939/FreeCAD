// SPDX-License-Identifier: LGPL-2.1-or-later
#include "BRepField.h"
#include <BRepClass3d_SignedDistance.hxx>
#include <BRepTools.hxx>
#include <BRep_Builder.hxx>
#include <Standard_Failure.hxx>
#include <algorithm>
#include <cmath>
#include <mutex>
#include <sstream>
#include <stdexcept>

namespace Implicit
{
struct BRepField::Implementation
{
    static TopoDS_Shape read(const std::string& data)
    {
        TopoDS_Shape shape;
        BRep_Builder builder;
        std::istringstream stream(data);
        BRepTools::Read(shape, stream, builder);
        if (shape.IsNull() || stream.bad()) {
            throw std::invalid_argument("invalid B-Rep snapshot");
        }
        return shape;
    }
    Implementation(const std::string& data, double tolerance)
        : distance(read(data), tolerance)
        , step(std::max(1.0e-5, 8.0 * tolerance))
    {}
    BRepClass3d_SignedDistance distance;
    double step;
    std::mutex mutex;
};

BRepField::BRepField(const std::string& data, double tolerance)
{
    try {
        implementation = std::make_unique<Implementation>(data, tolerance);
    }
    catch (const Standard_Failure& error) {
        throw std::invalid_argument(error.GetMessageString());
    }
}
BRepField::~BRepField() = default;

double BRepField::value(const Base::Vector3d& point) const
{
    std::lock_guard lock(implementation->mutex);
    try {
        return implementation->distance.Value(gp_Pnt(point.x, point.y, point.z));
    }
    catch (const Standard_Failure& error) {
        throw std::runtime_error(error.GetMessageString());
    }
}

Base::Vector3d BRepField::gradient(const Base::Vector3d& point) const
{
    // Adaptive coordinate scaling keeps the perturbation representable for
    // large coordinates. This derivative is not defined at medial-axis ties.
    const double step = std::max(
        implementation->step,
        1.0e-7 * std::max({std::abs(point.x), std::abs(point.y), std::abs(point.z)})
    );
    const Base::Vector3d x(step, 0, 0), y(0, step, 0), z(0, 0, step);
    return Base::Vector3d(
               value(point + x) - value(point - x),
               value(point + y) - value(point - y),
               value(point + z) - value(point - z)
           )
        / (2 * step);
}
}  // namespace Implicit
