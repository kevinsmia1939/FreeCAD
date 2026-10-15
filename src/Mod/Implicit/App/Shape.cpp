// SPDX-License-Identifier: LGPL-2.1-or-later

#include "Shape.h"

#include <cmath>
#include <algorithm>
#include <array>
#include <limits>
#include <stdexcept>
#include <string>
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

Shape::Chart Shape::sampleChart(
    const Base::Vector3d& seed,
    double width,
    double height,
    double depth,
    int pointCount,
    int raySamples,
    double distanceTolerance,
    double minimumAlignment,
    const std::atomic_bool* cancelled
) const
{
    if (!std::isfinite(width) || width <= 0 || !std::isfinite(height) || height <= 0
        || !std::isfinite(depth) || depth <= 0 || !std::isfinite(distanceTolerance)
        || distanceTolerance <= 0 || !std::isfinite(minimumAlignment) || minimumAlignment <= 0
        || minimumAlignment > 1 || pointCount < 4 || pointCount > 33 || raySamples < 2
        || raySamples > 4096 || pointCount * pointCount * raySamples > 262144) {
        throw std::invalid_argument("invalid chart dimensions, tolerances or sampling budget");
    }
    const auto check = [cancelled] {
        if (cancelled && cancelled->load(std::memory_order_relaxed)) {
            throw std::runtime_error("implicit operation cancelled");
        }
    };
    check();
    const auto projection = project(seed, distanceTolerance);
    if (!projection.converged) {
        throw std::runtime_error(std::string("chart seed projection failed: ") + projection.status);
    }
    Chart chart;
    chart.center = projection.point;
    chart.normal = gradient(chart.center);
    chart.normal /= std::hypot(chart.normal.x, chart.normal.y, chart.normal.z);
    const Base::Vector3d reference = std::abs(chart.normal.x) < 0.8 ? Base::Vector3d(1, 0, 0)
                                                                    : Base::Vector3d(0, 1, 0);
    chart.u = reference.Cross(chart.normal);
    chart.u.Normalize();
    chart.v = chart.normal.Cross(chart.u);
    chart.count = pointCount;
    chart.points.reserve(pointCount * pointCount);
    for (int u = 0; u < pointCount; ++u) {
        for (int v = 0; v < pointCount; ++v) {
            check();
            const auto origin = chart.center
                + chart.u * (width * (double(u) / (pointCount - 1) - 0.5))
                + chart.v * (height * (double(v) / (pointCount - 1) - 0.5));
            const auto roots
                = intersectRay(origin, chart.normal, -depth, depth, raySamples, distanceTolerance);
            if (roots.size() != 1) {
                throw std::runtime_error(
                    "chart ray requires exactly one sampled root; shrink the patch or depth"
                );
            }
            const auto& hit = roots.front();
            const auto g = gradient(hit.point);
            const double length = std::hypot(g.x, g.y, g.z);
            if (!std::isfinite(length) || length == 0) {
                throw std::runtime_error("chart encountered a critical point");
            }
            const double alignment = g.Dot(chart.normal) / length;
            if (alignment < minimumAlignment) {
                throw std::runtime_error(
                    "chart normal alignment failed; patch may fold or cross a crease"
                );
            }
            chart.minimumAlignment = std::min(chart.minimumAlignment, alignment);
            chart.maxResidual = std::max(chart.maxResidual, hit.residual);
            chart.points.push_back(hit.point);
        }
    }
    return chart;
}

Shape::Projection Shape::project(
    const Base::Vector3d& query,
    double distanceTolerance,
    double fieldTolerance,
    int maxIterations,
    double gradientStep
) const
{
    // Validate even when the seed is already on the zero set.
    value(query);
    if (!domain.contains(query) || !std::isfinite(distanceTolerance) || distanceTolerance <= 0
        || !std::isfinite(fieldTolerance) || fieldTolerance <= 0 || !std::isfinite(gradientStep)
        || gradientStep <= 0 || maxIterations < 1 || maxIterations > 256) {
        throw std::invalid_argument(
            "projection requires a seed in the domain, positive finite "
            "tolerances/gradient step and 1..256 iterations"
        );
    }
    Projection result;
    result.point = query;
    double lambda = 0;
    const auto norm = [](const Base::Vector3d& v) {
        return std::hypot(v.x, v.y, v.z);
    };
    const double maxStep = norm(domain.maximum - domain.minimum);
    if (!std::isfinite(maxStep)) {
        throw std::invalid_argument("projection domain extent is too large");
    }
    for (int iteration = 0; iteration <= maxIterations; ++iteration) {
        const auto g = gradient(result.point);
        const double f = value(result.point);
        const auto stationarity = result.point - query + g * lambda;
        result.residual = std::abs(f);
        result.distance = norm(result.point - query);
        result.stationarity = norm(stationarity);
        result.iterations = iteration;
        const double scale = norm(g);
        if (scale <= std::numeric_limits<double>::min() || !std::isfinite(scale)) {
            result.status = "critical_point";
            break;
        }
        if (result.residual <= fieldTolerance && result.residual / scale <= distanceTolerance
            && result.stationarity <= distanceTolerance) {
            result.converged = true;
            result.status = "converged";
            break;
        }
        if (iteration == maxIterations) {
            break;
        }
        std::array<std::array<double, 5>, 4> matrix {};
        for (int axis = 0; axis < 3; ++axis) {
            auto offset = Base::Vector3d();
            offset[axis] = gradientStep;
            const auto hessianColumn = (gradient(result.point + offset)
                                        - gradient(result.point - offset))
                / (2 * gradientStep);
            for (int row = 0; row < 3; ++row) {
                matrix[row][axis] = (row == axis ? 1.0 : 0.0) + lambda * hessianColumn[row];
            }
            matrix[axis][3] = g[axis];
            matrix[axis][4] = -stationarity[axis];
            matrix[3][axis] = g[axis] / scale;
        }
        matrix[3][4] = -f / scale;
        bool singular = false;
        for (int row = 0; row < 4; ++row) {
            double largest = 0;
            for (int col = 0; col < 4; ++col) {
                largest = std::max(largest, std::abs(matrix[row][col]));
            }
            if (!std::isfinite(largest) || largest == 0) {
                singular = true;
                break;
            }
            for (double& entry : matrix[row]) {
                entry /= largest;
            }
        }
        for (int col = 0; col < 4 && !singular; ++col) {
            int pivot = col;
            for (int row = col + 1; row < 4; ++row) {
                if (std::abs(matrix[row][col]) > std::abs(matrix[pivot][col])) {
                    pivot = row;
                }
            }
            if (std::abs(matrix[pivot][col]) < 1e-14) {
                singular = true;
                break;
            }
            std::swap(matrix[col], matrix[pivot]);
            const double divisor = matrix[col][col];
            for (int entry = col; entry < 5; ++entry) {
                matrix[col][entry] /= divisor;
            }
            for (int row = 0; row < 4; ++row) {
                if (row == col) {
                    continue;
                }
                const double factor = matrix[row][col];
                for (int entry = col; entry < 5; ++entry) {
                    matrix[row][entry] -= factor * matrix[col][entry];
                }
            }
        }
        if (singular) {
            result.status = "singular_system";
            break;
        }
        const Base::Vector3d step(matrix[0][4], matrix[1][4], matrix[2][4]);
        const double stepNorm = norm(step);
        double fraction = stepNorm > maxStep ? maxStep / stepNorm : 1;
        const double merit = std::hypot(f / scale, result.stationarity);
        bool accepted = false;
        for (int backtrack = 0; backtrack < 24; ++backtrack, fraction *= 0.5) {
            const auto candidate = result.point + step * fraction;
            const double candidateLambda = lambda + matrix[3][4] * fraction;
            if (!domain.contains(candidate) || !std::isfinite(candidateLambda)) {
                continue;
            }
            const double candidateMerit = std::hypot(
                value(candidate) / scale,
                norm(candidate - query + gradient(candidate) * candidateLambda)
            );
            if (std::isfinite(candidateMerit) && candidateMerit < merit) {
                result.point = candidate;
                lambda = candidateLambda;
                accepted = true;
                break;
            }
        }
        if (!accepted) {
            result.status = "line_search_failed";
            break;
        }
    }
    return result;
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
