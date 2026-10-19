# SPDX-License-Identifier: LGPL-2.1-or-later
"""Restricted native gyroid/Part-box boundaries; not generic Part Boolean solids.

The native geometry property persists math and shared topology. Operand links
remain live; display meshes are transient. Caps/seams are the default preview;
an opt-in trim-conforming surface candidate does not certify coverage or solids.
"""
import FreeCAD as App
import Implicit  # Register native property/owner types before document restoration.
import hashlib
import json


class MixedBoundary:
    def __init__(self, obj):
        self._boundary = self._mesh = self._section = None
        for name, kind, value in (
            ("MixedSchema", "Integer", 2), ("Field", "Link", None),
            ("Box", "Link", None), ("GeometricTolerance", "Length", .1),
            ("MaximumCells", "Integer", 512), ("SeamCount", "Integer", 0),
            ("BoxEdgeRootCount", "Integer", 0),
            ("PlanarCapCount", "Integer", 0), ("SeamGeometricBound", "Float", 0),
            ("SeamBoundVerified", "Bool", False),
            ("BackendStatus", "String", ""), ("NativeRevision", "Integer", 0)):
            obj.addProperty("App::Property" + kind, name, "Native mixed boundary")
            if value is not None:
                setattr(obj, name, value)
        obj.addProperty("App::PropertyEnumeration", "Operation", "Native mixed boundary")
        obj.Operation = ["Common", "BoxMinusField"]
        for name in ("MixedSchema", "SeamCount", "BoxEdgeRootCount", "PlanarCapCount", "SeamGeometricBound", "SeamBoundVerified", "BackendStatus"):
            obj.setEditorMode(name, 1)
        obj.setEditorMode("NativeRevision", 2)
        self._ensure_geometry(obj)
        self._restore_failed = False
        self._restoring = False
        self._publishing = False
        obj.Proxy = self

    @staticmethod
    def _ensure_geometry(obj):
        if "CornerPolicy" not in obj.PropertiesList:
            obj.addProperty("App::PropertyEnumeration", "CornerPolicy", "Native mixed boundary")
            obj.CornerPolicy = ["Reject", "Regularized"]
            obj.CornerPolicy = "Reject"
        if "Geometry" not in obj.PropertiesList:
            obj.addProperty("Implicit::PropertyNativeGeometry", "Geometry", "Native geometry")
        obj.setEditorMode("Geometry", 1)
        if "InputFingerprint" not in obj.PropertiesList:
            obj.addProperty("App::PropertyString", "InputFingerprint", "Native geometry")
        obj.setEditorMode("InputFingerprint", 2)
        if "SeamBoundVerified" not in obj.PropertiesList:
            obj.addProperty("App::PropertyBool", "SeamBoundVerified", "Native geometry")
        obj.setEditorMode("SeamBoundVerified", 1)

    @staticmethod
    def _fingerprint(obj):
        # Supported input geometry, not mutable BRep checked/free flags or mesh
        # caches. Canonicalize signed zero so FCStd reload does not force retracing.
        def xyz(vector):
            return [float(v) if v != 0 else 0.0 for v in vector]
        def vertices(shape):
            return sorted(xyz(v.Point) for v in shape.Vertexes)
        shape = obj.Box.Shape
        descriptor = {
            "schema": 1, "field": obj.Field.Name, "box": obj.Box.Name,
            "period": obj.Field.Period.Value, "iso": obj.Field.IsoValue,
            "minimum": xyz(obj.Field.DomainMin), "maximum": xyz(obj.Field.DomainMax),
            "operation": str(obj.Operation), "tolerance": obj.GeometricTolerance.Value,
            "budget": obj.MaximumCells, "shape_type": shape.ShapeType,
            "vertices": vertices(shape),
            "edges": sorted((type(e.Curve).__name__, vertices(e)) for e in shape.Edges),
            "faces": sorted((type(f.Surface).__name__, xyz(f.normalAt(0, 0)), vertices(f)) for f in shape.Faces),
        }
        # Preserve the legacy Reject fingerprint, so adding this property on
        # restore does not silently retrace unchanged saved native topology.
        if str(getattr(obj, "CornerPolicy", "Reject")) != "Reject":
            descriptor["corner_policy"] = str(obj.CornerPolicy).lower()
        return hashlib.sha256(json.dumps(descriptor, sort_keys=True, allow_nan=False).encode()).hexdigest()

    def _display(self, obj, data):
        meshes = []
        for cap in data["planar_caps"]:
            vertices, triangles = cap.tessellate(obj.GeometricTolerance.Value)
            normal = tuple(cap.normalAt(0, 0))
            meshes.append({"vertices": [tuple(v) for v in vertices],
                           "triangles": triangles, "normals": [normal] * len(vertices)})
        self._mesh = {"faces": meshes}
        self._section = {"curves": [{"points": p} for p in data["seams"]]}
        self._boundary = data
        obj.SeamCount, obj.PlanarCapCount = data["seam_count"], len(data["planar_caps"])
        obj.BoxEdgeRootCount = data["box_edge_root_count"]
        obj.SeamGeometricBound = data["seam_geometric_bound"]
        obj.SeamBoundVerified = data["seam_bound_verified"]
        obj.BackendStatus = ("Native geometry property; default caps/seams preview; "
                             "NOT a validated Part solid; seam bound "
                             + ("verified by tracing" if data["seam_bound_verified"] else "stored, not re-certified"))

    def native_boundary(self):
        """Owned snapshot of the last successful recompute; never a Part solid."""
        if self._boundary is None:
            raise RuntimeError("No successful native mixed-boundary recompute")
        # Copy containers: callers may inspect independent caps, but cannot edit
        # the feature's cached result or its opaque kernel topology.
        data = dict(self._boundary)
        data["planar_caps"] = [cap.copy() for cap in data["planar_caps"]]
        data["cap_sources"] = list(data["cap_sources"])
        data["seams"] = [list(points) for points in data["seams"]]
        for key in ("edge_points",):
            data[key] = [list(points) for points in data[key]]
        for key in ("vertex_points", "edge_vertices", "seam_edges"):
            data[key] = list(data[key])
        return data

    def classify(self, point, distance_tolerance=.1):
        """Query last successful native region snapshot, not the preview mesh.

        Returns inside/outside only with a distance lower bound exceeding the
        requested model-length tolerance. Near-boundary requires a witness;
        otherwise reports unresolved. This is not native-solid validation.
        """
        import ImplicitOCCT as native
        if self._boundary is None:
            raise RuntimeError("No successful native mixed-boundary recompute")
        return native.classify_mixed(self._boundary["boundary_handle"], tuple(point), distance_tolerance)

    def execute(self, obj):
        self._boundary = self._mesh = self._section = None
        obj.SeamCount = obj.PlanarCapCount = 0
        if "BoxEdgeRootCount" not in obj.PropertiesList:
            obj.addProperty("App::PropertyInteger", "BoxEdgeRootCount", "Native mixed boundary")
            obj.setEditorMode("BoxEdgeRootCount", 1)
        obj.BoxEdgeRootCount = 0
        obj.SeamGeometricBound = 0
        if "SeamBoundVerified" in obj.PropertiesList:
            obj.SeamBoundVerified = False
        try:
            import ImplicitOCCT as native
            if getattr(self, "_restore_failed", False):
                raise RuntimeError("Native topology restoration failed; explicit Proxy.rebuild(obj) required")
            if obj.MixedSchema not in (1, 2):
                raise ValueError("Unsupported native mixed-boundary schema")
            self._ensure_geometry(obj)
            obj.MixedSchema = 2
            field, box = obj.Field, obj.Box
            if (field is None or field.TypeId != "Implicit::Feature"
                    or not field.isValid() or str(field.Operation) != "Definition"
                    or str(field.Function) != "Gyroid" or field.FieldGraph
                    or not field.InsideNegative or field.getGlobalPlacement() != App.Placement()):
                raise ValueError("Field must be a valid identity-placed primitive gyroid with F<=0 inside")
            if (box is None or not box.isValid() or not box.isDerivedFrom("Part::Feature")
                    or box.getGlobalPlacement() != box.Placement):
                raise ValueError("Box must link a valid conventional Part solid")
            fingerprint = self._fingerprint(obj)
            if obj.Geometry is not None and obj.InputFingerprint == fingerprint:
                data = native.inspect_mixed(obj.Geometry)
                mode = "common" if str(obj.Operation) == "Common" else "box_minus_field"
                metadata = native.info(data["implicit_face"])
                points = [tuple(v.Point) for v in box.Shape.Vertexes]
                minimum = tuple(min(p[a] for p in points) for a in range(3))
                maximum = tuple(max(p[a] for p in points) for a in range(3))
                if (data["period"] != field.Period.Value or data["isovalue"] != field.IsoValue
                        or data["corner_policy"] != str(obj.CornerPolicy).lower()
                        or data["operation"] != mode or tuple(metadata["minimum"]) != minimum
                        or tuple(metadata["maximum"]) != maximum
                        or metadata["tolerance"] != obj.GeometricTolerance.Value):
                    self._restore_failed = True
                    raise ValueError("Stored native geometry disagrees with unchanged inputs; explicit rebuild required")
            else:
                face = native.gyroid(field.Period, field.IsoValue, tuple(field.DomainMin),
                                     tuple(field.DomainMax), obj.GeometricTolerance.Value)
                mode = "common" if str(obj.Operation) == "Common" else "box_minus_field"
                data = native.mixed_box(face, box.Shape, mode,
                                        obj.GeometricTolerance.Value, obj.MaximumCells,
                                        corner_policy=str(obj.CornerPolicy).lower())
                self._publishing = True
                try:
                    obj.Geometry = data["boundary_handle"]
                    obj.InputFingerprint = fingerprint
                finally:
                    self._publishing = False
            # Only conventional planar caps use Part meshing. The authoritative
            # implicit face is NEVER passed to tessellate/BRepMesh or Part.Shape.
            self._display(obj, data)
        except Exception as error:
            self._boundary = self._mesh = self._section = None
            obj.SeamCount = obj.PlanarCapCount = 0
            obj.BoxEdgeRootCount = 0
            obj.SeamGeometricBound = 0
            obj.SeamBoundVerified = False
            obj.BackendStatus = "Unsupported/failed: " + str(error)
            self._publishing = True
            try:
                if "Geometry" in obj.PropertiesList:
                    obj.Geometry = None
                if "InputFingerprint" in obj.PropertiesList and not getattr(self, "_restore_failed", False):
                    obj.InputFingerprint = ""
            finally:
                self._publishing = False
            raise
        finally:
            obj.NativeRevision += 1

    def onDocumentRestored(self, obj):
        self._boundary = self._mesh = self._section = None
        self._ensure_geometry(obj)  # Migrate old schema-1 recipe owners in place.
        self._restore_failed = False
        self._publishing = False
        try:
            import ImplicitOCCT as native
            if obj.Geometry is not None:
                self._display(obj, native.inspect_mixed(obj.Geometry))
                obj.NativeRevision += 1
            elif obj.InputFingerprint:
                self._restore_failed = True
                obj.BackendStatus = "Native topology restoration failed; explicit rebuild required"
        finally:
            self._restoring = False

    def onChanged(self, obj, prop):
        if (prop == "Geometry" and not getattr(self, "_restoring", False)
                and not getattr(self, "_publishing", False)):
            self._boundary = self._mesh = self._section = None
            for name in ("SeamCount", "PlanarCapCount", "BoxEdgeRootCount", "SeamGeometricBound"):
                if name in obj.PropertiesList:
                    setattr(obj, name, 0)
            if "SeamBoundVerified" in obj.PropertiesList:
                obj.SeamBoundVerified = False
            if "InputFingerprint" in obj.PropertiesList:
                obj.InputFingerprint = ""
            if "NativeRevision" in obj.PropertiesList:
                obj.NativeRevision += 1

    def rebuild(self, obj):
        """Explicit repair/retrace; never silently substitute for failed restore."""
        self._restore_failed = False
        obj.InputFingerprint = ""
        self.execute(obj)

    def mustExecute(self, _obj):
        return self._boundary is None

    def dumps(self):
        return None

    def loads(self, _state):
        self._boundary = self._mesh = self._section = None
        self._restoring = True
        self._publishing = False
        self._restore_failed = False


from ImplicitNative import NativeBoundaryView


class MixedBoundaryView(NativeBoundaryView):
    def attach(self, view):
        from pivy import coin
        self._view = view
        self._task = None
        self._native_geometry = None
        self._surface_key = self._surface_mesh = None
        self._cap_nodes, self._seam_nodes = [], []
        self._edge_nodes, self._extra_edge_nodes, self._vertex_nodes = [], [], []
        super().attach(view)
        # Keep aggregate buffers for diagnostics, but render individual native
        # subelements so a cap pick/highlight never denotes one display triangle.
        self._root.removeChild(self._faces)
        self._seam_coordinates = coin.SoCoordinate3()
        self._seam_lines = coin.SoIndexedLineSet()
        color = coin.SoBaseColor()
        color.rgb = (1, .6, .1)
        separator = coin.SoSeparator()
        style = coin.SoDrawStyle()
        style.lineWidth = 2
        separator.addChild(style)
        for node in (color, self._seam_coordinates, self._seam_lines):
            separator.addChild(node)
        separator.removeChild(self._seam_lines)
        self._seam_root = separator
        self._seam_switch = coin.SoSwitch()
        self._seam_switch.whichChild = coin.SO_SWITCH_ALL
        self._seam_switch.addChild(separator)
        self._root.addChild(self._seam_switch)
        self._surface_coordinates = coin.SoCoordinate3()
        self._surface_normals = coin.SoNormal()
        self._surface_faces = coin.SoIndexedFaceSet()
        binding = coin.SoNormalBinding()
        binding.value = coin.SoNormalBinding.PER_VERTEX_INDEXED
        self._surface_root = coin.SoSeparator()
        for node in (self._surface_coordinates, self._surface_normals, binding, self._surface_faces):
            self._surface_root.addChild(node)
        self._root.addChild(self._surface_root)
        self._edge_root = coin.SoSeparator()
        self._edge_coordinates = coin.SoCoordinate3()
        edge_color = coin.SoBaseColor()
        edge_color.rgb = (.08, .12, .15)
        edge_style = coin.SoDrawStyle()
        edge_style.lineWidth = 2
        for node in (edge_color, edge_style, self._edge_coordinates):
            self._edge_root.addChild(node)
        self._edge_switch = coin.SoSwitch()
        self._edge_switch.whichChild = coin.SO_SWITCH_ALL
        self._edge_switch.addChild(self._edge_root)
        self._root.addChild(self._edge_switch)
        self._vertex_root = coin.SoSeparator()
        self._vertex_coordinates = coin.SoCoordinate3()
        vertex_color = coin.SoBaseColor()
        vertex_color.rgb = (1, .9, .5)
        vertex_style = coin.SoDrawStyle()
        vertex_style.pointSize = 6
        for node in (vertex_color, vertex_style, self._vertex_coordinates):
            self._vertex_root.addChild(node)
        self._vertex_switch = coin.SoSwitch()
        self._vertex_switch.whichChild = coin.SO_SWITCH_ALL
        self._vertex_switch.addChild(self._vertex_root)
        self._root.addChild(self._vertex_switch)
        for name in ("ShowBoundaryEdges", "ShowVertices"):
            if name not in view.PropertiesList:
                view.addProperty("App::PropertyBool", name, "Native topology display")
                setattr(view, name, True)
        for name, kind, value in (("ShowImplicitSurface", "Bool", False),
                                  ("SurfaceTolerance", "Length", .1),
                                  ("SurfaceMaximumCells", "Integer", 256),
                                  ("SurfacePreviewStatus", "String", "Disabled")):
            if name not in view.PropertiesList:
                view.addProperty("App::Property" + kind, name, "Experimental surface preview")
                setattr(view, name, value)
        view.setEditorMode("SurfacePreviewStatus", 1)
        self._topology_visibility(view)
        self.updateData(view.Object, "NativeRevision")

    def _topology_visibility(self, view):
        from pivy import coin
        if all(name in view.PropertiesList for name in ("ShowBoundaryEdges", "ShowVertices")):
            state = coin.SO_SWITCH_ALL if view.ShowBoundaryEdges else coin.SO_SWITCH_NONE
            self._seam_switch.whichChild = state
            self._edge_switch.whichChild = state
            self._vertex_switch.whichChild = coin.SO_SWITCH_ALL if view.ShowVertices else coin.SO_SWITCH_NONE

    def onChanged(self, view, prop):
        super().onChanged(view, prop)
        if prop in ("ShowBoundaryEdges", "ShowVertices") and hasattr(self, "_vertex_root"):
            self._topology_visibility(view)
            import FreeCADGui as Gui
            Gui.Selection.removeSelection(view.Object)
        if (prop in ("ShowImplicitSurface", "SurfaceTolerance", "SurfaceMaximumCells")
                and hasattr(self, "_surface_faces")
                and all(name in view.PropertiesList for name in
                        ("ShowImplicitSurface", "SurfaceTolerance", "SurfaceMaximumCells", "SurfacePreviewStatus"))):
            self.updateData(view.Object, "NativeRevision")

    def _update_surface(self, obj):
        if not hasattr(self, "_surface_faces") or "SurfacePreviewStatus" not in self._view.PropertiesList:
            return None
        view = self._view
        key = (obj.NativeRevision, bool(view.ShowImplicitSurface),
               view.SurfaceTolerance.Value, view.SurfaceMaximumCells)
        if key == self._surface_key:
            return self._surface_mesh
        self._surface_key = key
        self._surface_mesh = None
        self._surface_faces.coordIndex.setNum(0)
        self._surface_coordinates.point.setNum(0)
        self._surface_normals.vector.setNum(0)
        if not view.ShowImplicitSurface:
            view.SurfacePreviewStatus = "Disabled; caps/seams only"
            return None
        if obj.Geometry is None or getattr(obj.Proxy, "_boundary", None) is None:
            view.SurfacePreviewStatus = "No successful native boundary"
            return None
        try:
            import ImplicitOCCT as native
            mesh = native.tessellate_mixed(obj.Geometry, view.SurfaceTolerance.Value,
                                          view.SurfaceMaximumCells)
            vertices, triangles = mesh["vertices"], mesh["implicit_triangles"]
            normals = mesh["implicit_normals"]
            indices = [i for tri in triangles for i in (*tri, -1)]
            self._surface_coordinates.point.setValues(0, len(vertices), vertices)
            self._surface_normals.vector.setValues(0, len(normals), normals)
            self._surface_faces.coordIndex.setValues(0, len(indices), indices)
            self._surface_mesh = mesh
            view.SurfacePreviewStatus = (
                f"Closed candidate; cells {mesh['cells']}; untrimmed-field distance bound "
                f"{mesh['field_distance_bound']:.6g} mm; coverage/embeddedness/solid NOT validated")
        except Exception as error:
            # Numerical preview failure must not invalidate authoritative math;
            # no stale or partially uploaded surface is allowed to survive.
            self._surface_faces.coordIndex.setNum(0)
            self._surface_coordinates.point.setNum(0)
            self._surface_normals.vector.setNum(0)
            view.SurfacePreviewStatus = "Unsupported/failed surface preview: " + str(error)
        return self._surface_mesh

    def doubleClicked(self, view):
        import FreeCADGui as Gui
        if Gui.Control.activeDialog() or App.getActiveTransaction():
            return False
        return Gui.getDocument(view.Object.Document.Name).setEdit(view.Object.Name)

    def setEdit(self, view, mode):
        import FreeCADGui as Gui
        if mode != 0 or self._task is not None or Gui.Control.activeDialog():
            return False
        self._task = MixedBoundaryTaskPanel(view.Object)
        Gui.Control.showDialog(self._task, Gui.getDocument(view.Object.Document.Name))
        return True

    def unsetEdit(self, view, _mode):
        import FreeCADGui as Gui
        task, self._task = self._task, None
        if task is not None and not task.closed:
            task.finish(False, reset_edit=False)
        Gui.Control.closeDialog(Gui.getDocument(view.Object.Document.Name))

    def updateData(self, obj, prop):
        super().updateData(obj, prop)
        if prop != "NativeRevision" or not hasattr(self, "_seam_lines"):
            return
        vertices, indices = [], []
        data = getattr(obj.Proxy, "_section", None)
        for curve in data["curves"] if data else []:
            points = curve["points"]
            indices.extend(range(len(vertices), len(vertices) + len(points)))
            indices.append(-1)
            vertices.extend(points)
        self._seam_lines.coordIndex.setNum(0)
        self._seam_coordinates.point.setNum(0)
        if vertices:
            self._seam_coordinates.point.setValues(0, len(vertices), vertices)
            self._seam_lines.coordIndex.setValues(0, len(indices), indices)
        from pivy import coin
        # Names are snapshot-local indices, not a history mapping across edits.
        # Discard current selections before a new snapshot can reuse an index.
        import FreeCADGui as Gui
        Gui.Selection.removeSelection(obj)
        self._native_geometry = Implicit.nativeGeometry(obj) if obj.Geometry is not None else None
        caps = getattr(obj.Proxy, "_mesh", None)
        cap_data = caps["faces"] if caps else []
        surface = self._update_surface(obj)
        if surface is not None:
            # Render caps from the SAME constrained mesh as the surface, not
            # the older independent chordal tessellation which may skip knots.
            cap_data = []
            boundary = obj.Proxy._boundary
            for index, cap in enumerate(boundary["planar_caps"]):
                triangles = [tuple(t[:3]) for t in surface["cap_triangles"] if t[3] == index]
                ids = sorted({i for t in triangles for i in t})
                local = {node: i for i, node in enumerate(ids)}
                cap_data.append({"vertices": [surface["vertices"][i] for i in ids],
                                 "normals": [tuple(cap.normalAt(0, 0))] * len(ids),
                                 "triangles": [tuple(local[i] for i in t) for t in triangles]})
            points = [p for cap in cap_data for p in cap["vertices"]]
            normals = [n for cap in cap_data for n in cap["normals"]]
            self._coordinates.point.setNum(0)
            self._normals.vector.setNum(0)
            self._coordinates.point.setValues(0, len(points), points)
            self._normals.vector.setValues(0, len(normals), normals)
        seam_data = data["curves"] if data else []
        for nodes, root, count, kind in (
                (self._cap_nodes, self._root, len(cap_data), coin.SoIndexedFaceSet),
                (self._seam_nodes, self._seam_root, len(seam_data), coin.SoIndexedLineSet)):
            while len(nodes) > count:
                root.removeChild(nodes.pop())
            while len(nodes) < count:
                node = kind()
                root.addChild(node)
                nodes.append(node)
        offset = 0
        for node, cap in zip(self._cap_nodes, cap_data):
            indices = [i + offset if i >= 0 else -1
                       for tri in cap["triangles"] for i in (*tri, -1)]
            node.coordIndex.setNum(0)
            node.coordIndex.setValues(0, len(indices), indices)
            offset += len(cap["vertices"])
        offset = 0
        for node, curve in zip(self._seam_nodes, seam_data):
            count = len(curve["points"])
            indices = list(range(offset, offset + count)) + [-1]
            node.coordIndex.setNum(0)
            node.coordIndex.setValues(0, len(indices), indices)
            offset += count
        # Edge/vertex order comes from the stored native topology, not curves
        # welded by coordinate or transient mesh points. Seam nodes are shared
        # aliases of the corresponding EdgeN; they are never drawn twice.
        topology = getattr(obj.Proxy, "_boundary", None) or {}
        edges = topology.get("edge_points", [])
        points = topology.get("vertex_points", [])
        seam_edges = dict(zip(topology.get("seam_edges", []), self._seam_nodes))
        extra_indices = [i for i in range(len(edges)) if i not in seam_edges]
        self._edge_coordinates.point.setNum(0)
        self._vertex_coordinates.point.setNum(0)
        flat = [p for i in extra_indices for p in edges[i]]
        if flat:
            self._edge_coordinates.point.setValues(0, len(flat), flat)
        if points:
            self._vertex_coordinates.point.setValues(0, len(points), points)
        for nodes, root, count, kind in (
                (self._extra_edge_nodes, self._edge_root, len(extra_indices), coin.SoIndexedLineSet),
                (self._vertex_nodes, self._vertex_root, len(points), coin.SoPointSet)):
            while len(nodes) > count:
                root.removeChild(nodes.pop())
            while len(nodes) < count:
                node = kind()
                root.addChild(node)
                nodes.append(node)
        self._edge_nodes = [None] * len(edges)
        for index, node in seam_edges.items():
            self._edge_nodes[index] = node
        offset = 0
        for index, node in zip(extra_indices, self._extra_edge_nodes):
            count = len(edges[index])
            indices = list(range(offset, offset + count)) + [-1]
            node.coordIndex.setNum(0)
            node.coordIndex.setValues(0, len(indices), indices)
            self._edge_nodes[index] = node
            offset += count
        for index, node in enumerate(self._vertex_nodes):
            node.startIndex = index
            node.numPoints = 1

    def getElementPicked(self, picked):
        tail = picked.getPath().getTail()
        if self._surface_mesh is not None and tail == self._surface_faces:
            return "NativeFace1"
        for prefix, nodes in (("Vertex", self._vertex_nodes), ("Cap", self._cap_nodes),
                              ("Seam", self._seam_nodes), ("Edge", self._edge_nodes)):
            for index, node in enumerate(nodes, 1):
                if tail == node:
                    return prefix + str(index)
        return None

    def getDetailPath(self, name, path, append):
        from pivy import coin
        if self._native_geometry is None:
            return False
        name = self._native_geometry.getElementName(name)
        target = None
        if name == "NativeFace1" and self._surface_mesh is not None:
            target = self._surface_faces
        for prefix, nodes in (("Cap", self._cap_nodes), ("Seam", self._seam_nodes),
                              ("Edge", self._edge_nodes), ("Vertex", self._vertex_nodes)):
            if name.startswith(prefix):
                if prefix in ("Seam", "Edge") and not self._view.ShowBoundaryEdges:
                    return False
                if prefix == "Vertex" and not self._view.ShowVertices:
                    return False
                suffix = name[len(prefix):]
                if (0 < len(suffix) <= 10 and suffix.isascii() and suffix.isdecimal()
                        and suffix == str(int(suffix))):
                    index = int(suffix) - 1
                    if 0 <= index < len(nodes):
                        target = nodes[index]
        if target is None:
            return False
        search = coin.SoSearchAction()
        search.setNode(target)
        search.apply(self._view.RootNode)
        found = search.getPath()
        if found is None:
            return False
        # Append the actual shape path, not a face/line detail referring to a
        # triangle or segment of the disposable display mesh.
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


class MixedBoundaryTaskPanel:
    """Transactional editor; meshes remain transient and fields authoritative."""

    def __init__(self, obj):
        from PySide import QtCore, QtWidgets
        self.obj = obj
        self.document_name = obj.Document.Name
        self.transaction = 0
        self.closed = False
        self.form = QtWidgets.QWidget()
        self.form.setObjectName("ImplicitMixedBoundaryEditor")
        self.form.setWindowTitle("Edit native mixed boundary")
        layout = QtWidgets.QFormLayout(self.form)
        for label, source in (("Field", obj.Field), ("Box", obj.Box)):
            text = (source.Label + " (" + source.Name + ")") if source else "Missing input"
            widget = QtWidgets.QLabel(text)
            widget.setTextFormat(QtCore.Qt.PlainText)
            layout.addRow(label, widget)
        self.operation = QtWidgets.QComboBox()
        self.operation.addItems(["Common", "BoxMinusField"])
        self.operation.setCurrentText(str(obj.Operation))
        self.tolerance = QtWidgets.QDoubleSpinBox()
        self.tolerance.setDecimals(6)
        self.tolerance.setRange(.000001, 1000000)
        self.tolerance.setSuffix(" mm")
        self.tolerance.setValue(obj.GeometricTolerance.Value)
        self.cells = QtWidgets.QComboBox()
        budgets = [str(1 << power) for power in range(2, 10)]
        self.cells.addItems(budgets)
        if str(obj.MaximumCells) not in budgets:
            self.cells.addItem(str(obj.MaximumCells))
        self.cells.setCurrentText(str(obj.MaximumCells))
        self.cells.setToolTip("Power-of-two tracing budget, 4 to 512 cells per axis")
        layout.addRow("Operation", self.operation)
        layout.addRow("Seam tolerance", self.tolerance)
        layout.addRow("Maximum tracing cells", self.cells)
        note = QtWidgets.QLabel("Apply previews changes. Cancel restores the previous state. "
            "Tolerance controls seams only; optional surface preview has separate settings. "
            "This is NOT a validated solid or a certified whole-surface mesh.")
        note.setWordWrap(True)
        layout.addRow(note)
        self.status = QtWidgets.QLabel(obj.BackendStatus)
        self.status.setTextFormat(QtCore.Qt.PlainText)
        self.status.setWordWrap(True)
        layout.addRow(self.status)

    def getStandardButtons(self):
        from PySide import QtWidgets
        buttons = QtWidgets.QDialogButtonBox
        return buttons.Ok | buttons.Cancel | buttons.Apply

    def isAllowedAlterDocument(self):
        return False

    def isAllowedAlterView(self):
        return True

    def isAllowedAlterSelection(self):
        return True

    def apply(self):
        if self.closed:
            return False
        try:
            doc = App.getDocument(self.document_name)
            if doc is None or self.obj.Document != doc:
                raise RuntimeError("The edited document is no longer available")
            cells = int(self.cells.currentText())
            if cells < 4 or cells > 512 or cells & (cells - 1):
                raise ValueError("Tracing budget must be a power of two from 4 to 512")
            active = App.getActiveTransaction()
            if self.transaction:
                if not active or active[1] != self.transaction:
                    raise RuntimeError("Edit transaction changed; cancel and reopen the editor")
            elif active:
                raise RuntimeError("Finish the existing transaction before applying native edits")
            else:
                self.transaction = App.setActiveTransaction("Edit native mixed boundary", True)
            self.obj.Operation = self.operation.currentText()
            self.obj.GeometricTolerance = self.tolerance.value()
            self.obj.MaximumCells = cells
            # Catch numerical preview errors here so the task stays usable.
            # execute clears geometry/display on failure. A successful normal
            # recompute reuses the published snapshot and updates dependencies.
            self.obj.Proxy.execute(self.obj)
            doc.recompute()
            if not self.obj.isValid() or self.obj.Geometry is None:
                raise RuntimeError(self.obj.BackendStatus)
            self.status.setText(self.obj.BackendStatus)
            return True
        except Exception as error:
            self.status.setText("Preview failed: " + str(error))
            return False

    def clicked(self, button):
        from PySide import QtWidgets
        if button == QtWidgets.QDialogButtonBox.Apply:
            self.apply()

    def accept(self):
        if not self.apply():
            return False
        return self.finish(True)

    def reject(self):
        return self.finish(False)

    def finish(self, commit, reset_edit=True):
        if self.closed:
            return True
        active = App.getActiveTransaction()
        owned = self.transaction and active and active[1] == self.transaction
        if active and not owned:
            self.status.setText("Finish the existing transaction before closing native edits")
            return False
        self.closed = True
        if owned:
            App.closeActiveTransaction(not commit, self.transaction)
        doc = App.getDocument(self.document_name)
        if doc is not None and owned and not commit:
            doc.recompute()
        if reset_edit and doc is not None:
            import FreeCADGui as Gui
            Gui.getDocument(self.document_name).resetEdit()
        return True


def create(field, box, operation="Common", corner_policy="Reject"):
    import ImplicitOCCT  # noqa: F401; ABI guard before document mutation.
    policy = {"reject": "Reject", "regularized": "Regularized"}.get(str(corner_policy).lower())
    if policy is None:
        raise ValueError("Unknown native corner policy")
    if field.Document != box.Document:
        raise ValueError("Mixed operands must belong to the same document")
    document = field.Document
    document.openTransaction("Create native mixed boundary")
    try:
        obj = document.addObject("Implicit::NativeFeaturePython", "NativeMixedBoundary")
        MixedBoundary(obj)
        obj.Field, obj.Box, obj.Operation = field, box, operation
        obj.CornerPolicy = policy
        obj.Label = "Native " + operation + " (experimental caps/seams)"
        if App.GuiUp:
            MixedBoundaryView(obj.ViewObject)
        document.recompute()
        if not obj.isValid() or obj.Proxy._boundary is None:
            raise RuntimeError(obj.BackendStatus)
        document.commitTransaction()
        return obj
    except BaseException:
        document.abortTransaction()
        raise


def selected(operation="Common"):
    import FreeCADGui as Gui
    objects = Gui.Selection.getSelection()
    fields = [o for o in objects if o.TypeId == "Implicit::Feature"]
    boxes = [o for o in objects if o.isDerivedFrom("Part::Feature")]
    if len(objects) != 2 or len(fields) != 1 or len(boxes) != 1:
        raise ValueError("Select one primitive native gyroid and one conventional Part box")
    return create(fields[0], boxes[0], operation)


def demo(operation="Common", open_contours=False):
    """Supported closed-loop or zero-isovalue edge-crossing live operands."""
    import ImplicitOCCT  # noqa: F401
    document = App.newDocument("NativeMixedDemo")
    field = document.addObject("Implicit::Feature", "Gyroid")
    field.Function, field.Period, field.IsoValue = "Gyroid", 10, 1.45
    field.DomainMin, field.DomainMax = (-5, -5, -5), (6, 6, 6)
    box = document.addObject("Part::Box", "Box")
    box.Length, box.Width, box.Height = 3.24, 3.28, 2.75
    box.Placement.Base = (-.31, -.37, 1.25)
    if open_contours:
        field.IsoValue = 0
        box.Length, box.Width, box.Height = 8, 8, 6.04
        box.Placement.Base = (-3.83, -4.07, -2.67)
    document.recompute()
    result = create(field, box, operation)
    if App.GuiUp:
        field.ViewObject.Visibility = box.ViewObject.Visibility = False
        import FreeCADGui as Gui
        Gui.activeDocument().activeView().viewAxonometric()
        Gui.activeDocument().activeView().fitAll()
    return result
