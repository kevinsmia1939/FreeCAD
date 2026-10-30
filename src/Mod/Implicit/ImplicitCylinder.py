# SPDX-License-Identifier: LGPL-2.1-or-later
"""Opt-in transient cylinder preview; no global surface-distance certificate."""
import hashlib
import FreeCAD as App


class CylinderView:
    def __init__(self, view):
        view.Proxy = self

    def attach(self, view):
        from pivy import coin
        self._view = view
        self._mesh = self._key = None
        self._picked, self._elements = {}, {}
        for kind, name, default in (("App::PropertyInteger", "PreviewResolution", 16),
                                    ("App::PropertyColor", "SurfaceColor", (.65, .8, .9)),
                                    ("App::PropertyString", "PreviewState", "Empty"),
                                    ("App::PropertyBool", "SurfaceDistanceVerified", False)):
            if name not in view.PropertiesList:
                view.addProperty(kind, name, "Cylinder preview")
                setattr(view, name, default)
        for name in ("PreviewState", "SurfaceDistanceVerified"):
            view.setEditorMode(name, 1)
            view.setPropertyStatus(name, "Transient")
        self._root = coin.SoSeparator()
        self._content = coin.SoSeparator()
        self._root.addChild(self._content)
        view.addDisplayMode(self._root, "Cylinder preview")
        self.refresh()

    def refresh(self):
        if not hasattr(self, "_content"):
            return
        view, obj = self._view, self._view.Object
        if not view.Visibility or obj.GeometryState != "Ready":
            self.clear()
            view.PreviewState = "Hidden" if not view.Visibility else obj.GeometryState
            return
        try:
            import Implicit
            import ImplicitOCCT as native
            from pivy import coin
            key = (hashlib.sha256(native.dumps_cylinder_solid(obj.Geometry).encode()).digest(),
                   view.PreviewResolution, tuple(view.SurfaceColor))
            if key == self._key:
                return
            self.clear()
            mesh = Implicit.cylinderPreview(obj, view.PreviewResolution)
            pending, picked, elements = coin.SoSeparator(), {}, {}
            coordinates = coin.SoCoordinate3()
            coordinates.point.setValues(0, len(mesh["points"]), mesh["points"])
            pending.addChild(coordinates)
            normals, binding, material = coin.SoNormal(), coin.SoNormalBinding(), coin.SoMaterial()
            normals.vector.setValues(0, len(mesh["corner_normals"]), mesh["corner_normals"])
            binding.value = coin.SoNormalBinding.PER_VERTEX_INDEXED
            material.diffuseColor = tuple(float(value) for value in view.SurfaceColor[:3])
            hints = coin.SoShapeHints()
            hints.vertexOrdering = coin.SoShapeHints.COUNTERCLOCKWISE
            surface = coin.SoSeparator()
            for node in (normals, binding, material, hints):
                surface.addChild(node)
            for face in (1, 2, 3):
                node, indices, normal_indices = coin.SoIndexedFaceSet(), [], []
                for index, (triangle, native_face) in enumerate(zip(mesh["triangles"], mesh["native_faces"])):
                    if native_face == face:
                        indices.extend((*triangle, -1))
                        normal_indices.extend((3*index, 3*index+1, 3*index+2, -1))
                node.coordIndex.setValues(0, len(indices), indices)
                node.normalIndex.setValues(0, len(normal_indices), normal_indices)
                surface.addChild(node)
                name = "Face" + str(face)
                elements[name] = node
                picked[node.getNodeId()] = name
            pending.addChild(surface)
            edges = coin.SoSeparator()
            color, style = coin.SoBaseColor(), coin.SoDrawStyle()
            color.rgb = (.1, .1, .1)
            style.lineWidth = 2
            edges.addChild(color)
            edges.addChild(style)
            for index, samples in enumerate(mesh["native_edges"], 1):
                node = coin.SoIndexedLineSet()
                node.coordIndex.setValues(0, len(samples)+1, [*samples, -1])
                edges.addChild(node)
                name = "Edge" + str(index)
                elements[name] = node
                picked[node.getNodeId()] = name
            pending.addChild(edges)
            vertices = coin.SoSeparator()
            point_color, point_style = coin.SoBaseColor(), coin.SoDrawStyle()
            point_color.rgb, point_style.pointSize = (.25, .05, .05), 5
            vertices.addChild(point_color)
            vertices.addChild(point_style)
            for index in range(mesh["native_vertex_count"]):
                group, coords, node = coin.SoSeparator(), coin.SoCoordinate3(), coin.SoPointSet()
                coords.point.setValue(*mesh["points"][index])
                node.numPoints = 1
                group.addChild(coords)
                group.addChild(node)
                vertices.addChild(group)
                name = "Vertex" + str(index+1)
                elements[name] = node
                picked[node.getNodeId()] = name
            pending.addChild(vertices)
            self._content.addChild(pending)
            self._mesh, self._key, self._picked, self._elements = mesh, key, picked, elements
            self._surface_material = material
            view.SurfaceDistanceVerified = False
            view.PreviewState = "Preview (surface distance unverified)"
        except Exception as error:
            self.clear()
            view.PreviewState = "Failed: " + str(error)

    def clear(self):
        self._mesh = self._key = None
        self._picked, self._elements = {}, {}
        self._content.removeAllChildren()
        self._view.SurfaceDistanceVerified = False

    def updateData(self, _obj, prop):
        if prop in ("Geometry", "GeometryState"):
            self.refresh()

    def onChanged(self, _view, prop):
        if prop in ("Visibility", "PreviewResolution", "SurfaceColor"):
            self.refresh()

    def getElementPicked(self, picked):
        return self._picked.get(picked.getPath().getTail().getNodeId()) if self._mesh else None

    def getDetailPath(self, name, path, append):
        from pivy import coin
        node = self._elements.get(name)
        if node is None:
            return False
        search = coin.SoSearchAction()
        search.setNode(node)
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

    def getDisplayModes(self, _view):
        return ["Cylinder preview"]

    def getDefaultDisplayMode(self):
        return "Cylinder preview"

    def setDisplayMode(self, mode):
        return mode

    def dumps(self):
        return None

    def loads(self, _state):
        self._mesh = self._key = None
        self._picked, self._elements = {}, {}


def attach_view(obj):
    if not App.GuiUp:
        raise RuntimeError("Cylinder preview requires the FreeCAD GUI")
    if obj.getTypeIdOfProperty("Geometry") != "Implicit::PropertyNativeCylinderGeometry":
        raise TypeError("Expected native cylinder document geometry")
    if not isinstance(obj.ViewObject.Proxy, CylinderView):
        CylinderView(obj.ViewObject)
    return obj.ViewObject.Proxy
