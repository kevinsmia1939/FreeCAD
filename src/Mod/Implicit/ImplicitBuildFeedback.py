# SPDX-License-Identifier: LGPL-2.1-or-later
"""Live, transaction-neutral GUI feedback; geometry/proof flags stay authoritative."""
from pathlib import Path
import weakref


def describe(obj):
    proxy = obj.Proxy
    if getattr(proxy, "_pending_job", None) is not None:
        return "Pending", "Native build in progress; output may be unavailable"
    if getattr(proxy, "_restore_failed", False):
        return "Failed", "Stored geometry could not be restored; explicit repair required"
    geometry = obj.Geometry
    status = str(obj.BackendStatus)
    if geometry is None:
        if any(word in status.lower() for word in ("failed", "unsupported", "cancelled", "unavailable")):
            return "Failed", status
        return "Empty", "No geometry or active build; recompute required"
    if any("Touched" in leaf.State or not leaf.isValid() for leaf in [obj] + obj.OutListRecursive):
        return "Changed", "Inputs changed; recompute before using the stored geometry"
    solid = "SolidSchema" in obj.PropertiesList
    checked = bool(obj.SolidValidated if solid else obj.SeamBoundVerified)
    if not checked:
        return "Unverified", "Geometry available; stored verification is not current"
    return ("Ready", "Native solid ready; display checks are separate" if solid else
            "Boundary ready; seam bound verified, solid validation is separate")


class Feedback:
    def __init__(self, proxy):
        obj = proxy._view.Object
        self.document_name, self.object_name = obj.Document.Name, obj.Name
        self.document_identity = id(obj.Document)

    def __str__(self):
        import FreeCAD as App
        try:
            doc = App.listDocuments().get(self.document_name)
            obj = doc.getObject(self.object_name) if doc is not None else None
            if doc is not None and id(doc) == self.document_identity and obj is not None:
                state, text = describe(obj)
                return state + ": " + text
        except (AttributeError, RuntimeError, ReferenceError):
            pass
        return "Unavailable"

    __repr__ = __str__


_icons = {}
_watcher = None


def icon(proxy):
    from PySide import QtCore, QtGui
    try:
        state = describe(proxy._view.Object)[0]
    except (AttributeError, RuntimeError, ReferenceError):
        return None
    if state in _icons:
        return _icons[state]
    base = QtGui.QIcon(str(Path(__file__).parent / "Resources/icons/ImplicitGyroid.svg"))
    pixmap = base.pixmap(32, 32)
    painter = QtGui.QPainter(pixmap)
    painter.setRenderHint(QtGui.QPainter.Antialiasing)
    colors = {"Pending": "#d38a00", "Failed": "#c73535", "Changed": "#d38a00",
              "Empty": "#777777", "Unverified": "#777777", "Ready": "#187da6"}
    painter.setPen(QtGui.QPen(QtGui.QColor("white"), 1))
    painter.setBrush(QtGui.QColor(colors[state]))
    painter.drawEllipse(15, 15, 16, 16)
    painter.setPen(QtGui.QColor("white"))
    font = painter.font()
    font.setBold(True)
    font.setPixelSize(13)
    painter.setFont(font)
    symbols = {"Pending": "…", "Failed": "!", "Changed": "↻", "Empty": "–", "Unverified": "?", "Ready": "✓"}
    painter.drawText(QtCore.QRect(15, 15, 16, 16), QtCore.Qt.AlignCenter, symbols[state])
    painter.end()
    _icons[state] = QtGui.QIcon(pixmap)
    return _icons[state]


class Watcher:
    def __init__(self):
        from PySide import QtCore
        import FreeCADGui as Gui
        self.views = {}
        self.timer = QtCore.QTimer(Gui.getMainWindow())
        self.timer.setInterval(150)
        self.timer.timeout.connect(self.poll)

    def add(self, proxy):
        self.views[id(proxy)] = (weakref.ref(proxy), None)
        self.timer.start()

    def poll(self):
        changed = False
        for identity, (reference, previous) in list(self.views.items()):
            proxy = reference()
            try:
                if proxy is None or proxy._view.Proxy is not proxy:
                    self.views.pop(identity, None)
                    continue
                obj = proxy._view.Object
                if obj.Document is None or obj.Document.getObject(obj.Name) is not obj:
                    self.views.pop(identity, None)
                    continue
                current = str(proxy._view.BuildFeedback)
                if current != previous:
                    self.views[identity] = reference, current
                    proxy._view.signalChangeIcon()
                    changed = True
            except (AttributeError, RuntimeError, ReferenceError):
                self.views.pop(identity, None)
        if changed:
            # Repainting asks the property model for the live Python value;
            # no property setter, recompute or transaction is used here.
            from PySide import QtWidgets
            import FreeCADGui as Gui
            for tree in Gui.getMainWindow().findChildren(QtWidgets.QTreeView):
                tree.viewport().update()
        if not self.views:
            self.timer.stop()


def attach(proxy, view):
    global _watcher
    if "BuildFeedback" not in view.PropertiesList:
        view.addProperty("Implicit::PropertyBuildFeedback", "BuildFeedback", "Native build",
                         "Live build feedback. Ready is separate from display checks; stored topology can be unverified.")
    for status in ("Transient", "NoModify", "Output", "NoRecompute"):
        view.setPropertyStatus("BuildFeedback", status)
    view.setEditorMode("BuildFeedback", 1)
    view.BuildFeedback = Feedback(proxy)
    if _watcher is None:
        _watcher = Watcher()
    _watcher.add(proxy)
