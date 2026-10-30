// SPDX-License-Identifier: LGPL-2.1-or-later
#include "CylinderPreview.h"
#include "CylinderBoundary.h"
#include <BRep_ImplicitTool.hxx>
#include <BRep_TImplicitFace.hxx>
#include <Geom_ImplicitGyroid.hxx>
#include <algorithm>
#include <map>
#include <set>

namespace Implicit
{
CylinderPreview buildCylinderPreview(const CylinderGeometry::Solid& solid, unsigned resolution)
{
    const auto require = [](bool ok, const char* message) {
        if (!ok) {
            throw Base::ValueError(message);
        }
    };
    require(solid.Verified && solid.Source.Verified, "Cylinder preview needs a qualified solid");
    require(resolution >= 2 && resolution <= 64, "Cylinder preview resolution must be 2..64");
    const auto& source = solid.Source;
    const auto& s = source.Parameters;
    const auto& primitive = source.Source.Primitive;
    const auto axial = BRepClass3d_ImplicitCylinder::CheckAxialField(primitive, s);
    require(axial.MonotonicityVerified, axial.Reason.c_str());
    const auto data = occ::down_cast<BRep_TImplicitFace>(primitive.TShape());
    const auto* field = static_cast<const Geom_ImplicitGyroid*>(data->Field().get());
    const double scale = std::abs(
        (primitive.Location() * data->Location()).Transformation().ScaleFactor()
    );
    const double k = 2 * std::acos(-1.) / field->Period() / scale, hessian = 4 * k * k;
    const double precision = 32768 * std::numeric_limits<double>::epsilon()
        * (1 + s.Frame.Location().Distance(gp_Pnt()) + s.Radius + std::abs(s.HeightMinimum)
           + std::abs(s.HeightMaximum));
    const double reserve = precision
        * (1 + hessian + field->LipschitzBound() / scale + std::abs(field->IsoValue()));
    const double gradientReserve = 32768 * std::numeric_limits<double>::epsilon()
            * (1 + field->LipschitzBound() / scale + hessian)
        + hessian * precision;
    const gp_Vec x(s.Frame.XDirection()), y(s.Frame.YDirection()), axis(s.Frame.Direction());
    const auto local = [&](const Base::Vector3d& p) {
        const gp_Vec delta(s.Frame.Location(), gp_Pnt(p.x, p.y, p.z));
        return gp_Pnt(delta.Dot(x), delta.Dot(y), delta.Dot(axis));
    };
    const auto world = [&](double px, double py, double pz) {
        const auto p = s.Frame.Location().Translated(x * px + y * py + axis * pz);
        return Base::Vector3d(p.X(), p.Y(), p.Z());
    };
    CylinderPreview result;
    result.curveDeflection = std::min(
        {.01, s.DistanceTolerance / 8, s.Radius / (4 * double(resolution) * double(resolution))}
    );
    std::vector<Data::ComplexGeoData::Line> lines;
    std::vector<std::vector<uint32_t>> samples;
    detail::cylinderBoundary(solid.Shape, result.curveDeflection, result.points, lines, &samples);
    result.edges = samples;
    using Map = NCollection_IndexedMap<TopoDS_Shape, TopTools_ShapeMapHasher>;
    Map nativeVertices;
    TopExp::MapShapes(solid.Shape, TopAbs_VERTEX, nativeVertices);
    result.nativeVertices = unsigned(nativeVertices.Size());
    Map edges, capEdges, fieldEdges;
    TopExp::MapShapes(solid.Shape, TopAbs_EDGE, edges);
    TopExp::MapShapes(source.Source.Faces[0], TopAbs_EDGE, capEdges);
    TopExp::MapShapes(source.Source.Faces[2], TopAbs_EDGE, fieldEdges);
    require(
        capEdges.Size() == 2 && fieldEdges.Size() == 1 && edges.Size() == 4,
        "Unsupported cylinder preview graph"
    );
    auto cap = samples.at(size_t(edges.FindIndex(capEdges.FindKey(1)) - 1));
    auto capSecond = samples.at(size_t(edges.FindIndex(capEdges.FindKey(2)) - 1));
    if (cap.back() != capSecond.front()) {
        std::reverse(capSecond.begin(), capSecond.end());
    }
    require(cap.back() == capSecond.front(), "Cap preview arcs do not share an endpoint");
    cap.insert(cap.end(), capSecond.begin() + 1, capSecond.end());
    auto sheet = samples.at(size_t(edges.FindIndex(fieldEdges.FindKey(1)) - 1));
    require(cap.front() == cap.back() && sheet.front() == sheet.back(), "Open cylinder preview boundary");
    cap.pop_back();
    sheet.pop_back();
    uint32_t capSeam = 0, fieldSeam = sheet.front();
    bool found = false;
    for (size_t i = 1; i <= edges.Size(); ++i) {
        if (!capEdges.Contains(edges.FindKey(i)) && !fieldEdges.Contains(edges.FindKey(i))) {
            const auto& seam = samples.at(size_t(i - 1));
            if (seam.front() == fieldSeam) {
                capSeam = seam.back();
            }
            else {
                require(seam.back() == fieldSeam, "Unshared cylinder preview seam");
                capSeam = seam.front();
            }
            require(seam.size() == 2, "Unexpected subdivided cylinder seam");
            found = true;
        }
    }
    require(found, "Missing cylinder preview seam");
    const double turn = 2 * std::acos(-1.);
    const auto order = [&](std::vector<uint32_t>& ring, uint32_t seam) {
        std::set<std::pair<uint32_t, uint32_t>> boundary;
        for (size_t i = 0; i < ring.size(); ++i) {
            boundary.insert(std::minmax(ring[i], ring[(i + 1) % ring.size()]));
        }
        std::vector<std::pair<double, uint32_t>> sorted;
        for (auto index : ring) {
            const auto p = local(result.points.at(index));
            double u = std::fmod(std::atan2(p.Y(), p.X()) - s.AngleMinimum, turn);
            if (u < 0) {
                u += turn;
            }
            if (index == seam) {
                u = 0;
            }
            sorted.emplace_back(u, index);
        }
        std::sort(sorted.begin(), sorted.end());
        ring.clear();
        std::vector<double> angles;
        for (const auto& entry : sorted) {
            angles.push_back(entry.first);
            ring.push_back(entry.second);
        }
        require(ring.size() >= 3 && ring.front() == seam, "Invalid cylinder preview winding");
        for (size_t i = 0; i < ring.size(); ++i) {
            require(
                boundary.contains(std::minmax(ring[i], ring[(i + 1) % ring.size()])),
                "Cylinder preview angular reorder crossed a native edge"
            );
        }
        angles.push_back(turn);
        return angles;
    };
    const auto capAngles = order(cap, capSeam), fieldAngles = order(sheet, fieldSeam);
    require(
        result.points.size() + size_t(resolution - 1) * sheet.size() + 2 <= 250000,
        "Cylinder preview node budget"
    );
    const auto append = [&](const Base::Vector3d& p) {
        require(result.points.size() < 250000, "Cylinder preview node budget");
        result.points.push_back(p);
        return uint32_t(result.points.size() - 1);
    };
    const bool bottom = source.Source.Negative == (axial.Direction > 0);
    const double capHeight = bottom ? s.HeightMinimum : s.HeightMaximum;
    const auto emit = [&](uint32_t a, uint32_t b, uint32_t c, unsigned face) {
        require(a != b && b != c && a != c, "Degenerate cylinder preview indices");
        auto normal = (result.points[b] - result.points[a]).Cross(result.points[c] - result.points[a]);
        Base::Vector3d expected;
        if (face == 1) {
            expected = Base::Vector3d(axis.X(), axis.Y(), axis.Z()) * (bottom ? -1. : 1.);
        }
        else if (face == 3) {
            expected = Base::Vector3d(axis.X(), axis.Y(), axis.Z())
                * (source.Source.Negative ? axial.Direction : -axial.Direction);
        }
        else {
            const auto p = local((result.points[a] + result.points[b] + result.points[c]) / 3);
            const gp_Vec radial = x * p.X() + y * p.Y();
            expected = Base::Vector3d(radial.X(), radial.Y(), radial.Z());
        }
        require(
            std::isfinite(normal.Length()) && normal.Length() > 0,
            "Degenerate cylinder preview triangle"
        );
        if (normal.Dot(expected) < 0) {
            std::swap(b, c);
        }
        require(result.triangles.size() < 500000, "Cylinder preview triangle budget");
        result.triangles.push_back({a, b, c});
        result.faces.push_back(face);
    };
    const auto center = append(world(0, 0, capHeight));
    for (size_t i = 0; i < cap.size(); ++i) {
        emit(center, cap[i], cap[(i + 1) % cap.size()], 1);
    }
    size_t ci = 0, fi = 0;
    while (ci < cap.size() || fi < sheet.size()) {
        const auto c = cap[ci % cap.size()], f = sheet[fi % sheet.size()];
        if (ci < cap.size() && (fi == sheet.size() || capAngles[ci + 1] < fieldAngles[fi + 1])) {
            emit(c, cap[(ci + 1) % cap.size()], f, 2);
            ++ci;
        }
        else {
            emit(c, sheet[(fi + 1) % sheet.size()], f, 2);
            ++fi;
        }
    }
    const double rootWidth = std::min(.001, s.DistanceTolerance / 64);
    require(rootWidth > 8 * precision, "Cylinder preview root precision");
    const auto root = [&](double px, double py) {
        double low = s.HeightMinimum, high = s.HeightMaximum;
        const auto value = [&](double z) {
            require(result.rootTests++ < 2000000, "Cylinder preview root budget");
            const auto p = world(px, py, z);
            const double v = axial.Direction
                * BRep_ImplicitTool::Value(primitive, gp_Pnt(p.x, p.y, p.z));
            require(std::isfinite(v), "Nonfinite cylinder preview field");
            return v;
        };
        require(value(low) < -reserve && value(high) > reserve, "Cylinder preview root bracket");
        for (int step = 0; step < 128 && high - low > rootWidth; ++step) {
            const double middle = low + (high - low) * .5, v = value(middle);
            if (v > reserve) {
                high = middle;
            }
            else if (v < -reserve) {
                low = middle;
            }
            else {
                const auto p = world(px, py, middle);
                const double g = axial.Direction
                        * BRep_ImplicitTool::Gradient(primitive, gp_Pnt(p.x, p.y, p.z)).Dot(axis)
                    - gradientReserve;
                double error = (std::abs(v) + reserve) / axial.DerivativeLowerBound;
                if (g > 0) {
                    const double candidate = 2 * (std::abs(v) + reserve) / g;
                    if (hessian * candidate <= g * .5) {
                        error = std::min(error, candidate);
                    }
                }
                const double a = std::max(low, middle - error), b = std::min(high, middle + error);
                require(a <= b && b - a < high - low, "Cylinder preview unresolved root");
                low = a;
                high = b;
            }
        }
        require(high - low <= rootWidth, "Cylinder preview root iteration budget");
        result.rootPointBound = std::max(result.rootPointBound, (high - low) * .5 + precision);
        return append(world(px, py, low + (high - low) * .5));
    };
    const auto fieldCenter = root(0, 0);
    std::vector<uint32_t> previous;
    for (unsigned ring = 1; ring <= resolution; ++ring) {
        std::vector<uint32_t> current;
        for (size_t j = 0; j < sheet.size(); ++j) {
            if (ring == resolution) {
                current.push_back(sheet[j]);
            }
            else {
                const auto p = local(result.points[sheet[j]]);
                const double radial = std::hypot(p.X(), p.Y());
                require(radial > precision, "Cylinder preview boundary at axis");
                const double factor = double(ring) / resolution
                    * std::min(1., (s.Radius - precision) / radial);
                current.push_back(root(p.X() * factor, p.Y() * factor));
            }
        }
        for (size_t j = 0; j < sheet.size(); ++j) {
            const size_t next = (j + 1) % sheet.size();
            if (ring == 1) {
                emit(fieldCenter, current[j], current[next], 3);
            }
            else {
                emit(previous[j], current[j], current[next], 3);
                emit(previous[j], current[next], previous[next], 3);
            }
        }
        previous = std::move(current);
    }
    struct Use
    {
        unsigned count = 0;
        int orientation = 0;
    };
    std::map<std::pair<uint32_t, uint32_t>, Use> incidence;
    std::vector<bool> used(result.points.size(), false);
    for (const auto& triangle : result.triangles) {
        for (size_t i = 0; i < 3; ++i) {
            const auto a = triangle[i], b = triangle[(i + 1) % 3];
            auto& use = incidence[std::minmax(a, b)];
            ++use.count;
            use.orientation += a < b ? 1 : -1;
            used[a] = true;
        }
    }
    for (const auto& use : incidence) {
        require(
            use.second.count == 2 && use.second.orientation == 0,
            "Open or inconsistently oriented cylinder preview"
        );
    }
    require(
        std::all_of(used.begin(), used.end(), [](bool v) { return v; }),
        "Unused cylinder preview node"
    );
    require(
        int64_t(result.points.size()) - int64_t(incidence.size()) + int64_t(result.triangles.size())
            == 2,
        "Cylinder preview Euler mismatch"
    );
    for (size_t i = 0; i < result.triangles.size(); ++i) {
        for (auto index : result.triangles[i]) {
            const auto& p = result.points[index];
            gp_Vec n;
            if (result.faces[i] == 1) {
                n = axis * (bottom ? -1. : 1.);
            }
            else if (result.faces[i] == 2) {
                const auto q = local(p);
                n = x * q.X() + y * q.Y();
            }
            else {
                n = BRep_ImplicitTool::Gradient(primitive, gp_Pnt(p.x, p.y, p.z))
                    * (source.Source.Negative ? 1. : -1.);
            }
            require(std::isfinite(n.Magnitude()) && n.Magnitude() > 0, "Cylinder preview normal");
            n.Normalize();
            result.cornerNormals.emplace_back(n.X(), n.Y(), n.Z());
        }
    }
    for (const auto& p : result.points) {
        const Base::Vector3d upload(double(float(p.x)), double(float(p.y)), double(float(p.z)));
        const double displacement = (upload - p).Length();
        require(std::isfinite(displacement), "Cylinder preview float upload overflow");
        result.uploadBound = std::max(result.uploadBound, displacement);
    }
    require(
        result.uploadBound < s.DistanceTolerance,
        "Cylinder preview upload displacement exceeds geometry tolerance"
    );
    return result;
}
}  // namespace Implicit
