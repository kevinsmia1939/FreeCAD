# SPDX-License-Identifier: LGPL-2.1-or-later
"""Restricted native gyroid/Part-box boundaries; not generic Part Boolean solids.

Only operand links, settings and schema persist. Native topology/caps/seams are
reconstructed. Display shows planar caps and seams, NOT a conforming implicit
surface mesh. No mesh-wide accuracy or manufacturing-solid claim is made.
"""
import FreeCAD as App


class MixedBoundary:
    def __init__(self, obj):
        self._boundary = self._mesh = self._section = None
        for name, kind, value in (
            ("MixedSchema", "Integer", 1), ("Field", "Link", None),
            ("Box", "Link", None), ("GeometricTolerance", "Length", .1),
            ("MaximumCells", "Integer", 512), ("SeamCount", "Integer", 0),
            ("BoxEdgeRootCount", "Integer", 0),
            ("PlanarCapCount", "Integer", 0), ("SeamGeometricBound", "Float", 0),
            ("BackendStatus", "String", ""), ("NativeRevision", "Integer", 0)):
            obj.addProperty("App::Property" + kind, name, "Native mixed boundary")
            if value is not None:
                setattr(obj, name, value)
        obj.addProperty("App::PropertyEnumeration", "Operation", "Native mixed boundary")
        obj.Operation = ["Common", "BoxMinusField"]
        for name in ("MixedSchema", "SeamCount", "BoxEdgeRootCount", "PlanarCapCount", "SeamGeometricBound", "BackendStatus"):
            obj.setEditorMode(name, 1)
        obj.setEditorMode("NativeRevision", 2)
        obj.Proxy = self

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
        return data

    def execute(self, obj):
        self._boundary = self._mesh = self._section = None
        obj.SeamCount = obj.PlanarCapCount = 0
        if "BoxEdgeRootCount" not in obj.PropertiesList:
            obj.addProperty("App::PropertyInteger", "BoxEdgeRootCount", "Native mixed boundary")
            obj.setEditorMode("BoxEdgeRootCount", 1)
        obj.BoxEdgeRootCount = 0
        obj.SeamGeometricBound = 0
        try:
            import ImplicitOCCT as native
            if obj.MixedSchema != 1:
                raise ValueError("Unsupported native mixed-boundary schema")
            field, box = obj.Field, obj.Box
            if (field is None or field.TypeId != "Implicit::Feature"
                    or not field.isValid() or str(field.Operation) != "Definition"
                    or str(field.Function) != "Gyroid" or field.FieldGraph
                    or not field.InsideNegative or field.getGlobalPlacement() != App.Placement()):
                raise ValueError("Field must be a valid identity-placed primitive gyroid with F<=0 inside")
            if (box is None or not box.isValid() or not box.isDerivedFrom("Part::Feature")
                    or box.getGlobalPlacement() != box.Placement):
                raise ValueError("Box must link a valid conventional Part solid")
            face = native.gyroid(field.Period, field.IsoValue, tuple(field.DomainMin),
                                 tuple(field.DomainMax), obj.GeometricTolerance.Value)
            mode = "common" if str(obj.Operation) == "Common" else "box_minus_field"
            data = native.mixed_box(face, box.Shape, mode,
                                    obj.GeometricTolerance.Value, obj.MaximumCells)
            # Only conventional planar caps use Part meshing. The authoritative
            # implicit face is NEVER passed to tessellate/BRepMesh or Part.Shape.
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
            obj.BackendStatus = ("Native hybrid boundary; caps/seams preview only; "
                                 "NOT a validated Part solid or conforming surface mesh")
        except Exception as error:
            self._boundary = self._mesh = self._section = None
            obj.SeamCount = obj.PlanarCapCount = 0
            obj.BoxEdgeRootCount = 0
            obj.SeamGeometricBound = 0
            obj.BackendStatus = "Unsupported/failed: " + str(error)
            raise
        finally:
            obj.NativeRevision += 1

    def onDocumentRestored(self, obj):
        # Recompute from links after restore, not during this callback: linked
        # Part objects may not yet have reconstructed their conventional shapes.
        self._boundary = self._mesh = self._section = None

    def mustExecute(self, _obj):
        return self._boundary is None

    def dumps(self):
        return None

    def loads(self, _state):
        self._boundary = self._mesh = self._section = None


from ImplicitNative import NativeBoundaryView


class MixedBoundaryView(NativeBoundaryView):
    def attach(self, view):
        from pivy import coin
        super().attach(view)
        self._seam_coordinates = coin.SoCoordinate3()
        self._seam_lines = coin.SoIndexedLineSet()
        color = coin.SoBaseColor()
        color.rgb = (1, .6, .1)
        separator = coin.SoSeparator()
        for node in (color, self._seam_coordinates, self._seam_lines):
            separator.addChild(node)
        self._root.addChild(separator)
        self.updateData(view.Object, "NativeRevision")

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


def create(field, box, operation="Common"):
    import ImplicitOCCT  # noqa: F401; ABI guard before document mutation.
    if field.Document != box.Document:
        raise ValueError("Mixed operands must belong to the same document")
    document = field.Document
    document.openTransaction("Create native mixed boundary")
    try:
        obj = document.addObject("App::FeaturePython", "NativeMixedBoundary")
        MixedBoundary(obj)
        obj.Field, obj.Box, obj.Operation = field, box, operation
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
