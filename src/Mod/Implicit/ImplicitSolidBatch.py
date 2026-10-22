# SPDX-License-Identifier: LGPL-2.1-or-later
"""Main-thread coordinator for transactional native-solid peer previews.

No GUI or document work runs on the native worker. The caller owns the edit
transaction and calls step from its event loop, then commits or rolls back.
"""
import FreeCAD as App
import ImplicitOCCT as native
from ImplicitSolid import NativeSolid
from ImplicitMixed import MixedBoundary


def source_signature(source):
    """Include current live math and dirty leaves, not only stored geometry."""
    if not source.isValid():
        raise ValueError("Invalid native boundary source")
    if any("Touched" in leaf.State or not leaf.isValid() for leaf in source.OutListRecursive):
        raise ValueError("Native boundary inputs changed; recompute before previewing")
    recipe = getattr(source, "Proxy", None)
    return (source, recipe._fingerprint(source) if isinstance(recipe, MixedBoundary) else None)


class SolidBatch:
    def __init__(self, objects, transaction):
        self.objects = list(dict.fromkeys(objects))
        if not self.objects:
            raise ValueError("A native solid batch requires at least one owner")
        self.document = self.objects[0].Document
        self.document_name = self.document.Name
        self.transaction = transaction
        self.token = object()
        self.job = None
        self.results = []
        self.state = "pending"
        self.phase = "queued"
        self.error = ""
        self.inputs = []
        self._transaction()
        # Preflight all owners before acquiring or mutating any of them.
        for obj in self.objects:
            if (obj.Document != self.document or not isinstance(obj.Proxy, NativeSolid)
                    or obj.Proxy._restore_failed or getattr(obj.Proxy, "_pending_job", None) is not None):
                raise ValueError("Native preview requires available, restorable same-document owners")
            self.inputs.append((obj.Proxy._inputs(obj), source_signature(obj.Source)))
        try:
            for obj in self.objects:
                obj.Proxy._pending_job = self.token
                obj.Geometry = None
                obj.InputFingerprint = ""
                obj.BackendStatus = "Pending native solid background preview"
            self._start()
        except Exception:
            self.cancel()
            raise

    def _transaction(self):
        active = App.getActiveTransaction()
        if (App.getDocument(self.document_name) != self.document or not self.transaction
                or not active or active[1] != self.transaction):
            raise RuntimeError("Native preview transaction or document changed")

    def _check(self):
        self._transaction()
        for obj, (inputs, signature) in zip(self.objects, self.inputs):
            if (not obj.isValid() or obj.Document != self.document
                    or obj.Proxy._pending_job is not self.token
                    or obj.Proxy._inputs(obj) != inputs
                    or source_signature(obj.Source) != signature):
                raise ValueError("Native preview inputs changed; cancel or apply again")

    def _start(self):
        index = len(self.results)
        obj = self.objects[index]
        settings = self.inputs[index][0][1]
        self.job = native.start_solid_job(obj.Source.Geometry, *settings)

    def cancel(self):
        if self.job is not None:
            native.cancel_solid_job(self.job)
            self.job = None
        self.results.clear()
        active = App.getActiveTransaction()
        owned = active and active[1] == self.transaction
        for obj in self.objects:
            try:
                proxy = getattr(obj, "Proxy", None)
                if getattr(proxy, "_pending_job", None) is self.token:
                    proxy._pending_job = None
                    if owned:
                        obj.Geometry = None
                        obj.InputFingerprint = ""
                        obj.BackendStatus = "Native solid preview cancelled or failed"
            except (RuntimeError, ReferenceError):
                pass  # Document/object may already have been deleted.
        if self.state == "pending":
            self.state = "cancelled"

    def step(self):
        if self.state != "pending":
            return self.state
        try:
            self._check()
            status = native.solid_job_status(self.job)
            self.phase = "%d/%d: %s" % (len(self.results) + 1, len(self.objects), status["phase"])
            if status["state"] in ("queued", "running", "cancelling"):
                return self.state
            if status["state"] != "ready":
                raise RuntimeError(status["error"] or status["state"])
            self.results.append(native.take_solid_job(self.job))
            self.job = None
            if len(self.results) < len(self.objects):
                self._start()
                return self.state
            self._check()
            # Publish only after all peers succeeded and all descriptors match.
            for obj, result in zip(self.objects, self.results):
                obj.Proxy.publish(obj, result)
            self._check()
            for obj in self.objects:
                obj.Proxy._pending_job = None
            self.results.clear()
            self.state = "ready"
        except Exception as error:
            self.error = str(error)
            self.cancel()
            self.state = "failed"
        return self.state
