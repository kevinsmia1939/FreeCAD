// SPDX-License-Identifier: LGPL-2.1-or-later
#pragma once
#include <BRepClass3d_ImplicitBox.hxx>
#include <BRepClass3d_ImplicitWork.hxx>
#include <BRepMesh_ImplicitBoundary.hxx>
#include <atomic>
#include <memory>
#include <mutex>
#include <optional>
#include <string>

namespace Implicit
{
// No Python, document, view-provider or shared mutable OCCT objects enter a job.
struct NativeSolidRequest
{
    std::string boundary;
    double tolerance = .1;
    int resolution = 32, depth = 16, geometryDepth = -1;
    std::size_t cells = 4000000, tests = 2000000, separators = 2000000;
    std::size_t geometryCells = 2000000, segments = 8000000;
};

struct NativeSolidResult
{
    NativeSolidRequest request;
    std::unique_ptr<BRepClass3d_ImplicitBox::NativeSolids> solid;
    std::optional<BRepMesh_ImplicitBoundary::Result> surface;
    std::string surfaceError;
};

class NativeSolidJob: public BRepClass3d_ImplicitWork::Control
{
public:
    enum class State { Queued, Running, Ready, Failed, Cancelled, Consumed };
    struct Status
    {
        State state;
        bool cancelling;
        BRepClass3d_ImplicitWork::Phase phase;
        std::size_t checkpoints;
        std::string error;
    };
    explicit NativeSolidJob(NativeSolidRequest request);
    bool IsCancelled() const override;
    void EnterPhase(BRepClass3d_ImplicitWork::Phase phase) override;
    void cancel();
    Status status() const;
    std::unique_ptr<NativeSolidResult> take();
    void run();

private:
    NativeSolidRequest request;
    std::atomic_bool cancelled {false};
    mutable std::atomic_size_t checkpoints {0};
    std::atomic<BRepClass3d_ImplicitWork::Phase> phase {BRepClass3d_ImplicitWork::Phase::Copying};
    mutable std::mutex mutex;
    State state = State::Queued;
    std::string error;
    std::unique_ptr<NativeSolidResult> result;
};

// One worker and at most one additional outstanding request bound CPU/memory.
// The executor cancels and joins its worker at shutdown; jobs never detach.
std::shared_ptr<NativeSolidJob> submitNativeSolid(NativeSolidRequest request);
}
