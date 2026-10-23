# SPDX-License-Identifier: LGPL-2.1-or-later
"""GUI-thread scheduling for private native display work; latest request wins."""
import weakref
import FreeCAD as App
import ImplicitOCCT as native


class Request:
    def __init__(self, view, key, boundary, generation):
        self.view = weakref.ref(view)
        self.obj = view._view.Object
        self.document = self.obj.Document
        self.document_name = self.document.Name
        self.key = key
        self.generation = generation
        self.boundary = boundary
        self.record = native.dumps_mixed(boundary)
        self.settings = (key[1], key[2], 200000, 400000, True, 14,
                         2000000, 1000000, 2000000, 50000000)
        self.job = None


class Scheduler:
    def __init__(self):
        from PySide import QtCore
        import FreeCADGui as Gui
        self.requests = {}
        self.generation = 0
        self.timer = QtCore.QTimer(Gui.getMainWindow())
        self.timer.setInterval(50)
        self.timer.timeout.connect(self.poll)
        App.addDocumentObserver(self)

    def cancel(self, view):
        request = self.requests.pop(id(view), None)
        if request is not None and request.job is not None:
            native.cancel_native_job(request.job)
        view._display_pending = False
        self.generation += 1
        view._display_generation = self.generation

    def submit(self, view, key, boundary):
        old = self.requests.get(id(view))
        if (old is not None and old.view() is view and old.key == key
                and old.generation == view._display_generation and old.obj == view._view.Object):
            return
        self.cancel(view)
        request = Request(view, key, boundary, view._display_generation)
        self.requests[id(view)] = request
        view._display_pending = True
        self.timer.start()

    def _drop(self, identity, request):
        if self.requests.get(identity) is not request:
            return
        self.requests.pop(identity)
        if request.job is not None:
            native.cancel_native_job(request.job)
        view = request.view()
        if view is not None:
            view._display_pending = False

    def slotDeletedDocument(self, doc):
        for identity, request in list(self.requests.items()):
            if request.document == doc:
                self._drop(identity, request)

    def slotDeletedObject(self, obj):
        for identity, request in list(self.requests.items()):
            if request.obj == obj:
                self._drop(identity, request)

    def poll(self):
        solid_pending = self._solid_work_pending()
        for identity, request in list(self.requests.items()):
            view = request.view()
            try:
                if (view is None or App.getDocument(request.document_name) != request.document
                        or not request.obj.isValid()
                        or not view._checked_job_current(request.generation, request.key)):
                    self._drop(identity, request)
                    continue
                # A stored solid can remain unchanged while upstream input
                # properties are dirty. Do not stamp those inputs as checked.
                source = request.obj.Source
                if (source is None or any("Touched" in leaf.State or not leaf.isValid()
                        for leaf in [source] + source.OutListRecursive)):
                    raise ValueError("Native solid inputs changed; recompute before checking display")
                from ImplicitMixed import MixedBoundary
                recipe = getattr(source, "Proxy", None)
                if isinstance(recipe, MixedBoundary) and recipe._fingerprint(source) != source.InputFingerprint:
                    raise ValueError("Native boundary recipe changed; recompute before checking display")
                if solid_pending:
                    if request.job is not None:
                        native.cancel_native_job(request.job)
                        request.job = None
                    view._view.SurfacePreviewStatus = "Checking display: waiting for solid preview"
                    continue
                if request.job is None:
                    # Keep a native queue slot available for interactive solid
                    # construction; the remaining views wait here as descriptors.
                    if any(other.job is not None for other in self.requests.values()):
                        continue
                    try:
                        request.job = native.start_surface_job(request.boundary, *request.settings)
                    except RuntimeError as error:
                        if "queue is full" in str(error):
                            continue  # Shared solid work has priority; retry this latest request.
                        raise
                status = native.native_job_status(request.job)
                if status["state"] in ("queued", "running", "cancelling"):
                    view._view.SurfacePreviewStatus = "Checking display: " + status["phase"].replace("_", " ")
                    continue
                if status["state"] != "ready":
                    raise RuntimeError(status["error"] or status["state"])
                result = native.take_surface_job(request.job)
                if (result["input_record"] != request.record
                        or result["input_settings"] != request.settings):
                    raise ValueError("Display result disagrees with its requested source/settings")
                # Verify the actual live solid input descriptor again before
                # publishing, not merely the snapshot recorded by the worker.
                proxy = request.obj.Proxy
                if proxy._inputs(request.obj)[2] != request.obj.InputFingerprint:
                    raise ValueError("Native solid settings or source changed; recompute before checking display")
                if not view._checked_job_current(request.generation, request.key):
                    self._drop(identity, request)
                    continue
                self._drop(identity, request)
                view._checked_job_ready(request.generation, request.key, result["surface"])
            except Exception as error:
                self._drop(identity, request)
                if view is not None and view._checked_job_current(request.generation, request.key):
                    view._checked_job_error(str(error))
        if not self.requests:
            self.timer.stop()

    @staticmethod
    def _solid_work_pending():
        for doc in App.listDocuments().values():
            try:
                if any(getattr(getattr(obj, "Proxy", None), "_pending_job", None) is not None
                       for obj in doc.Objects):
                    return True
            except (RuntimeError, ReferenceError):
                continue  # A document may be closing during a signal callback.
        return False


_scheduler = None


def scheduler():
    global _scheduler
    if _scheduler is None:
        _scheduler = Scheduler()
    return _scheduler


def cancel(view):
    if _scheduler is not None:
        _scheduler.cancel(view)
