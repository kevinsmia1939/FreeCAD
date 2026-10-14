# SPDX-License-Identifier: LGPL-2.1-or-later
import threading
import time
import traceback
import FreeCAD as App
import Implicit


def cancelled(call):
    try:
        call()
    except RuntimeError as error:
        assert "cancelled" in str(error), error
    else:
        raise AssertionError("cancelled extraction returned geometry")


def main():
    doc = App.newDocument("Cancellation")
    field = doc.addObject("Implicit::Feature", "Gyroid")
    field.Period = 3
    doc.recompute()
    token = Implicit.newCancellationToken()
    Implicit.cancel(token)
    for extractor in (Implicit.tessellate, Implicit.tessellateAdaptive):
        cancelled(lambda: extractor(field, 32, token))
    # A Python thread can signal a running native extractor. It accesses only
    # the atomic token, never a FreeCAD document from the background thread.
    token = Implicit.newCancellationToken()
    def cancel_later():
        time.sleep(0.01)
        Implicit.cancel(token)
    worker = threading.Thread(target=cancel_later)
    worker.start()
    try:
        cancelled(lambda: Implicit.tessellate(field, 64, token))
    finally:
        worker.join()
    # Cancellation does not poison feature geometry or the interpreter lock.
    assert Implicit.tessellate(field, 8, None)["triangles"]
    assert Implicit.evaluateBatch(field, [(0, 0, 0), (1, 2, 3)]) == [
        Implicit.evaluate(field, *point) for point in [(0, 0, 0), (1, 2, 3)]]
    for invalid in (None, 1, "bad"):
        try:
            Implicit.cancel(invalid)
        except (ValueError, TypeError):
            pass
        else:
            raise AssertionError("invalid token accepted")
    App.closeDocument(doc.Name)
    print("native implicit cancellation smoke test passed")


try:
    main()
except BaseException:
    traceback.print_exc()
    raise
