# SPDX-License-Identifier: LGPL-2.1-or-later
"""Live restricted native solids. Math/topology is authoritative; meshes are transient."""
import hashlib
import json
import math

import FreeCAD as App
import Implicit


class NativeSolid:
    def __init__(self, obj):
        for name, kind, value in (
                # Global scope: moving the result into a container must not
                # adopt/move its source and that source's Boolean operands.
                ("SolidSchema", "Integer", 1), ("Source", "LinkGlobal", None),
                ("GeometricTolerance", "Length", .1), ("TopologyResolution", "Integer", 32),
                ("MaximumDepth", "Integer", 16), ("MaximumCells", "Integer", 4000000),
                ("MaximumTests", "Integer", 2000000), ("MaximumSeparatorCells", "Integer", 2000000),
                ("MaximumGeometryCells", "Integer", 2000000),
                ("MaximumSegmentTests", "Integer", 8000000),
                ("FollowSourcePlacement", "Bool", True),
                ("SolidCount", "Integer", 0), ("ShellCount", "Integer", 0),
                ("NativeFaceCount", "Integer", 0), ("SolidValidated", "Bool", False),
                ("BackendStatus", "String", ""), ("InputFingerprint", "String", ""),
                ("NativeRevision", "Integer", 0)):
            obj.addProperty("App::Property" + kind, name, "Native solid")
            if value is not None:
                setattr(obj, name, value)
        for name in ("SolidSchema", "SolidCount", "ShellCount", "NativeFaceCount",
                     "SolidValidated", "BackendStatus", "Geometry"):
            obj.setEditorMode(name, 1)
        for name in ("InputFingerprint", "NativeRevision"):
            obj.setEditorMode(name, 2)
        self.loads(None)
        self._restoring = False
        obj.Proxy = self

    @staticmethod
    def _inputs(obj):
        import ImplicitOCCT as native
        source = obj.Source
        if (source is None or source == obj or not source.isValid()
                or source.isDerivedFrom("App::Link")
                or source.getTypeIdOfProperty("Geometry") != "Implicit::PropertyNativeGeometry"
                or source.Geometry is None):
            raise ValueError("Source must be a valid native mixed-boundary owner, not a Part shape/solid/link")
        if obj.SolidSchema != 1:
            raise ValueError("Unsupported native solid feature schema")
        record = native.dumps_mixed(source.Geometry)
        settings = (obj.GeometricTolerance.Value, obj.TopologyResolution, obj.MaximumDepth,
                    obj.MaximumCells, obj.MaximumTests, obj.MaximumSeparatorCells,
                    obj.MaximumGeometryCells, obj.MaximumSegmentTests)
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
    """
    groups = [[] for _ in domains]
    for tri in mesh["implicit_triangles"]:
        points = [mesh["vertices"][i] for i in tri]
        candidates = []
        for index, (low, high) in enumerate(domains):
            reserve = 64 * math.ulp(max(1., *(abs(v) for v in (*low, *high))))
            if all(low[a] - reserve <= p[a] <= high[a] + reserve for p in points for a in range(3)):
                candidates.append(index)
        if len(candidates) != 1:
            raise ValueError("Display triangle is not contained in one actual native component domain")
        groups[candidates[0]].append(tri)
    if any(not triangles for triangles in groups):
        raise ValueError("Display candidate omits an actual native field component")
    return groups


from ImplicitNative import NativeBoundaryView


class NativeSolidView(NativeBoundaryView):
    def attach(self, view):
        self._ready = False
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
                                  ("SurfacePreviewStatus", "String", "")):
            if name not in view.PropertiesList:
                view.addProperty("App::Property" + kind, name, "Native solid display")
                setattr(view, name, value)
        view.setEditorMode("SurfacePreviewStatus", 1)
        self._ready = True
        self.updateData(view.Object, "NativeRevision")

    def onChanged(self, view, prop):
        super().onChanged(view, prop)
        if getattr(self, "_ready", False) and prop in (
                "ShowImplicitSurface", "ShowBoundaryEdges", "ShowVertices",
                "SurfaceTolerance", "SurfaceMaximumCells"):
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
               bool(view.ShowVertices), view.SurfaceTolerance.Value, view.SurfaceMaximumCells)
        if key == self._key:
            return
        self._key = key
        # Instance selections hold the target's old subelement indices too.
        # Clear only this target and its link instances, not unrelated objects.
        for selected in Gui.Selection.getSelectionEx():
            if selected.Object.getLinkedObject(True) == obj:
                Gui.Selection.removeSelection(selected.Object)
        self._content.removeAllChildren()
        self._elements, self._picked = {}, {}
        self._mesh = None
        if self._preview_key is not None and self._preview_key[0] != proxy._digest:
            self._preview_key = self._preview = None
        self._geometry = Implicit.nativeGeometry(obj) if obj.Geometry is not None else None
        if self._geometry is None or proxy._solid is None:
            self._preview_key = self._preview = None
            view.SurfacePreviewStatus = "No native solid"
            return
        report, source = proxy._solid, proxy._source
        surface = None
        groups = [[] for _ in report["component_domains"]]
        view.SurfacePreviewStatus = "Field display disabled; native caps/edges/vertices only"
        if view.ShowImplicitSurface and report["implicit_face_count"]:
            try:
                import ImplicitOCCT as native
                preview_key = (proxy._digest, view.SurfaceTolerance.Value, view.SurfaceMaximumCells)
                if preview_key != self._preview_key:
                    surface = native.tessellate_mixed(source["boundary_handle"], view.SurfaceTolerance.Value,
                                                     view.SurfaceMaximumCells)
                    groups = component_triangles(surface, report["component_domains"])
                    self._preview_key, self._preview = preview_key, (surface, groups)
                else:
                    surface, groups = self._preview
                self._mesh = surface
                view.SurfacePreviewStatus = "Transient component-assigned candidate; display coverage NOT validated"
            except Exception as error:
                surface = None
                self._preview_key = self._preview = None
                view.SurfacePreviewStatus = "Unsupported/failed field preview: " + str(error)
        elif not report["implicit_face_count"]:
            view.SurfacePreviewStatus = "No implicit faces in actual result"
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


def create(source, tolerance=.1, topology_resolution=32):
    import ImplicitOCCT  # ABI guard before document mutation.
    if App.getActiveTransaction():
        raise RuntimeError("Finish the active transaction before creating a native solid")
    document = source.Document
    document.openTransaction("Create live native implicit solid")
    try:
        obj = document.addObject("Implicit::NativeSolidFeaturePython", "NativeSolid")
        NativeSolid(obj)
        obj.Source = source
        obj.GeometricTolerance = tolerance
        obj.TopologyResolution = topology_resolution
        obj.Label = "Native implicit solid (experimental)"
        document.recompute()
        if not obj.isValid() or obj.Geometry is None:
            raise RuntimeError(obj.BackendStatus)
        if App.GuiUp:
            NativeSolidView(obj.ViewObject)
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
    return create(objects[0])


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
