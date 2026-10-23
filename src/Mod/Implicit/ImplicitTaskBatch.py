# SPDX-License-Identifier: LGPL-2.1-or-later
"""Transaction-owned source preparation followed by native-solid peer builds."""
import FreeCAD as App
import ImplicitOCCT as native
from ImplicitMixed import MixedBoundary
from ImplicitMixedRecompute import Request, same_inputs
from ImplicitSolid import NativeSolid, BUILD_LIMITS
from ImplicitSolidBatch import SolidBatch


class SourceBatch(SolidBatch):
    status_kind = "source"

    def __init__(self, sources, transaction):
        self.objects = list(dict.fromkeys(sources))
        self.document = self.objects[0].Document
        self.document_name = self.document.Name
        self.transaction, self.token = transaction, object()
        self.job, self.results = None, []
        self.state, self.phase, self.error = "pending", "queued", ""
        self._transaction()
        self.requests = []
        for obj in self.objects:
            if (obj.Document != self.document or not isinstance(obj.Proxy, MixedBoundary)
                    or obj.Proxy._restore_failed or obj.Proxy._pending_job is not None):
                raise ValueError("Source preview requires available same-document owners")
            self.requests.append(Request(obj, obj.Proxy._fingerprint(obj)))
        try:
            for obj in self.objects:
                obj.Proxy._pending_job = self.token
                obj.Geometry = None
                obj.InputFingerprint = ""
                obj.BackendStatus = "Pending native source task preview"
        except Exception:
            self.cancel()
            raise

    def _check(self):
        self._transaction()
        for request in self.requests:
            obj = request.obj
            if (not obj.isValid() or obj.Document != self.document or obj.Proxy is not request.proxy
                    or obj.Proxy._pending_job is not self.token or not same_inputs(request)):
                raise ValueError("Source preview inputs changed; Apply again")

    def _start(self):
        request = self.requests[len(self.results)]
        self.job = native.start_boundary_job_from_record(request.face, request.box_record, *request.settings)

    def _take(self):
        return native.take_boundary_job(self.job)

    def _publish(self):
        for request, result in zip(self.requests, self.results):
            request.proxy.publish(request.obj, result, request.inputs, request.field_record,
                                  request.box_record, request.settings)


def target_settings(obj):
    return (obj.Source, obj.SolidSchema, obj.GeometricTolerance.Value, obj.TopologyResolution,
            tuple(getattr(obj, name) for name, *_ in BUILD_LIMITS), bool(obj.FollowSourcePlacement))


class PreparedSolidBatch:
    """Task interface matches SolidBatch; source work never invokes document recompute."""
    def __init__(self, sources, targets, transaction):
        self.sources, self.targets = list(dict.fromkeys(sources)), list(dict.fromkeys(targets))
        owners = self.sources + self.targets
        if not owners:
            raise ValueError("A prepared preview requires source or solid owners")
        self.document, self.document_name = owners[0].Document, owners[0].Document.Name
        self.transaction, self.token = transaction, object()
        self.state, self.phase, self.error = "pending", "queued", ""
        self.inner, self.waiters, self.snapshots = None, [], []
        self.source_stage = False
        self._transaction()
        # A GUI task supersedes ordinary background work. Preflight the whole
        # group before cancelling any request; never steal another task's token.
        for obj, expected in ([(item, MixedBoundary) for item in self.sources]
                              + [(item, NativeSolid) for item in self.targets]):
            proxy = getattr(obj, "Proxy", None)
            if (obj.Document != self.document or not isinstance(proxy, expected)
                    or proxy._restore_failed
                    or (proxy._pending_job is not None and proxy._recompute_request is None)):
                raise ValueError("Task preview requires available same-document owners")
        for obj in owners:
            if obj.Proxy._recompute_request is not None:
                if isinstance(obj.Proxy, MixedBoundary):
                    from ImplicitMixedRecompute import scheduler
                else:
                    from ImplicitSolidRecompute import scheduler
                scheduler().cancel(obj)
        pending_sources = []
        for source in self.sources:
            proxy = getattr(source, "Proxy", None)
            if (source.Document != self.document or not isinstance(proxy, MixedBoundary)
                    or proxy._restore_failed or proxy._pending_job is not None):
                raise ValueError("Source preview requires available same-document owners")
            if source.Geometry is not None and source.InputFingerprint == proxy._fingerprint(source):
                proxy.execute(source)  # Inspect cached topology, without recertification.
            else:
                pending_sources.append(source)
        for obj in self.targets:
            proxy = getattr(obj, "Proxy", None)
            if (obj.Document != self.document or not isinstance(proxy, NativeSolid)
                    or proxy._restore_failed or proxy._pending_job is not None):
                raise ValueError("Solid preview requires available same-document owners")
            self.snapshots.append((obj, proxy, target_settings(obj)))
        try:
            if pending_sources:
                for obj in self.targets:
                    self.waiters.append(obj)
                    obj.Proxy._pending_job = self.token
                    obj.Geometry = None
                    obj.InputFingerprint = ""
                    obj.BackendStatus = "Pending task source preparation"
                self.inner = SourceBatch(pending_sources, transaction)
                self.source_stage = True
                self.phase = "source queued"
            else:
                self._start_solids()
        except Exception:
            self.cancel()
            raise

    def _transaction(self):
        SolidBatch._transaction(self)

    def _check_targets(self):
        self._transaction()
        for obj, proxy, settings in self.snapshots:
            if (not obj.isValid() or obj.Proxy is not proxy or target_settings(obj) != settings
                    or (obj in self.waiters and proxy._pending_job is not self.token)):
                raise ValueError("Solid preview inputs changed; Apply again")

    @property
    def job(self):
        return self.inner.job if self.inner is not None else None

    def _release_waiters(self):
        for obj in self.waiters:
            if obj.Proxy._pending_job is self.token:
                obj.Proxy._pending_job = None
        self.waiters.clear()

    def _start_solids(self):
        self._check_targets()
        self._release_waiters()
        pending = []
        for obj in self.targets:
            if obj.Geometry is not None and obj.InputFingerprint == obj.Proxy._inputs(obj)[2]:
                obj.Proxy.execute(obj)
            else:
                pending.append(obj)
        self.source_stage = False
        self.inner = SolidBatch(pending, self.transaction, defer_start=True) if pending else None
        self.phase = "solid queued"
        if self.inner is None:
            self.state = "ready"

    def cancel(self):
        if self.inner is not None:
            self.inner.cancel()
        active = App.getActiveTransaction()
        owned = active and active[1] == self.transaction
        for obj in self.waiters:
            try:
                if obj.Proxy._pending_job is self.token:
                    obj.Proxy._pending_job = None
                    if owned:
                        obj.Geometry = None
                        obj.InputFingerprint = ""
                        obj.BackendStatus = "Native task preview cancelled or failed"
            except (RuntimeError, ReferenceError):
                pass
        self.waiters.clear()
        if self.state == "pending":
            self.state = "cancelled"

    def step(self):
        if self.state != "pending":
            return self.state
        try:
            self._check_targets()
            state = self.inner.step()
            self.phase = ("source " if self.source_stage else "solid ") + self.inner.phase
            if state == "pending":
                return self.state
            if state != "ready":
                raise RuntimeError(self.inner.error or state)
            if self.source_stage:
                self._start_solids()
            else:
                self.state = "ready"
        except Exception as error:
            self.error = str(error)
            self.cancel()
            self.state = "failed"
        return self.state
