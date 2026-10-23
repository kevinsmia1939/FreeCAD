# SPDX-License-Identifier: LGPL-2.1-or-later
"""Opt-in GUI recompute jobs; output publication never joins a foreign edit."""
import FreeCAD as App
import ImplicitOCCT as native
from ImplicitSolidBatch import source_signature


def live_source(source):
    signature = source_signature(source)
    if signature[1] is not None and signature[1] != source.InputFingerprint:
        raise ValueError("Native boundary recipe changed; recompute source before rebuilding")
    return signature


class Request:
    def __init__(self, obj, inputs):
        self.obj, self.proxy = obj, obj.Proxy
        self.document, self.document_name = obj.Document, obj.Document.Name
        self.identity = (self.document_name, obj.Name)
        self.inputs, self.source = inputs, live_source(obj.Source)
        self.boundary = obj.Source.Geometry
        active = App.getActiveTransaction()
        self.transaction = active[1] if active else None
        self.job = None


class Scheduler:
    def __init__(self):
        from PySide import QtCore
        import FreeCADGui as Gui
        self.requests = {}
        self.polling = False
        self.timer = QtCore.QTimer(Gui.getMainWindow())
        self.timer.setInterval(50)
        self.timer.timeout.connect(self.poll)
        App.addDocumentObserver(self)

    def _drop(self, request):
        identity = request.identity
        if self.requests.get(identity) is not request:
            return
        del self.requests[identity]
        if request.job is not None:
            native.cancel_solid_job(request.job)
        if request.proxy._recompute_request is request:
            request.proxy._pending_job = request.proxy._recompute_request = None

    def cancel(self, obj):
        request = self.requests.get((obj.Document.Name, obj.Name))
        if request is not None:
            self._drop(request)

    def submit(self, obj, inputs):
        identity = (obj.Document.Name, obj.Name)
        old = self.requests.get(identity)
        if old is not None and old.proxy is obj.Proxy and old.inputs == inputs:
            return
        request = Request(obj, inputs)
        if old is not None:
            self._drop(old)
        self.requests[identity] = request
        obj.Proxy._pending_job = obj.Proxy._recompute_request = request
        obj.Geometry = None
        obj.InputFingerprint = ""
        obj.BackendStatus = "Pending native solid background recompute"
        self.timer.start()

    def slotDeletedObject(self, obj):
        self.cancel(obj)

    def slotDeletedDocument(self, doc):
        self._cancel_document(doc)

    def _cancel_document(self, doc):
        for request in list(self.requests.values()):
            if request.document == doc:
                self._drop(request)

    def slotUndoDocument(self, doc):
        self._cancel_document(doc)

    def slotRedoDocument(self, doc):
        self._cancel_document(doc)

    def slotAbortTransaction(self, doc):
        self._cancel_document(doc)

    def poll(self):
        if self.polling:
            return
        self.polling = True
        try:
            self._poll()
        finally:
            self.polling = False
            if not self.requests:
                self.timer.stop()

    def _poll(self):
        for request in list(self.requests.values()):
            obj, proxy = request.obj, request.proxy
            try:
                if (App.getDocument(request.document_name) != request.document
                        or not obj.isValid() or obj.Proxy is not proxy
                        or proxy._recompute_request is not request):
                    self._drop(request)
                    continue
                # Do not write even status properties into an unrelated edit.
                active = App.getActiveTransaction()
                if active and active[1] != request.transaction:
                    continue
                if (not obj.BackgroundRecompute or proxy._restore_failed
                        or proxy._inputs(obj) != request.inputs
                        or live_source(obj.Source) != request.source):
                    raise ValueError("Background recompute inputs changed; recompute again")
                if request.job is None:
                    try:
                        request.job = native.start_solid_job(request.boundary, *request.inputs[1])
                    except RuntimeError as error:
                        if "queue is full" in str(error):
                            continue
                        raise
                status = native.solid_job_status(request.job)
                if status["state"] in ("queued", "running", "cancelling"):
                    obj.BackendStatus = "Background recompute: " + status["phase"]
                    continue
                if status["state"] != "ready":
                    raise RuntimeError(status["error"] or status["state"])
                result = native.take_solid_job(request.job)
                proxy.publish(obj, result)
                if (proxy._inputs(obj) != request.inputs
                        or live_source(obj.Source) != request.source):
                    raise ValueError("Inputs changed during background publication")
                self._drop(request)
                # Geometry changes touch consumers; recompute them only after
                # publication, on this document's GUI thread.
                request.document.recompute()
            except Exception as error:
                self._drop(request)
                try:
                    if (obj.isValid() and obj.Proxy is proxy
                            and proxy._recompute_request is None):
                        obj.Geometry = None
                        obj.InputFingerprint = ""
                        obj.BackendStatus = "Unsupported/failed background recompute: " + str(error)
                except (RuntimeError, ReferenceError):
                    pass


_scheduler = None


def scheduler():
    global _scheduler
    if _scheduler is None:
        _scheduler = Scheduler()
    return _scheduler
