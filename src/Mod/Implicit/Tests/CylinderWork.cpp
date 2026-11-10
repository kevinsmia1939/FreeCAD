// SPDX-License-Identifier: LGPL-2.1-or-later
#include "../App/CylinderPreview.h"
#include "../App/CylinderBoundary.h"
#include <BRepClass3d_ImplicitWork.hxx>
#include <BRep_Builder.hxx>
#include <Geom_ImplicitGyroid.hxx>
#include <Standard_AbortiveTransaction.hxx>
#include <iostream>
#include <map>
#include <sstream>
#include <stdexcept>
using Work = BRepClass3d_ImplicitWork;
using IO = BRepClass3d_ImplicitCylinderIO;
using Ops = BRepClass3d_ImplicitCylinder;
void require(bool valid, const char* message)
{
    if (!valid) throw std::runtime_error(message);
}
struct Control : Work::Control
{
    mutable size_t calls = 0;
    mutable std::map<Work::Phase,size_t> phases;
    Work::Phase phase = Work::Phase::Copying, stopPhase = Work::Phase::Copying;
    size_t stop = std::numeric_limits<size_t>::max();
    bool byPhase = false;
    bool IsCancelled() const override
    {
        ++calls;
        const auto count = ++phases[phase];
        return byPhase ? phase == stopPhase && count >= stop : calls >= stop;
    }
    void EnterPhase(Work::Phase value) override { phase = value; }
};
template<class Operation> void cancelled(Control& control, Operation operation)
{
    bool aborted = false;
    try { Work::Scope scope(control); operation(); }
    catch (const Standard_AbortiveTransaction&) { aborted = true; }
    require(aborted,"Cancellation was converted into a result");
}
int main()
{
    try {
        TopoDS_Face field;
        BRep_Builder().MakeImplicitFace(field,new Geom_ImplicitGyroid(10,.21),
            gp_Pnt(-10,-10,-10),gp_Pnt(10,10,10),TopLoc_Location(),.1);
        BRep_ImplicitCylinderSection::Settings settings;
        settings.Radius=.5; settings.AngleMinimum=.27;
        settings.AngleMaximum=.27+2*std::acos(-1.);
        settings.HeightMinimum=-1.7; settings.HeightMaximum=1.3;
        const auto geometry=Ops::CheckShellGeometry(field,settings);
        require(geometry.BoundaryVerified,"Initial geometry failed");
        const auto original=Ops::BuildNativeSolid(geometry,Ops::VolumeSettings());
        require(original.SolidValidated,"Initial solid failed");
        std::ostringstream record; IO::Write(original,record);
        IO::StoredSolid stored; std::istringstream input(record.str()); IO::Read(input,stored);
        IO::Geometry ready;
        Control qualification;
        { Work::Scope scope(qualification); ready=IO::CheckGeometry(stored); }
        require(ready.Verified && qualification.calls>10,"Qualification ignored work scope");
        for (auto stop : {size_t(1),qualification.calls/2,qualification.calls}) {
            Control control; control.stop=stop;
            cancelled(control,[&] { IO::CheckGeometry(stored); });
        }
        Control reading;
        { Work::Scope scope(reading); std::istringstream stream(record.str()); IO::Read(stream,stored); }
        for (auto stop : {size_t(1),reading.calls/2,reading.calls}) {
            Control control; control.stop=stop;
            const auto previous=stored.Shape;
            cancelled(control,[&] { std::istringstream stream(record.str()); IO::Read(stream,stored); });
            require(stored.Shape.IsSame(previous),"Cancelled read replaced destination graph");
        }
        Control volume;
        IO::Solid solid;
        { Work::Scope scope(volume); solid=IO::QualifySolid(ready,Ops::VolumeSettings()); }
        require(solid.Verified && volume.calls>10,"Volume ignored work scope");
        for (auto stop : {size_t(1),volume.calls/2,volume.calls}) {
            Control control; control.stop=stop;
            cancelled(control,[&] { IO::QualifySolid(ready,Ops::VolumeSettings()); });
        }
        std::ostringstream before; IO::Write(solid,before);
        Control previewControl;
        Implicit::CylinderPreview preview;
        { Work::Scope scope(previewControl); preview=Implicit::buildCylinderPreview(solid,6); }
        require(preview.surfaceDistanceVerified(),"Baseline preview unverified");
        for (auto phase : {Work::Phase::Meshing,Work::Phase::Coverage,Work::Phase::ContactAudit}) {
            const auto count=previewControl.phases[phase];
            require(count>10,"Preview phase lacked checkpoints");
            for (auto stop : {size_t(1),count/2,count}) {
                Control control; control.byPhase=true; control.stopPhase=phase; control.stop=stop;
                cancelled(control,[&] { Implicit::buildCylinderPreview(solid,6); });
            }
        }
        using Line = Data::ComplexGeoData::Line;
        std::vector<Base::Vector3d> points {Base::Vector3d(1,2,3)};
        std::vector<Line> lines {{0,0}};
        std::vector<std::vector<uint32_t>> baselineSamples {{42}};
        Control boundary;
        { Work::Scope scope(boundary); Implicit::detail::cylinderBoundary(solid.Shape,.01,points,lines,&baselineSamples); }
        for (auto stop : {size_t(1),boundary.calls/2,boundary.calls}) {
            std::vector<Base::Vector3d> output {Base::Vector3d(1,2,3)};
            std::vector<Line> segments {{0,0}};
            std::vector<std::vector<uint32_t>> samples {{42}};
            Control control; control.stop=stop;
            cancelled(control,[&] { Implicit::detail::cylinderBoundary(solid.Shape,.01,output,segments,&samples); });
            require(output.size()==1 && output[0]==Base::Vector3d(1,2,3)
                && segments.size()==1 && samples==std::vector<std::vector<uint32_t>>{{42}},
                "Cancelled sampler published partial data");
        }
        std::ostringstream after; IO::Write(solid,after);
        require(before.str()==after.str(),"Cancellation mutated source record");
        require(!stored.GeometryVerified && !stored.SolidValidated,"Stored flags promoted by cancellation");
        require(Implicit::buildCylinderPreview(solid,6).surfaceDistanceVerified(),"Cancelled scope leaked");
        std::cout<<"native cylinder cancellation tests passed\n";
        return 0;
    }
    catch (const Standard_Failure& error) { std::cerr<<error.what()<<'\n'; }
    catch (const std::exception& error) { std::cerr<<error.what()<<'\n'; }
    return 1;
}
