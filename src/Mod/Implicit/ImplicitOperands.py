# SPDX-License-Identifier: LGPL-2.1-or-later
"""Resolve live native-mixed operands without copying or flattening B-Reps."""
import FreeCAD as App


_observer = None


def parents(obj):
    result = []
    group = obj.getParentGeoFeatureGroup()
    while group is not None and group not in result:
        result.append(group)
        group = group.getParentGeoFeatureGroup()
    return result


class ContainerObserver:
    def slotChangedObject(self, obj, prop):
        if (prop not in ("Placement", "Group")
                or not obj.hasExtension("App::GeoFeatureGroupExtension")
                or getattr(obj.Document, "Restoring", False)):
            return
        for source in obj.Document.Objects:
            if "MixedSchema" not in source.PropertiesList:
                continue
            operands = (source.Field, source.Box)
            if prop == "Group" or any(operand is not None and obj in parents(operand)
                                      for operand in operands):
                # A container's transform is not a normal outgoing dependency
                # of its children. Touch only; never publish geometry or write
                # properties in this callback (including unrelated transactions).
                source.touch()


def watch_containers():
    global _observer
    if _observer is None:
        _observer = ContainerObserver()
        App.addDocumentObserver(_observer)


def resolve(obj):
    if obj is None or not obj.isValid():
        raise ValueError("A valid live operand is required")
    current, seen = obj, set()
    while current is not None:
        if current in seen or current.Document != obj.Document or not current.isValid():
            raise ValueError("Operand links must be valid, acyclic and in one document")
        seen.add(current)
        linked = getattr(current, "LinkedObject", None)
        if isinstance(linked, tuple) and any(linked[1]):
            raise ValueError("Native mixed operands require whole-object links")
        if getattr(current, "ElementCount", 0):
            raise ValueError("Link arrays are not single native mixed operands")
        target = current.getLinkedObject(False)
        if target is current:
            break
        current = target
    target, matrix = obj.getLinkedObject(True, App.Matrix())
    for parent in parents(obj):
        matrix = parent.Placement.toMatrix().multiply(matrix)
    return target, matrix


def primitive_field(obj):
    target, matrix = resolve(obj)
    if (target.TypeId != "Implicit::Feature" or str(target.Operation) != "Definition"
            or str(target.Function) != "Gyroid" or target.FieldGraph or not target.InsideNegative
            or matrix.A != App.Matrix().A):
        raise ValueError("Field must resolve to an identity-placed primitive gyroid with F<=0 inside")
    return target


def box_shape(obj):
    target, matrix = resolve(obj)
    if not target.isDerivedFrom("Part::Feature"):
        raise ValueError("Box must resolve to a conventional Part solid")
    # Preserve original direct-input locations and their exact coordinate bits.
    # The native builder performs the actual axis-aligned box qualification.
    if target is obj and obj.getParentGeoFeatureGroup() is None:
        return obj.Shape
    if any(getattr(matrix, "A%d%d" % (r, c)) != (1. if r == c else 0.)
           for r in range(1, 4) for c in range(1, 4)):
        raise ValueError("Linked/container box operands currently require pure translations")
    import Part
    shape = Part.Shape(target.Shape)
    # The constructor makes a shallow independent TopoShape wrapper. Setting its
    # location does not change the immutable document property or copy geometry.
    shape.Placement = App.Placement(matrix)
    return shape
