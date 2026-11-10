// SPDX-License-Identifier: LGPL-2.1-or-later
#include "PreviewContacts.h"
#include <iostream>
#include <stdexcept>
using Points = std::vector<std::array<float,3>>;
using Triangle = Implicit::detail::contact::Triangle;
using Implicit::detail::checkPreviewContacts;
struct Cancelled {};
size_t checkpointCalls = 0, cancelAt = std::numeric_limits<size_t>::max();
void checkpoint()
{
    if (++checkpointCalls >= cancelAt) throw Cancelled();
}
void require(bool valid, const char* message)
{
    if (!valid) throw std::runtime_error(message);
}
void pair(const char* name, const Points& points, Triangle a, Triangle b, bool allowed)
{
    // Classification must be invariant under ordering and either winding.
    std::sort(a.begin(),a.end());
    do {
        std::sort(b.begin(),b.end());
        do {
            const auto result = checkPreviewContacts(points,{a,b});
            if (result.verified != allowed) throw std::runtime_error(std::string(name)+": "+result.reason);
        } while (std::next_permutation(b.begin(),b.end()));
    } while (std::next_permutation(a.begin(),a.end()));
}
int main()
{
    try {
        pair("coplanar shared edge",{{0,0,0},{1,0,0},{0,1,0},{0,-1,0}},{0,1,2},{0,1,3},true);
        pair("coplanar shared edge overlap",{{0,0,0},{1,0,0},{0,1,0},{1,1,0}},{0,1,2},{0,1,3},false);
        pair("folded shared edge",{{0,0,0},{1,0,0},{0,1,0},{0,0,1}},{0,1,2},{0,1,3},true);
        pair("indexed duplicate",{{0,0,0},{1,0,0},{0,1,0}},{0,1,2},{0,1,2},false);
        pair("unindexed coincident vertex",{{0,0,0},{1,0,0},{0,1,0},{0,0,0},{-1,0,0},{0,-1,0}},
             {0,1,2},{3,4,5},false);
        pair("unindexed coincident edge",{{0,0,0},{1,0,0},{0,1,0},{0,0,0},{1,0,0},{0,-1,0}},
             {0,1,2},{3,4,5},false);
        pair("coplanar shared vertex",{{0,0,0},{1,0,0},{0,1,0},{-1,0,0},{0,-1,0}},
             {0,1,2},{0,3,4},true);
        pair("coplanar crossing",{{0,0,0},{3,0,0},{0,3,0},{1,-1,0},{3,2,0},{-1,1,0}},
             {0,1,2},{3,4,5},false);
        pair("coplanar contained",{{0,0,0},{3,0,0},{0,3,0},{.2f,.2f,0},{.4f,.2f,0},{.2f,.4f,0}},
             {0,1,2},{3,4,5},false);
        pair("shared vertex crossing ray",{{0,0,0},{1,0,0},{0,1,0},{1,0,1},{1,0,-1}},
             {0,1,2},{0,3,4},false);
        pair("shared vertex opposite ray",{{0,0,0},{1,0,0},{0,1,0},{-1,0,1},{-1,0,-1}},
             {0,1,2},{0,3,4},true);
        pair("shared vertex tangent only",{{0,0,0},{1,0,0},{0,1,0},{-1,-1,1},{1,-1,1}},
             {0,1,2},{0,3,4},true);
        pair("noncoplanar crossing",{{0,0,0},{3,0,0},{0,3,0},{1,1,-1},{1,1,1},{2,1,0}},
             {0,1,2},{3,4,5},false);
        pair("separating edge axis",{{0,0,0},{2,0,0},{0,2,0},{1.5f,1.5f,-1},{2,2,-1},{1.5f,1.5f,1}},
             {0,1,2},{3,4,5},true);
        pair("parallel overlapping boxes",{{1,0,0},{0,1,0},{0,0,1},{1,1,0},{0,1,1},{1,0,1}},
             {0,1,2},{3,4,5},true);
        const float tiny = std::numeric_limits<float>::denorm_min();
        pair("subnormal shared edge",{{0,0,0},{tiny,0,0},{0,tiny,0},{0,-tiny,0}},
             {0,1,2},{0,1,3},true);
        const float large = std::ldexp(1.f,100), step = std::ldexp(1.f,80);
        pair("large translated shared edge",{{large,large,large},{large+step,large,large},
             {large,large+step,large},{large,large-step,large}},{0,1,2},{0,1,3},true);
        const Points fan {{0,0,0},{1,0,0},{0,1,0},{-1,0,0},{0,-1,0}};
        const std::vector<Triangle> triangles {{0,1,2},{0,2,3},{0,3,4}};
        require(checkPreviewContacts(fan,triangles).verified,"Valid fan refused");
        const auto controlled=checkPreviewContacts(fan,triangles,20000000,checkpoint);
        require(controlled.verified && checkpointCalls>10,"Contact checkpoints missing");
        const size_t complete=checkpointCalls;
        for (auto stop : {size_t(1),complete/2,complete}) {
            checkpointCalls=0; cancelAt=stop;
            bool aborted=false;
            try { checkPreviewContacts(fan,triangles,20000000,checkpoint); }
            catch (const Cancelled&) { aborted=true; }
            require(aborted,"Contact cancellation returned a certificate");
        }
        require(checkPreviewContacts(fan,triangles).verified,"Contact cancellation changed source");
        const auto exhausted = checkPreviewContacts(fan,triangles,1);
        require(!exhausted.verified && exhausted.reason == "Contact work budget exhausted","Budget promoted");
        require(!checkPreviewContacts(fan,triangles,0).verified,"Zero budget promoted");
        require(!checkPreviewContacts({},triangles).verified,"Empty input promoted");
        require(!checkPreviewContacts(fan,{{0,1,99}}).verified,"Invalid index promoted");
        require(!checkPreviewContacts(fan,{{0,1,1}}).verified,"Repeated index promoted");
        require(!checkPreviewContacts({{0,0,0},{1,0,0},{2,0,0}},{{0,1,2}}).verified,"Collinear promoted");
        const float collapsed = float(std::nextafter(1.,2.));
        require(!checkPreviewContacts({{1,0,0},{collapsed,0,0},{0,1,0}},{{0,1,2}}).verified,"Float collapse promoted");
        for (float bad : {std::numeric_limits<float>::infinity(),std::numeric_limits<float>::quiet_NaN()})
            require(!checkPreviewContacts({{0,0,bad},{1,0,0},{0,1,0}},{{0,1,2}}).verified,"Nonfinite promoted");
        std::cout << "Exact uploaded preview contact tests passed\n";
        return 0;
    }
    catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
