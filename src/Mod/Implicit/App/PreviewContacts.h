// SPDX-License-Identifier: LGPL-2.1-or-later
#pragma once
#include <boost/multiprecision/cpp_int.hpp>
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <limits>
#include <numeric>
#include <string>
#include <vector>

namespace Implicit::detail
{
struct PreviewContacts
{
    bool verified = false;
    size_t boundsTests = 0, pairs = 0;
    std::string reason;
};
namespace contact
{
using Integer = boost::multiprecision::cpp_int;
using Point = std::array<Integer, 3>;
using Triangle = std::array<uint32_t, 3>;
inline Point subtract(const Point& a, const Point& b)
{
    return {a[0]-b[0], a[1]-b[1], a[2]-b[2]};
}
inline Point cross(const Point& a, const Point& b)
{
    return {a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]};
}
inline Integer dot(const Point& a, const Point& b)
{
    return a[0]*b[0]+a[1]*b[1]+a[2]*b[2];
}
inline bool zero(const Point& a) { return a[0] == 0 && a[1] == 0 && a[2] == 0; }
inline bool opposite(const Integer& a, const Integer& b)
{
    return (a < 0 && b > 0) || (a > 0 && b < 0);
}
// Every finite binary32 coordinate times 2^149 is an exact integer, including
// subnormals. No geometric epsilon, decimal conversion or float predicate.
inline Integer coordinate(float value)
{
    static_assert(sizeof(float) == 4 && std::numeric_limits<float>::is_iec559);
    uint32_t bits;
    std::memcpy(&bits, &value, sizeof(bits));
    const unsigned exponent = (bits >> 23) & 255;
    Integer result = bits & 0x7fffff;
    if (exponent) {
        result += 1u << 23;
        result <<= exponent-1;
    }
    if (bits >> 31) result = -result;
    return result;
}
inline Integer orient(const Point& a, const Point& b, const Point& c, unsigned drop)
{
    const auto u = (drop+1)%3, v = (drop+2)%3;
    return (b[u]-a[u])*(c[v]-a[v])-(b[v]-a[v])*(c[u]-a[u]);
}
inline bool inside(const Point& p, const Triangle& t, const std::vector<Point>& points, unsigned drop)
{
    const Integer a = orient(points[t[0]], points[t[1]], p, drop);
    const Integer b = orient(points[t[1]], points[t[2]], p, drop);
    const Integer c = orient(points[t[2]], points[t[0]], p, drop);
    return (a >= 0 && b >= 0 && c >= 0) || (a <= 0 && b <= 0 && c <= 0);
}
inline bool shared(uint32_t i, const Triangle& t)
{
    return std::find(t.begin(), t.end(), i) != t.end();
}
inline bool coplanarAllowed(const Triangle& a, const Triangle& b,
                            const std::vector<Point>& p, const Point& normal)
{
    unsigned drop = 0;
    while (normal[drop] == 0) ++drop;
    // Inclusive point containment catches unindexed coincident coordinates,
    // edge touches and collinear overlaps as well as interior containment.
    for (auto i : a) if (!shared(i, b) && inside(p[i], b, p, drop)) return false;
    for (auto i : b) if (!shared(i, a) && inside(p[i], a, p, drop)) return false;
    for (unsigned i = 0; i < 3; ++i) for (unsigned j = 0; j < 3; ++j) {
        const auto& a0 = p[a[i]]; const auto& a1 = p[a[(i+1)%3]];
        const auto& b0 = p[b[j]]; const auto& b1 = p[b[(j+1)%3]];
        if (opposite(orient(a0,a1,b0,drop), orient(a0,a1,b1,drop))
            && opposite(orient(b0,b1,a0,drop), orient(b0,b1,a1,drop))) return false;
    }
    return true;
}
// Intersection of a triangle with a plane through its indexed shared vertex:
// either only that vertex, or a single ray truncated by the opposite edge.
inline Point intersectionRay(const Triangle& t, uint32_t vertex,
                             const std::vector<Point>& p, const Point& otherNormal)
{
    std::array<uint32_t, 2> others {}; unsigned count = 0;
    for (auto i : t) if (i != vertex) others[count++] = i;
    const Point u = subtract(p[others[0]], p[vertex]), v = subtract(p[others[1]], p[vertex]);
    const Integer a = dot(u, otherNormal), b = dot(v, otherNormal);
    if (a == 0) return u;
    if (b == 0) return v;
    if (!opposite(a,b)) return {0,0,0};
    const Integer aa = a < 0 ? -a : a, bb = b < 0 ? -b : b;
    return {bb*u[0]+aa*v[0], bb*u[1]+aa*v[1], bb*u[2]+aa*v[2]};
}
inline bool pairAllowed(const Triangle& a, const Triangle& b, const std::vector<Point>& p)
{
    std::vector<uint32_t> common;
    for (auto i : a) if (shared(i,b)) common.push_back(i);
    if (common.size() == 3) return false;
    const Point na = cross(subtract(p[a[1]],p[a[0]]), subtract(p[a[2]],p[a[0]]));
    const Point nb = cross(subtract(p[b[1]],p[b[0]]), subtract(p[b[2]],p[b[0]]));
    const bool parallel = zero(cross(na,nb));
    if (parallel) {
        if (dot(na,subtract(p[b[0]],p[a[0]])) != 0) return true;
        return coplanarAllowed(a,b,p,na);
    }
    if (common.size() == 2) return true; // Plane intersection is exactly the indexed edge.
    if (common.size() == 1) {
        const Point ra = intersectionRay(a,common[0],p,nb);
        const Point rb = intersectionRay(b,common[0],p,na);
        return zero(ra) || zero(rb) || dot(ra,rb) < 0;
    }
    const auto separates = [&](const Point& axis) {
        if (zero(axis)) return false;
        Integer amin = dot(axis,p[a[0]]), amax = amin;
        Integer bmin = dot(axis,p[b[0]]), bmax = bmin;
        for (unsigned i = 1; i < 3; ++i) {
            const Integer av = dot(axis,p[a[i]]), bv = dot(axis,p[b[i]]);
            amin = std::min(amin,av); amax = std::max(amax,av);
            bmin = std::min(bmin,bv); bmax = std::max(bmax,bv);
        }
        return amax < bmin || bmax < amin;
    };
    if (separates(na) || separates(nb)) return true;
    for (unsigned i = 0; i < 3; ++i) for (unsigned j = 0; j < 3; ++j) {
        if (separates(cross(subtract(p[a[(i+1)%3]],p[a[i]]),
                            subtract(p[b[(j+1)%3]],p[b[j]])))) return true;
    }
    return false; // No strict separation proof: contact/crossing or unresolved.
}
} // namespace contact

inline PreviewContacts checkPreviewContacts(const std::vector<std::array<float,3>>& points,
                                           const std::vector<contact::Triangle>& triangles,
                                           size_t maximumBoundsTests = 20000000,
                                           void (*checkpoint)() = nullptr)
{
    if (checkpoint) checkpoint();
    PreviewContacts result;
    const auto fail = [&](const char* reason) { result.reason = reason; return result; };
    if (points.empty() || triangles.empty() || points.size() > 250000
        || triangles.size() > 500000 || maximumBoundsTests == 0 || maximumBoundsTests > 50000000)
        return fail("Invalid contact input size or work budget");
    std::vector<contact::Point> exact;
    exact.reserve(points.size());
    for (const auto& p : points) {
        if (checkpoint) checkpoint();
        if (!std::all_of(p.begin(),p.end(),[](float v) { return std::isfinite(v); }))
            return fail("Nonfinite uploaded contact coordinate");
        exact.push_back({contact::coordinate(p[0]),contact::coordinate(p[1]),contact::coordinate(p[2])});
    }
    struct Box { std::array<float,3> low, high; size_t triangle; };
    std::vector<Box> boxes; boxes.reserve(triangles.size());
    for (size_t i = 0; i < triangles.size(); ++i) {
        if (checkpoint) checkpoint();
        const auto& t = triangles[i];
        for (auto index : t) if (index >= points.size()) return fail("Invalid contact triangle index");
        if (contact::zero(contact::cross(contact::subtract(exact[t[1]],exact[t[0]]),
                                         contact::subtract(exact[t[2]],exact[t[0]]))))
            return fail("Degenerate uploaded contact triangle");
        Box box {points[t[0]],points[t[0]],i};
        for (auto index : t) for (unsigned axis = 0; axis < 3; ++axis) {
            box.low[axis] = std::min(box.low[axis],points[index][axis]);
            box.high[axis] = std::max(box.high[axis],points[index][axis]);
        }
        boxes.push_back(box);
    }
    // Inclusive AABBs: touching boxes must reach the exact predicates.
    size_t comparisons = 0;
    std::sort(boxes.begin(),boxes.end(),[&](const Box& a, const Box& b) {
        if (checkpoint && (++comparisons % 1024 == 0)) checkpoint();
        return a.low[0] < b.low[0] || (a.low[0] == b.low[0] && a.triangle < b.triangle);
    });
    std::vector<size_t> active;
    for (size_t i = 0; i < boxes.size(); ++i) {
        if (checkpoint) checkpoint();
        const auto& current = boxes[i];
        size_t retained = 0;
        for (auto j : active) {
            if (checkpoint) checkpoint();
            if (++result.boundsTests > maximumBoundsTests) return fail("Contact work budget exhausted");
            const auto& previous = boxes[j];
            if (previous.high[0] < current.low[0]) continue;
            active[retained++] = j;
            if (previous.high[1] < current.low[1] || current.high[1] < previous.low[1]
                || previous.high[2] < current.low[2] || current.high[2] < previous.low[2]) continue;
            ++result.pairs;
            if (!contact::pairAllowed(triangles[current.triangle],triangles[previous.triangle],exact))
                return fail("Uploaded triangles contact beyond their indexed shared simplex");
        }
        active.resize(retained);
        active.push_back(i);
    }
    if (checkpoint) checkpoint();
    result.verified = true;
    return result;
}
} // namespace Implicit::detail
