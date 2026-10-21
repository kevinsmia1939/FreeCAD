// SPDX-License-Identifier: LGPL-2.1-or-later
#include "NativeSolidJob.h"
#include <BRepClass3d_ImplicitBoxIO.hxx>
#include <Standard_AbortiveTransaction.hxx>
#include <Standard_Failure.hxx>
#include <algorithm>
#include <condition_variable>
#include <deque>
#include <sstream>
#include <stdexcept>
#include <thread>

using namespace Implicit;

NativeSolidJob::NativeSolidJob(NativeSolidRequest input): request(std::move(input)) {}

bool NativeSolidJob::IsCancelled() const
{
    checkpoints.fetch_add(1, std::memory_order_relaxed);
    return cancelled.load(std::memory_order_relaxed);
}

void NativeSolidJob::EnterPhase(BRepClass3d_ImplicitWork::Phase value)
{
    phase.store(value, std::memory_order_relaxed);
}

void NativeSolidJob::cancel()
{
    cancelled.store(true, std::memory_order_relaxed);
    std::lock_guard<std::mutex> lock(mutex);
    if (state == State::Queued) { request.boundary.clear(); }
    if (state == State::Queued || state == State::Ready) {
        result.reset();
        state = State::Cancelled;
    }
}

NativeSolidJob::Status NativeSolidJob::status() const
{
    std::lock_guard<std::mutex> lock(mutex);
    return {state, cancelled.load(std::memory_order_relaxed),
            phase.load(std::memory_order_relaxed), checkpoints.load(std::memory_order_relaxed), error};
}

std::unique_ptr<NativeSolidResult> NativeSolidJob::take()
{
    std::lock_guard<std::mutex> lock(mutex);
    if (state != State::Ready || cancelled.load(std::memory_order_relaxed)) {
        throw std::runtime_error("Native solid job has no available result");
    }
    state = State::Consumed;
    return std::move(result);
}

void NativeSolidJob::run()
{
    {
        std::lock_guard<std::mutex> lock(mutex);
        if (cancelled.load(std::memory_order_relaxed)) {
            state = State::Cancelled;
            return;
        }
        state = State::Running;
    }
    try {
        BRepClass3d_ImplicitWork::Scope scope(*this);
        BRepClass3d_ImplicitWork::EnterPhase(BRepClass3d_ImplicitWork::Phase::Copying);
        BRepClass3d_ImplicitBox::Boundary boundary;
        std::istringstream input(request.boundary);
        BRepClass3d_ImplicitBoxIO::Read(input, boundary);
        auto output = std::make_unique<NativeSolidResult>();
        output->solid = std::make_unique<BRepClass3d_ImplicitBox::NativeSolids>(
            BRepClass3d_ImplicitBox::BuildNativeSolids(boundary, request.tolerance,
                request.resolution, request.depth, request.cells, request.tests, request.separators,
                request.geometryCells, request.segments,
                request.geometryDepth == -1 ? request.depth : request.geometryDepth));
        if (!output->solid->Constructed || !output->solid->Validated) {
            throw std::runtime_error(output->solid->Reason);
        }
        BRepClass3d_ImplicitWork::Checkpoint();
        const auto& parts = output->solid->Boundary.FaceComponents;
        if (std::any_of(parts.begin(), parts.end(), [](int component) { return component >= 0; })) {
            try {
                output->surface = BRepMesh_ImplicitBoundary::Tessellate(output->solid->Boundary.Source, .1);
            }
            catch (const Standard_AbortiveTransaction&) { throw; }
            catch (const Standard_Failure& failure) {
                output->surfaceError = failure.what();
            }
        }
        BRepClass3d_ImplicitWork::Checkpoint();
        output->request = std::move(request);
        std::lock_guard<std::mutex> lock(mutex);
        if (cancelled.load(std::memory_order_relaxed)) {
            state = State::Cancelled;
        }
        else {
            result = std::move(output);
            state = State::Ready;
        }
    }
    catch (const Standard_AbortiveTransaction&) {
        std::lock_guard<std::mutex> lock(mutex);
        state = State::Cancelled;
    }
    catch (const Standard_Failure& failure) {
        std::lock_guard<std::mutex> lock(mutex);
        error = failure.what();
        state = cancelled.load(std::memory_order_relaxed) ? State::Cancelled : State::Failed;
    }
    catch (const std::exception& failure) {
        std::lock_guard<std::mutex> lock(mutex);
        error = failure.what();
        state = cancelled.load(std::memory_order_relaxed) ? State::Cancelled : State::Failed;
    }
    catch (...) {
        std::lock_guard<std::mutex> lock(mutex);
        error = "Unknown native solid background failure";
        state = State::Failed;
    }
    request.boundary.clear();
}

namespace
{
class Executor
{
public:
    Executor(): worker([this] { run(); }) {}
    ~Executor()
    {
        {
            std::lock_guard<std::mutex> lock(mutex);
            stopping = true;
            if (active) { active->cancel(); }
            for (const auto& job : queue) { job->cancel(); }
        }
        changed.notify_one();
        worker.join();
    }
    std::shared_ptr<NativeSolidJob> submit(NativeSolidRequest request)
    {
        std::lock_guard<std::mutex> lock(mutex);
        queue.erase(std::remove_if(queue.begin(), queue.end(), [](const auto& job) {
            return job->status().state == NativeSolidJob::State::Cancelled;
        }), queue.end());
        if (queue.size() + std::size_t(bool(active)) >= 2) {
            throw std::runtime_error("Native solid worker queue is full; wait or cancel an existing build");
        }
        auto job = std::make_shared<NativeSolidJob>(std::move(request));
        queue.push_back(job);
        changed.notify_one();
        return job;
    }
private:
    void run()
    {
        std::unique_lock<std::mutex> lock(mutex);
        for (;;) {
            changed.wait(lock, [this] { return stopping || !queue.empty(); });
            if (stopping) { return; }
            active = queue.front();
            queue.pop_front();
            auto job = active;
            lock.unlock();
            job->run();
            lock.lock();
            active.reset();
        }
    }
    std::mutex mutex;
    std::condition_variable changed;
    std::deque<std::shared_ptr<NativeSolidJob>> queue;
    std::shared_ptr<NativeSolidJob> active;
    bool stopping = false;
    std::thread worker;
};
}

std::shared_ptr<NativeSolidJob> Implicit::submitNativeSolid(NativeSolidRequest request)
{
    static Executor executor;
    return executor.submit(std::move(request));
}
