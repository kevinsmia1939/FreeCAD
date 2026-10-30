// SPDX-License-Identifier: LGPL-2.1-or-later
#pragma once
#include <App/ComplexGeoData.h>
#include <Base/Exception.h>
#include <BRep_Tool.hxx>
#include <Geom_Circle.hxx>
#include <Geom_Line.hxx>
#include <Geom_BSplineCurve.hxx>
#include <TopExp.hxx>
#include <TopoDS.hxx>
#include <NCollection_IndexedMap.hxx>
#include <TopTools_ShapeMapHasher.hxx>
#include <cmath>
#include <algorithm>
#include <limits>

namespace Implicit::detail
{
// Native endpoints are indexed by identity, never distance-welded. Accuracy
// bounds the stored curves, independently of their field approximation.
inline void cylinderBoundary(
    const TopoDS_Shape& shape,
    double accuracy,
    std::vector<Base::Vector3d>& output,
    std::vector<Data::ComplexGeoData::Line>& lines,
    std::vector<std::vector<uint32_t>>* edgeSamples = nullptr
)
{
    using Map = NCollection_IndexedMap<TopoDS_Shape, TopTools_ShapeMapHasher>;
    if (!std::isfinite(accuracy) || accuracy <= 0) {
        throw Base::ValueError("Invalid cylinder line deflection");
    }
    Map edges, vertices;
    TopExp::MapShapes(shape, TopAbs_EDGE, edges);
    TopExp::MapShapes(shape, TopAbs_VERTEX, vertices);
    std::vector<Base::Vector3d> points;
    std::vector<Data::ComplexGeoData::Line> segments;
    std::vector<std::vector<uint32_t>> samples;
    constexpr size_t maximumNodes = 1000000;
    const auto append = [&](const gp_Pnt& p) {
        if (points.size() >= maximumNodes || !std::isfinite(p.X()) || !std::isfinite(p.Y())
            || !std::isfinite(p.Z())) {
            throw Base::ValueError("Cylinder line cache size/coordinate limit");
        }
        points.emplace_back(p.X(), p.Y(), p.Z());
        return static_cast<uint32_t>(points.size() - 1);
    };
    for (const auto& vertex : vertices) {
        append(BRep_Tool::Pnt(TopoDS::Vertex(vertex)));
    }
    for (const auto& source : edges) {
        const auto edge = TopoDS::Edge(source.Oriented(TopAbs_FORWARD));
        TopoDS_Vertex a, b;
        TopExp::Vertices(edge, a, b);
        const int start = vertices.FindIndex(a), finish = vertices.FindIndex(b);
        if (!start || !finish) {
            throw Base::ValueError("Missing native cylinder endpoint");
        }
        TopLoc_Location location;
        double first, last;
        const auto curve = BRep_Tool::Curve(edge, location, first, last);
        if (curve.IsNull() || !std::isfinite(first) || !std::isfinite(last) || last <= first) {
            throw Base::ValueError("Invalid cylinder boundary curve");
        }
        const auto world = [&](const gp_Pnt& p) {
            return p.Transformed(location.Transformation());
        };
        const double endpoint = std::max(
            world(curve->Value(first)).Distance(BRep_Tool::Pnt(a)),
            world(curve->Value(last)).Distance(BRep_Tool::Pnt(b))
        );
        const auto analyticCircle = occ::down_cast<Geom_Circle>(curve);
        const double angularReserve = analyticCircle.IsNull()
            ? 0.
            : analyticCircle->Radius() * std::abs(location.Transformation().ScaleFactor())
                * (1 + std::abs(first) + std::abs(last));
        const double reserve = 32768 * std::numeric_limits<double>::epsilon()
            * (1 + BRep_Tool::Pnt(a).Distance(gp_Pnt()) + BRep_Tool::Pnt(b).Distance(gp_Pnt())
               + angularReserve);
        const double remaining = accuracy - endpoint - reserve;
        if (!(remaining > 0)) {
            throw Base::ValueError("Cylinder line precision exceeds deflection");
        }
        std::vector<gp_Pnt> interior;
        if (const auto spline = occ::down_cast<Geom_BSplineCurve>(curve); !spline.IsNull()) {
            if (spline->Degree() != 1 || spline->IsRational() || spline->IsPeriodic()
                || spline->NbPoles() != spline->NbKnots() || first != spline->FirstParameter()
                || last != spline->LastParameter()) {
                throw Base::NotImplementedError("Unsupported cylinder boundary spline");
            }
            if (size_t(spline->NbPoles()) + points.size() > maximumNodes) {
                throw Base::ValueError("Cylinder spline sampling budget");
            }
            for (int i = 2; i < spline->NbPoles(); ++i) {
                interior.push_back(world(spline->Pole(i)));
            }
        }
        else if (const auto circle = occ::down_cast<Geom_Circle>(curve); !circle.IsNull()) {
            const double radius = circle->Radius()
                * std::abs(location.Transformation().ScaleFactor());
            const double required = std::ceil((last - first) * std::sqrt(radius / (8 * remaining)));
            if (!std::isfinite(required) || required > maximumNodes) {
                throw Base::ValueError("Cylinder circle sampling budget");
            }
            const size_t count = std::max(size_t(3), size_t(required));
            if (count + points.size() > maximumNodes) {
                throw Base::ValueError("Cylinder circle sampling budget");
            }
            for (size_t i = 1; i < count; ++i) {
                interior.push_back(
                    world(curve->Value(first + (last - first) * double(i) / double(count)))
                );
            }
        }
        else if (occ::down_cast<Geom_Line>(curve).IsNull()) {
            throw Base::NotImplementedError("Unsupported cylinder boundary curve");
        }
        uint32_t previous = uint32_t(start - 1);
        std::vector<uint32_t> sample;
        if (edgeSamples) {
            sample.push_back(previous);
        }
        for (const auto& p : interior) {
            const auto index = append(p);
            segments.push_back({previous, index});
            previous = index;
            if (edgeSamples) {
                sample.push_back(index);
            }
        }
        segments.push_back({previous, uint32_t(finish - 1)});
        if (edgeSamples) {
            sample.push_back(uint32_t(finish - 1));
            samples.push_back(std::move(sample));
        }
    }
    if (output.size() + points.size() > std::numeric_limits<uint32_t>::max()) {
        throw Base::ValueError("Cylinder line index overflow");
    }
    const auto offset = static_cast<uint32_t>(output.size());
    output.insert(output.end(), points.begin(), points.end());
    for (const auto& line : segments) {
        lines.push_back({line.I1 + offset, line.I2 + offset});
    }
    if (edgeSamples) {
        for (auto& sample : samples) {
            for (auto& index : sample) {
                index += offset;
            }
        }
        *edgeSamples = std::move(samples);
    }
}
}  // namespace Implicit::detail
