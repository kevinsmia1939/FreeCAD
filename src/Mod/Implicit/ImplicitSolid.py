# SPDX-License-Identifier: LGPL-2.1-or-later
"""Live restricted native solids. Math/topology is authoritative; meshes are transient."""
import hashlib
import json
import math

import FreeCAD as App
import Implicit


# Property name, task label, minimum, maximum, initial value. Keep creation and
# editing on the same limits; independent geometry depth additionally excludes 0.
BUILD_LIMITS = (
    ("MaximumDepth", "Topology depth", 0, 16, 16),
    ("MaximumGeometryDepth", "Geometry depth (-1 inherits)", -1, 24, -1),
    ("MaximumCells", "Topology cell budget", 1, 10000000, 4000000),
    ("MaximumTests", "Attachment test budget", 1, 10000000, 2000000),
    ("MaximumSeparatorCells", "Separator cell budget", 1, 10000000, 2000000),
    ("MaximumGeometryCells", "Geometry cell budget", 1, 10000000, 2000000),
    ("MaximumSegmentTests", "Geometry segment budget", 1, 50000000, 8000000),
)


def build_limit_controls(layout, values=None):
    from PySide import QtWidgets
    values = values or {}
    controls = {}
    for name, title, low, high, default in BUILD_LIMITS:
        widget = QtWidgets.QSpinBox()
        widget.setRange(low, high)
        widget.setValue(values.get(name, default))
        controls[name] = widget
        layout.addRow(title, widget)
    return controls


class NativeSolid:
    def __init__(self, obj):
        for name, kind, value in (
                # Global scope: moving the result into a container must not
                # adopt/move its source and that source's Boolean operands.
                ("SolidSchema", "Integer", 1), ("Source", "LinkGlobal", None),
                ("GeometricTolerance", "Length", .1), ("TopologyResolution", "Integer", 32),
        ) + tuple((name, "Integer", default) for name, _, _, _, default in BUILD_LIMITS
                  if name != "MaximumGeometryDepth") + (
                ("FollowSourcePlacement", "Bool", True),
                ("SolidCount", "Integer", 0), ("ShellCount", "Integer", 0),
                ("NativeFaceCount", "Integer", 0), ("SolidValidated", "Bool", False),
                ("BackendStatus", "String", ""), ("InputFingerprint", "String", ""),
                ("NativeRevision", "Integer", 0)):
            obj.addProperty("App::Property" + kind, name, "Native solid")
            if value is not None:
                setattr(obj, name, value)
        self._ensure_settings(obj)
        for name in ("SolidSchema", "SolidCount", "ShellCount", "NativeFaceCount",
                     "SolidValidated", "BackendStatus", "Geometry"):
            obj.setEditorMode(name, 1)
        for name in ("InputFingerprint", "NativeRevision"):
            obj.setEditorMode(name, 2)
        self.loads(None)
        self._restoring = False
        obj.Proxy = self

    @staticmethod
    def _ensure_settings(obj):
        if "MaximumGeometryDepth" not in obj.PropertiesList:
            obj.addProperty("App::PropertyInteger", "MaximumGeometryDepth", "Native solid",
                            "Independent cap geometry depth: -1 inherits MaximumDepth; otherwise 1 to 24")
            obj.MaximumGeometryDepth = -1

    @staticmethod
    def _boundary_record(source):
        import ImplicitOCCT as native
        if (source is None or not source.isValid()
                or source.isDerivedFrom("App::Link")
                or "Geometry" not in source.PropertiesList
                or source.getTypeIdOfProperty("Geometry") != "Implicit::PropertyNativeGeometry"
                or source.Geometry is None):
            raise ValueError("Source must be a valid native mixed-boundary owner, not a Part shape/solid/link")
        return native.dumps_mixed(source.Geometry)

    @staticmethod
    def _inputs(obj):
        record = NativeSolid._boundary_record(obj.Source)
        if obj.SolidSchema != 1:
            raise ValueError("Unsupported native solid feature schema")
        NativeSolid._ensure_settings(obj)
        geometry_depth = obj.MaximumGeometryDepth
        if geometry_depth != -1 and not 1 <= geometry_depth <= 24:
            raise ValueError("MaximumGeometryDepth must be -1 (inherit) or 1 to 24")
        settings = (obj.GeometricTolerance.Value, obj.TopologyResolution, obj.MaximumDepth,
                    obj.MaximumCells, obj.MaximumTests, obj.MaximumSeparatorCells,
                    obj.MaximumGeometryCells, obj.MaximumSegmentTests)
        # Keep old schema-1 fingerprints and the original call prefix intact.
        # Only a non-default independent setting extends the descriptor/call.
        if geometry_depth != -1:
            settings += (geometry_depth,)
        descriptor = (hashlib.sha256(record.encode()).hexdigest(), settings)
        fingerprint = hashlib.sha256(json.dumps(descriptor, allow_nan=False).encode()).hexdigest()
        return record, settings, fingerprint

    def _refresh(self, obj):
        import ImplicitOCCT as native
        self._solid = self._source = None
        self._digest = None
        if obj.Geometry is not None:
            self._solid = native.inspect_mixed_solids(obj.Geometry)
            self._source = native.source_mixed_solids(obj.Geometry)
            self._digest = hashlib.sha256(native.dumps_mixed_solids(obj.Geometry).encode()).hexdigest()
        data = self._solid or {}
        obj.SolidCount = data.get("solid_count", 0)
        obj.ShellCount = data.get("shell_count", 0)
        obj.NativeFaceCount = data.get("implicit_face_count", 0)
        obj.SolidValidated = data.get("solid_validated", False)
        obj.BackendStatus = (data.get("reason", "No native solid")
                             + "; restricted implicit-aware result, not an ordinary Part shape")
        obj.NativeRevision += 1

    @staticmethod
    def _placement(obj):
        if obj.FollowSourcePlacement:
            # The stored result remains in source-local coordinates. Remove the
            # output container pose before assigning its local Placement.
            parent = obj.getGlobalPlacement().multiply(obj.Placement.inverse())
            obj.Placement = parent.inverse().multiply(obj.Source.getGlobalPlacement())

    def execute(self, obj):
        import ImplicitOCCT as native
        try:
            if self._restore_failed:
                raise RuntimeError("Native solid restoration failed; explicit Proxy.rebuild(obj) required")
            record, settings, fingerprint = self._inputs(obj)
            if obj.Geometry is not None and obj.InputFingerprint == fingerprint:
                stored = native.source_mixed_solids(obj.Geometry)
                report = native.inspect_mixed_solids(obj.Geometry)
                if (native.dumps_mixed(stored["boundary_handle"]) != record
                        or report["tolerance"] != settings[0]):
                    self._restore_failed = True
                    raise ValueError("Stored solid disagrees with unchanged source/settings; explicit rebuild required")
            else:
                result = native.build_mixed_solids(obj.Source.Geometry, *settings)
                if not result["solid_validated"] or "solid_handle" not in result:
                    raise ValueError("Native solid unresolved: " + result["reason"])
                self._publishing = True
                try:
                    obj.Geometry = result["solid_handle"]
                    obj.InputFingerprint = fingerprint
                finally:
                    self._publishing = False
            self._placement(obj)
            self._refresh(obj)
        except Exception as error:
            self._publishing = True
            try:
                obj.Geometry = None
                if not self._restore_failed:
                    obj.InputFingerprint = ""
            finally:
                self._publishing = False
            self._refresh(obj)
            obj.BackendStatus = "Unsupported/failed: " + str(error)
            raise

    def onDocumentRestored(self, obj):
        self._ensure_settings(obj)
        self._restoring = False
        self._restore_failed = obj.Geometry is None and bool(obj.InputFingerprint)
        self._refresh(obj)
        if self._restore_failed:
            obj.BackendStatus = "Native solid restoration failed; explicit rebuild required"

    def onChanged(self, obj, prop):
        if prop == "Geometry" and not self._restoring and not self._publishing:
            self._refresh(obj)

    def rebuild(self, obj):
        """Explicit NEW checked build, not certification of the loaded topology."""
        self._restore_failed = False
        obj.InputFingerprint = ""
        self.execute(obj)

    def mustExecute(self, _obj):
        return self._solid is None

    def dumps(self):
        return None

    def loads(self, _state):
        self._solid = self._source = self._digest = None
        self._restoring = True
        self._publishing = False
        self._restore_failed = False


def component_triangles(mesh, domains):
    """Assign display triangles only when contained in one actual face domain.

    Saved domains are the exact field-face restrictions. Ambiguity or crossing
    a separator refuses the preview, never creates a guessed NativeFace index.
    This is display assignment, not surface coverage/solid validation.
    Checked binary32 uploads retain canonical pre-upload points for this
    assignment; the displayed displacement must stay within their checked bound.
    """
    groups = [[] for _ in domains]
    assignment = mesh.get("assignment_vertices", mesh["vertices"])
    upload = mesh.get("display_checks", {}).get("upload_coordinate_bound", 0.)
    for tri in mesh["implicit_triangles"]:
        points = [assignment[i] for i in tri]
        candidates = []
        for index, (low, high) in enumerate(domains):
            reserve = 64 * math.ulp(max(1., *(abs(v) for v in (*low, *high))))
            if all(low[a] - reserve <= p[a] <= high[a] + reserve for p in points for a in range(3)):
                candidates.append(index)
        if len(candidates) != 1:
            raise ValueError("Display triangle is not contained in one actual native component domain")
        if any(math.dist(assignment[i], mesh["vertices"][i]) > upload for i in tri):
            raise ValueError("Display upload exceeds its checked displacement bound")
        groups[candidates[0]].append(tri)
    if any(not triangles for triangles in groups):
        raise ValueError("Display candidate omits an actual native field component")
    return groups


from ImplicitNative import NativeBoundaryView


class NativeSolidView(NativeBoundaryView):
    def __init__(self, view, initial_preview=None):
        self._initial_preview = initial_preview
        super().__init__(view)

    def attach(self, view):
        self._ready = False
        self._task = None
        self._view = view
        self._key = None
        self._elements, self._picked = {}, {}
        self._mesh = None
        self._preview_key = self._preview = None
        super().attach(view)
        self._root.removeChild(self._faces)
        from pivy import coin
        self._content = coin.SoSeparator()
        self._root.addChild(self._content)
        for name, kind, value in (("ShowImplicitSurface", "Bool", True),
                                  ("ShowBoundaryEdges", "Bool", True), ("ShowVertices", "Bool", True),
                                  ("SurfaceTolerance", "Length", .1),
                                  ("SurfaceMaximumCells", "Integer", 256),
                                  ("CheckSurfaceDisplay", "Bool", False),
                                  ("DisplayProximityChecked", "Bool", False),
                                  ("SurfacePreviewStatus", "String", "")):
            if name not in view.PropertiesList:
                view.addProperty("App::Property" + kind, name, "Native solid display")
                setattr(view, name, value)
        view.setEditorMode("SurfacePreviewStatus", 1)
        view.setEditorMode("DisplayProximityChecked", 1)
        self._ready = True
        self.updateData(view.Object, "NativeRevision")

    def onChanged(self, view, prop):
        super().onChanged(view, prop)
        if getattr(self, "_ready", False) and prop in (
                "ShowImplicitSurface", "ShowBoundaryEdges", "ShowVertices",
                "SurfaceTolerance", "SurfaceMaximumCells", "CheckSurfaceDisplay"):
            self.updateData(view.Object, "NativeRevision")

    def _face(self, root, name, points, normals, triangles):
        from pivy import coin
        # Preserve source vertex IDs while compacting each face's display buffer;
        # do not duplicate the entire global candidate for every component/cap.
        used = sorted({i for triangle in triangles for i in triangle})
        local = {i: j for j, i in enumerate(used)}
        points, normals = [points[i] for i in used], [normals[i] for i in used]
        triangles = [tuple(local[i] for i in triangle) for triangle in triangles]
        group = coin.SoSeparator()
        coords, normal, binding, node = (coin.SoCoordinate3(), coin.SoNormal(),
                                         coin.SoNormalBinding(), coin.SoIndexedFaceSet())
        binding.value = coin.SoNormalBinding.PER_VERTEX_INDEXED
        if points:
            coords.point.setValues(0, len(points), points)
            normal.vector.setValues(0, len(normals), normals)
        indices = [i for t in triangles for i in (*t, -1)]
        if indices:
            node.coordIndex.setValues(0, len(indices), indices)
        for child in (coords, normal, binding, node):
            group.addChild(child)
        root.addChild(group)
        if triangles:
            self._elements[name] = node
            self._picked[node.getNodeId()] = name
        return node

    def updateData(self, obj, prop):
        if prop != "NativeRevision" or not getattr(self, "_ready", False):
            return
        from pivy import coin
        import FreeCADGui as Gui
        view = self._view
        proxy = obj.Proxy
        key = (proxy._digest, bool(view.ShowImplicitSurface), bool(view.ShowBoundaryEdges),
               bool(view.ShowVertices), view.SurfaceTolerance.Value, view.SurfaceMaximumCells,
               bool(view.CheckSurfaceDisplay))
        if key == self._key:
            return
        self._key = None  # Publish a successful cache key only after scene upload.
        # Instance selections hold the target's old subelement indices too.
        # Clear only this target and its link instances, not unrelated objects.
        for selected in Gui.Selection.getSelectionEx():
            if selected.Object.getLinkedObject(True) == obj:
                Gui.Selection.removeSelection(selected.Object)
        self._content.removeAllChildren()
        self._elements, self._picked = {}, {}
        self._mesh = None
        view.DisplayProximityChecked = False
        if self._preview_key is not None and self._preview_key[0] != proxy._digest:
            self._preview_key = self._preview = None
        self._geometry = Implicit.nativeGeometry(obj) if obj.Geometry is not None else None
        if self._geometry is None or proxy._solid is None:
            self._preview_key = self._preview = None
            view.SurfacePreviewStatus = "No native solid"
            return
        report, source = proxy._solid, proxy._source
        surface = None
        checked_status = None
        preview_failed = False
        groups = [[] for _ in report["component_domains"]]
        view.SurfacePreviewStatus = "Field display disabled; native caps/edges/vertices only"
        if view.ShowImplicitSurface and report["implicit_face_count"]:
            try:
                import ImplicitOCCT as native
                preview_key = (proxy._digest, view.SurfaceTolerance.Value, view.SurfaceMaximumCells,
                               bool(view.CheckSurfaceDisplay))
                if preview_key != self._preview_key:
                    initial = getattr(self, "_initial_preview", None)
                    self._initial_preview = None
                    if initial is not None and preview_key[1:] == (.1, 256, False):
                        surface, error = initial
                        if error or surface is None:
                            raise ValueError(error or "No initial display candidate")
                    else:
                        extract = (native.tessellate_mixed_checked if view.CheckSurfaceDisplay
                                   else native.tessellate_mixed)
                        surface = extract(source["boundary_handle"], view.SurfaceTolerance.Value,
                                          view.SurfaceMaximumCells)
                    groups = component_triangles(surface, report["component_domains"])
                    self._preview_key, self._preview = preview_key, (surface, groups)
                else:
                    surface, groups = self._preview
                self._mesh = surface
                checks = surface.get("display_checks")
                if view.CheckSurfaceDisplay:
                    if not checks or not checks["boundary_proximity_resolved"] or not checks["triangle_contacts_clear"]:
                        raise ValueError("Missing same-buffer display checks")
                    checked_status = (
                        "Local binary32 display: two-way proximity <= %g mm, triangle contacts clear; "
                        "NOT topology/solid validation" % checks["distance_tolerance"])
                    view.SurfacePreviewStatus = "Checked source-local buffers; upload pending"
                else:
                    view.SurfacePreviewStatus = "Transient component-assigned candidate; display coverage NOT validated"
            except Exception as error:
                surface = None
                self._mesh = None
                self._key = None
                preview_failed = True
                checked_status = None
                view.DisplayProximityChecked = False
                self._preview_key = self._preview = None
                view.SurfacePreviewStatus = "Unsupported/failed field preview: " + str(error)
        elif not report["implicit_face_count"]:
            view.SurfacePreviewStatus = "No implicit faces in actual result"
        try:
            self._upload_scene(report, source, surface, groups)
        except Exception as error:
            self._content.removeAllChildren()
            self._elements, self._picked = {}, {}
            self._mesh = None
            self._preview_key = self._preview = None
            view.SurfacePreviewStatus = "Unsupported/failed display upload: " + str(error)
            return
        self._key = None if preview_failed else key
        if checked_status is not None:
            view.DisplayProximityChecked = True
            view.SurfacePreviewStatus = checked_status

    def _upload_scene(self, report, source, surface, groups):
        from pivy import coin
        view = self._view
        solids, shells = [], []
        for index in range(report["solid_count"]):
            node = coin.SoSeparator()
            self._content.addChild(node)
            self._elements["Solid" + str(index + 1)] = node
            solids.append(node)
        for index, region in enumerate(report["shell_regions"]):
            node = coin.SoSeparator()
            solids[region].addChild(node)
            self._elements["Shell" + str(index + 1)] = node
            shells.append(node)
        cap_index = native_index = 0
        for face_index, (component, source_index, shell_index) in enumerate(zip(
                report["face_components"], report["face_sources"], report["face_shells"])):
            if component >= 0:
                native_index += 1
                name = "NativeFace" + str(native_index)
                points = surface["vertices"] if surface else []
                normals = surface["implicit_normals"] if surface else []
                triangles = groups[component] if surface else []
            else:
                cap_index += 1
                name = "Cap" + str(cap_index)
                cap = source["planar_caps"][source_index]
                if surface:
                    points = surface["vertices"]
                    triangles = [tuple(t[:3]) for t in surface["cap_triangles"] if t[3] == source_index]
                else:
                    tolerance = view.SurfaceTolerance.Value
                    if not math.isfinite(tolerance) or tolerance <= 0:
                        tolerance = obj.GeometricTolerance.Value
                    points, triangles = cap.tessellate(tolerance)
                    points = [tuple(p) for p in points]
                normals = [tuple(cap.normalAt(0, 0))] * len(points)
            node = self._face(shells[shell_index], name, points, normals, triangles)
            if name in self._elements:
                self._elements["Face" + str(face_index + 1)] = node
        # Use actual ComplexGeoData topology, not the source graph's edge order.
        for kind, enabled in (("Edge", view.ShowBoundaryEdges), ("Vertex", view.ShowVertices)):
            if not enabled:
                continue
            for index in range(1, self._geometry.countSubElements(kind) + 1):
                points, lines = self._geometry.getLinesFromSubElement(kind, index)
                group, coords = coin.SoSeparator(), coin.SoCoordinate3()
                coords.point.setValues(0, len(points), [tuple(p) for p in points])
                style, color = coin.SoDrawStyle(), coin.SoBaseColor()
                color.rgb = (.08, .12, .15) if kind == "Edge" else (1, .9, .5)
                style.lineWidth, style.pointSize = 2, 6
                if kind == "Edge":
                    node = coin.SoIndexedLineSet()
                    indices = [v for line in lines for v in (*line, -1)]
                    node.coordIndex.setValues(0, len(indices), indices)
                else:
                    node = coin.SoPointSet()
                    node.numPoints = 1
                for child in (color, style, coords, node):
                    group.addChild(child)
                self._content.addChild(group)
                name = kind + str(index)
                self._elements[name] = node
                self._picked[node.getNodeId()] = name
        for index, edge in enumerate(report["seam_edges"], 1):
            node = self._elements.get("Edge" + str(edge + 1))
            if node is not None:
                self._elements["Seam" + str(index)] = node

    def getElementPicked(self, picked):
        return self._picked.get(picked.getPath().getTail().getNodeId())

    def doubleClicked(self, view):
        import FreeCADGui as Gui
        if Gui.Control.activeDialog() or App.getActiveTransaction():
            return False
        return Gui.getDocument(view.Object.Document.Name).setEdit(view.Object.Name)

    def setEdit(self, view, mode):
        import FreeCADGui as Gui
        if mode != 0 or self._task is not None or Gui.Control.activeDialog() or App.getActiveTransaction():
            return False
        self._task = NativeSolidTaskPanel(view.Object)
        Gui.Control.showDialog(self._task, Gui.getDocument(view.Object.Document.Name))
        Gui.Control.showTaskView()
        return True

    def unsetEdit(self, view, _mode):
        import FreeCADGui as Gui
        task, self._task = self._task, None
        if task is not None and not task.closed:
            task.finish(False, reset_edit=False)
        Gui.Control.closeDialog(Gui.getDocument(view.Object.Document.Name))

    def getDetailPath(self, name, path, append):
        if self._geometry is None:
            return False
        from pivy import coin
        name = self._geometry.getElementName(name)
        target = self._elements.get(name)
        if target is None:
            return False
        search = coin.SoSearchAction()
        search.setNode(target)
        search.apply(self._view.RootNode)
        found = search.getPath()
        if found is None:
            return False
        start = 0
        if path.getLength():
            start = found.findNode(path.getTail())
            if start < 0:
                return False
            start += 1
        elif not append:
            return False
        for index in range(start, found.getLength()):
            path.append(found.getNode(index))
        return True


from ImplicitMixed import MixedBoundary, MixedBoundaryTaskPanel


class NativeSolidTaskPanel(MixedBoundaryTaskPanel):
    """Reuse owned transaction/button lifecycle, with solid-specific controls."""
    def __init__(self, obj):
        from PySide import QtCore, QtWidgets
        NativeSolid._ensure_settings(obj)
        self.obj = obj
        self.document_name = obj.Document.Name
        self.transaction = 0
        self.closed = False
        self.source = obj.Source
        self.edit_operation = (self.source is not None and self.source.Document == obj.Document
                               and isinstance(getattr(self.source, "Proxy", None), MixedBoundary))
        # TaskPanel already supplies a scroll area: avoid nested scrolling.
        self.form = QtWidgets.QWidget()
        self.form.setObjectName("ImplicitNativeSolidEditor")
        self.form.setWindowTitle("Edit native implicit solid")
        layout = QtWidgets.QFormLayout(self.form)
        layout.setRowWrapPolicy(QtWidgets.QFormLayout.WrapAllRows)
        label = QtWidgets.QLabel(self.source.Label if self.source else "Missing source")
        label.setTextFormat(QtCore.Qt.PlainText)
        label.setWordWrap(True)
        layout.addRow("Source", label)
        self.operation = QtWidgets.QComboBox()
        self.operation.addItems(["Common", "BoxMinusField"])
        if self.edit_operation:
            self.operation.setCurrentText(str(self.source.Operation))
        else:
            self.operation.clear()
            self.operation.addItem("Stored source (read-only)")
        self.operation.setEnabled(self.edit_operation)
        layout.addRow("Shared source operation", self.operation)
        from ImplicitSourceEdit import SourceEdits, driven
        self.source_edits = None
        self.parameters = {}
        try:
            self.source_edits = SourceEdits(obj)
        except ValueError as error:
            info = QtWidgets.QLabel("Input parameter editing unavailable: " + str(error))
            info.setWordWrap(True)
            layout.addRow(info)
        if self.source_edits is not None:
            current = self.source_edits.values()
            for name in self.source_edits.names:
                widget = QtWidgets.QDoubleSpinBox()
                widget.setDecimals(6)
                widget.setRange(-1000000 if name == "IsoValue" else .000001, 1000000)
                if name != "IsoValue":
                    widget.setSuffix(" mm")
                widget.setValue(current[name])
                widget._initial_numeric, widget._initial_shown = current[name], widget.value()
                target = self.source_edits.field if name in ("Period", "IsoValue") else self.source_edits.box
                widget.setEnabled(not driven(target, name) and (
                    name in ("Period", "IsoValue") or self.source_edits.parametric_box))
                self.parameters[name] = widget
                layout.addRow("Shared input " + name, widget)
            self.fit_domain = QtWidgets.QCheckBox()
            self.fit_domain.setEnabled(self.source_edits.domain_mode() is not None)
            self.fit_domain.setChecked(self.source_edits.follows_box())
            layout.addRow("Fit shared field domain to box", self.fit_domain)
        self.tolerance = QtWidgets.QDoubleSpinBox()
        self.tolerance.setDecimals(6)
        self.tolerance.setRange(.000001, 1000000)
        self.tolerance.setSuffix(" mm")
        self.tolerance.setValue(obj.GeometricTolerance.Value)
        self.tolerance._initial_numeric = obj.GeometricTolerance.Value
        self.tolerance._initial_shown = self.tolerance.value()
        layout.addRow("Solid tolerance", self.tolerance)
        self.resolution = QtWidgets.QComboBox()
        self.resolution.addItems(["4", "8", "16", "32", "64"])
        if str(obj.TopologyResolution) not in [self.resolution.itemText(i)
                                               for i in range(self.resolution.count())]:
            self.resolution.addItem(str(obj.TopologyResolution))
        self.resolution.setCurrentText(str(obj.TopologyResolution))
        layout.addRow("Topology reference resolution", self.resolution)
        self.controls = build_limit_controls(layout, {name: getattr(obj, name) for name, *_ in BUILD_LIMITS})
        self.follow = QtWidgets.QCheckBox()
        self.follow.setChecked(obj.FollowSourcePlacement)
        layout.addRow("Follow source placement", self.follow)
        note = QtWidgets.QLabel(
            "Apply previews one owned transaction; Cancel restores it. Changing the source "
            "operation or input parameters affects all linked native results. Existing custom "
            "expressions are never replaced; cross-document input edits are unsupported. Geometry depth does not relax "
            "the physical tolerance. Display checks are separate and synchronous. "
            "This is a restricted native solid, not a Part shape.")
        note.setWordWrap(True)
        layout.addRow(note)
        self.status = QtWidgets.QLabel(obj.BackendStatus)
        self.status.setTextFormat(QtCore.Qt.PlainText)
        self.status.setWordWrap(True)
        layout.addRow(self.status)

    def apply(self):
        if self.closed:
            return False
        editing_started = False
        try:
            doc = App.getDocument(self.document_name)
            if doc is None or self.obj.Document != doc:
                raise RuntimeError("The edited document is no longer available")
            if self.obj.Source != self.source:
                raise RuntimeError("Source changed; cancel and reopen the editor")
            resolution = int(self.resolution.currentText())
            if resolution < 4 or resolution > 64 or resolution & (resolution - 1):
                raise ValueError("Topology resolution must be a power of two from 4 to 64")
            values = {name: widget.value() for name, widget in self.controls.items()}
            if values["MaximumGeometryDepth"] == 0:
                raise ValueError("Geometry depth must be -1 (inherit) or 1 to 24")
            def number(widget):
                return widget._initial_numeric if widget.value() == widget._initial_shown else widget.value()
            plan = (self.source_edits.prepare({name: number(widget) for name, widget in self.parameters.items()},
                                             self.fit_domain.isChecked()) if self.source_edits else None)
            active = App.getActiveTransaction()
            if self.transaction:
                if not active or active[1] != self.transaction:
                    raise RuntimeError("Edit transaction changed; cancel and reopen the editor")
            elif active:
                raise RuntimeError("Finish the existing transaction before applying native edits")
            else:
                self.transaction = App.setActiveTransaction("Edit native implicit solid", True)
            editing_started = True
            from ImplicitSourceEdit import invalidate, rebuild
            affected = self.source_edits.apply(plan, self.transaction) if plan else []
            if self.edit_operation and str(self.source.Operation) != self.operation.currentText():
                if self.source not in affected:
                    invalidate([self.source])
                    affected.append(self.source)
                self.source.Operation = self.operation.currentText()
            self.obj.GeometricTolerance = number(self.tolerance)
            self.obj.TopologyResolution = resolution
            self.obj.FollowSourcePlacement = self.follow.isChecked()
            for name, value in values.items():
                setattr(self.obj, name, value)
            # Catch failed previews before C++ document recompute logs an error;
            # normal recompute then reuses the checked snapshot/dependency data.
            if self.edit_operation and self.source not in affected:
                affected.append(self.source)
            rebuild(affected)
            if self.source not in affected:
                self.obj.Proxy.execute(self.obj)
            doc.recompute()
            if not self.obj.isValid() or self.obj.Geometry is None:
                raise RuntimeError(self.obj.BackendStatus)
            self.status.setText(self.obj.BackendStatus)
            return True
        except Exception as error:
            self.status.setText("Preview failed: " + str(error))
            return False
        finally:
            if editing_started and self.source_edits is not None:
                self.source_edits.remember()


def create(source, tolerance=.1, topology_resolution=32, maximum_geometry_depth=-1,
           *, build_limits=None, hide_source=False):
    return _create(source, tolerance, topology_resolution, maximum_geometry_depth,
                   build_limits=build_limits, hide_source=hide_source)


def _create(source, tolerance=.1, topology_resolution=32, maximum_geometry_depth=-1,
            *, build_limits=None, hide_source=False, completed=None):
    import ImplicitOCCT  # ABI guard before document mutation.
    if App.getActiveTransaction():
        raise RuntimeError("Finish the active transaction before creating a native solid")
    limits = dict(build_limits or {})
    allowed = {name: (low, high) for name, _, low, high, _ in BUILD_LIMITS
               if name != "MaximumGeometryDepth"}
    for name, value in limits.items():
        if name not in allowed:
            raise ValueError("Unknown native solid build limit: " + str(name))
        low, high = allowed[name]
        if type(value) is not int or not low <= value <= high:
            raise ValueError(name + " must be an integer from %d to %d" % (low, high))
    NativeSolid._boundary_record(source)
    if completed is not None and any(
            "Touched" in item.State or not item.isValid()
            for item in [source] + source.OutListRecursive):
        raise ValueError("Recompute the changed boundary inputs before starting another build")
    document = source.Document
    document.openTransaction("Create live native implicit solid")
    try:
        obj = document.addObject("Implicit::NativeSolidFeaturePython", "NativeSolid")
        NativeSolid(obj)
        obj.Source = source
        obj.GeometricTolerance = tolerance
        obj.TopologyResolution = topology_resolution
        obj.MaximumGeometryDepth = maximum_geometry_depth
        for name, value in limits.items():
            setattr(obj, name, value)
        obj.Label = "Native implicit solid (experimental)"
        if completed is not None:
            record, settings, fingerprint = obj.Proxy._inputs(obj)
            if record != completed["input_record"] or settings != completed["input_settings"]:
                raise ValueError("Source or settings changed during the native solid build")
            handle = completed["solid_handle"]
            report = ImplicitOCCT.inspect_mixed_solids(handle)
            stored = ImplicitOCCT.source_mixed_solids(handle)
            if (not report["solid_validated"] or report["tolerance"] != tolerance
                    or ImplicitOCCT.dumps_mixed(stored["boundary_handle"]) != record):
                raise ValueError("Background result does not match the validated source")
            obj.Geometry = handle
            obj.InputFingerprint = fingerprint
        try:
            obj.Proxy.execute(obj)
        except Exception as error:
            raise RuntimeError(obj.BackendStatus) from error
        document.recompute()
        if not obj.isValid() or obj.Geometry is None:
            raise RuntimeError(obj.BackendStatus)
        if App.GuiUp:
            preview = None if completed is None else (completed["surface"], completed["surface_error"])
            NativeSolidView(obj.ViewObject, preview)
            if hide_source:
                source.ViewObject.Visibility = False
        document.commitTransaction()
        return obj
    except BaseException:
        document.abortTransaction()
        raise


def selected():
    import FreeCADGui as Gui
    objects = Gui.Selection.getSelection()
    if len(objects) != 1:
        raise ValueError("Select one native mixed-boundary object")
    from ImplicitSolidCreate import open_task
    return open_task(objects[0])


def demo():
    import ImplicitMixed
    boundary = ImplicitMixed.demo(open_contours=True)
    obj = create(boundary)
    if App.GuiUp:
        boundary.ViewObject.Visibility = False
        import FreeCADGui as Gui
        Gui.activeDocument().activeView().viewAxonometric()
        Gui.activeDocument().activeView().fitAll()
    return obj
