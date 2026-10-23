# SPDX-License-Identifier: LGPL-2.1-or-later
"""Opt-in source tracing on the native worker with GUI-thread publication."""
import FreeCAD as App
import ImplicitOCCT as native
from ImplicitSolidRecompute import Scheduler as SolidScheduler


class Request:
    def __init__(self, obj, fingerprint):
        self.obj, self.proxy = obj, obj.Proxy
        self.document, self.document_name = obj.Document, obj.Document.Name
        self.identity = (self.document_name, obj.Name)
        self.inputs = fingerprint
        field, box = self.proxy._validate_operands(obj)
        self.operands = field, box
        self.face = native.gyroid(field.Period.Value, field.IsoValue, tuple(field.DomainMin),
                                  tuple(field.DomainMax), obj.GeometricTolerance.Value)
        self.field_record, self.box_record = native.dumps(self.face), box.Shape.exportBrepToString()
        self.settings = ("common" if str(obj.Operation) == "Common" else "box_minus_field",
                         obj.GeometricTolerance.Value, obj.MaximumCells, str(obj.CornerPolicy).lower())
        active = App.getActiveTransaction()
        self.transaction = active[1] if active else None
        self.job = None


def same_inputs(request):
    obj, proxy = request.obj, request.proxy
    proxy._validate_operands(obj)
    return (not proxy._restore_failed and request.operands == (obj.Field, obj.Box)
            and proxy._fingerprint(obj) == request.inputs
            and all(leaf.isValid() and "Touched" not in leaf.State for leaf in obj.OutListRecursive))


class Scheduler(SolidScheduler):
    @staticmethod
    def invalidate_consumers(source, status):
        from ImplicitSolid import NativeSolid
        from ImplicitSolidRecompute import scheduler as solid_scheduler
        for obj in source.InList:
            proxy = getattr(obj, "Proxy", None)
            if obj.Document != source.Document or not isinstance(proxy, NativeSolid):
                continue
            if getattr(proxy, "_recompute_request", None) is not None:
                solid_scheduler().cancel(obj)
            # A task-owned batch has its own failure/transaction coordinator.
            if getattr(proxy, "_pending_job", None) is not None:
                continue
            obj.Geometry = None
            obj.InputFingerprint = ""
            obj.BackendStatus = status

    def submit(self, obj, fingerprint):
        identity = (obj.Document.Name, obj.Name)
        old = self.requests.get(identity)
        if (old is not None and old.proxy is obj.Proxy and old.inputs == fingerprint
                and old.operands == (obj.Field, obj.Box)):
            return
        request = Request(obj, fingerprint)
        if old is not None:
            self._drop(old)
        self.requests[identity] = request
        obj.Proxy._pending_job = obj.Proxy._recompute_request = request
        obj.Geometry = None
        obj.InputFingerprint = ""
        obj.BackendStatus = "Pending native boundary preparation"
        self.invalidate_consumers(obj, "Pending native boundary preparation")
        self.timer.start()

    @staticmethod
    def current(request):
        return request.obj.BackgroundRecompute and same_inputs(request)

    def _poll(self):
        for request in list(self.requests.values()):
            obj, proxy = request.obj, request.proxy
            try:
                if (App.getDocument(request.document_name) != request.document
                        or not obj.isValid() or obj.Proxy is not proxy
                        or proxy._recompute_request is not request):
                    self._drop(request)
                    continue
                active = App.getActiveTransaction()
                if active and active[1] != request.transaction:
                    continue
                if not self.current(request):
                    raise ValueError("Native boundary inputs changed; recompute again")
                if request.job is None:
                    try:
                        request.job = native.start_boundary_job_from_record(request.face, request.box_record,
                                                                            *request.settings)
                    except RuntimeError as error:
                        if "queue is full" in str(error):
                            continue
                        raise
                status = native.native_job_status(request.job)
                if status["state"] in ("queued", "running", "cancelling"):
                    obj.BackendStatus = "Background boundary preparation: " + status["phase"]
                    continue
                if status["state"] != "ready":
                    raise RuntimeError(status["error"] or status["state"])
                result = native.take_boundary_job(request.job)
                proxy.publish(obj, result, request.inputs, request.field_record,
                              request.box_record, request.settings)
                if not self.current(request):
                    raise ValueError("Inputs changed during boundary publication")
                self._drop(request)
                request.document.recompute()
            except Exception as error:
                self._drop(request)
                try:
                    if (obj.isValid() and obj.Proxy is proxy
                            and proxy._recompute_request is None):
                        obj.Geometry = None
                        obj.InputFingerprint = ""
                        obj.BackendStatus = "Unsupported/failed background boundary: " + str(error)
                        self.invalidate_consumers(obj, "Source boundary unavailable: " + str(error))
                except (RuntimeError, ReferenceError):
                    pass


_scheduler = None


def scheduler():
    global _scheduler
    if _scheduler is None:
        _scheduler = Scheduler()
    return _scheduler
