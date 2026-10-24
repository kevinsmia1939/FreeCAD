# SPDX-License-Identifier: LGPL-2.1-or-later
"""Owned-transaction edits of shared primitive gyroid/box inputs, not geometry."""
import math
import FreeCAD as App
from ImplicitMixed import MixedBoundary
from ImplicitOperands import resolve, box_shape


def expressions(obj):
    return {str(path).lstrip("."): str(value) for path, value in obj.ExpressionEngine}


def driven(obj, name):
    return any(path == name or path.startswith(name + ".") for path in expressions(obj))


def sources_for(source, field=None, box=None):
    return [o for o in source.Document.Objects
            if isinstance(getattr(o, "Proxy", None), MixedBoundary)
            and (o == source or (field is not None and o.Field is not None
                                    and o.Field.getLinkedObject(True) == field)
                 or (box is not None and o.Box is not None
                     and o.Box.getLinkedObject(True) == box))]


def invalidate(sources):
    """Discard provisional native results before changing their shared math."""
    from ImplicitSolid import NativeSolid
    if not sources:
        return
    doc = sources[0].Document
    if any(o.Document != doc for source in sources for o in source.InListRecursive):
        raise ValueError("Cross-document shared-input editing is not supported by this task")
    for source in sources:
        source.Geometry = None  # Existing proxy clears caches/fingerprint/selection.
    for result in doc.Objects:
        if isinstance(getattr(result, "Proxy", None), NativeSolid) and result.Source in sources:
            if not result.Proxy._restore_failed:
                result.InputFingerprint = ""
            result.Geometry = None
            result.BackendStatus = "Pending native shared-input preview"


def rebuild(sources):
    """Trap native preview failures before ordinary recompute logs tracebacks."""
    from ImplicitSolid import NativeSolid
    errors = []
    for source in sources:
        try:
            source.Proxy.execute(source, background=False)
        except Exception as error:
            errors.append(source.Name + ": " + str(error))
    for result in sources[0].Document.Objects if sources else []:
        if isinstance(getattr(result, "Proxy", None), NativeSolid) and result.Source in sources:
            try:
                result.Proxy.execute(result, background=False)
            except Exception as error:
                errors.append(result.Name + ": " + str(error))
    if errors:
        raise ValueError("; ".join(errors))


class SourceEdits:
    """Canonical primitive parameters; no GUI, transactions, or mesh authority."""
    names = ("Period", "IsoValue", "Length", "Width", "Height")

    def __init__(self, solid):
        self.solid, self.source = solid, solid.Source
        if self.source is None or not isinstance(getattr(self.source, "Proxy", None), MixedBoundary):
            raise ValueError("Source has no editable live mixed recipe")
        self.field_input, self.box_input = self.source.Field, self.source.Box
        self.field, _ = MixedBoundary._validate_operands(self.source)
        self.box = resolve(self.box_input)[0]
        if (self.source.Document != solid.Document or self.field is None or self.box is None
                or self.field.Document != solid.Document or self.box.Document != solid.Document
                or self.field.TypeId != "Implicit::Feature" or str(self.field.Function) != "Gyroid"
                or str(self.field.Operation) != "Definition" or self.field.FieldGraph
                or not self.field.InsideNegative):
            raise ValueError("Only same-document identity-placed primitive gyroid inputs are editable")
        self.parametric_box = self.box.TypeId == "Part::Box"
        self.remember()

    def bounds(self, values=None):
        if self.parametric_box:
            matrix = resolve(self.box_input)[1]
            if any(
                    getattr(matrix, "A%d%d" % (r, c)) != (1. if r == c else 0.)
                    for r in range(1, 4) for c in range(1, 4)):
                raise ValueError("Box dimension editing requires an exact pure translation")
            low = (matrix.A14, matrix.A24, matrix.A34)
            size = values or self.values()
            return low, tuple(low[a] + size[name] for a, name in enumerate(self.names[2:]))
        points = [tuple(v.Point) for v in box_shape(self.box_input).Vertexes]
        if not points:
            raise ValueError("Missing conventional box geometry")
        return (tuple(min(p[a] for p in points) for a in range(3)),
                tuple(max(p[a] for p in points) for a in range(3)))

    def values(self):
        values = {"Period": self.field.Period.Value, "IsoValue": self.field.IsoValue}
        if self.parametric_box:
            values.update({name: getattr(self.box, name).Value for name in self.names[2:]})
        else:
            low, high = self.bounds()
            values.update({name: high[a] - low[a] for a, name in enumerate(self.names[2:])})
        return values

    def domain_mode(self):
        if driven(self.field, "DomainMin"):
            return None
        engine = expressions(self.field)
        paths = {path: value for path, value in engine.items()
                 if path == "DomainMax" or path.startswith("DomainMax.")}
        if not paths:
            return "direct"
        expected = {"DomainMax." + axis: "DomainMin." + axis + "+" + name + "/1mm"
                    for axis, name in zip("xyz", self.names[2:])}
        if (set(paths) == set(expected) and all(
                "".join(paths[path].split()).lstrip(".") == expected[path] for path in paths)
                and all(name in self.field.PropertiesList
                        and self.field.getTypeIdOfProperty(name) == "App::PropertyLength" and not driven(self.field, name)
                        for name in self.names[2:])):
            return "dimensions"
        return None

    def follows_box(self):
        low, high = self.bounds()
        return (self.domain_mode() is not None and tuple(self.field.DomainMin) == low
                and tuple(self.field.DomainMax) == high
                and (self.domain_mode() != "dimensions" or all(
                    getattr(self.field, name).Value == self.values()[name] for name in self.names[2:])))

    def signature(self):
        return (tuple(self.values().items()), tuple(self.field.DomainMin), tuple(self.field.DomainMax),
                tuple(sorted(expressions(self.field).items())), tuple(sorted(expressions(self.box).items())),
                tuple(self.bounds()), str(self.source.Operation), self.source.GeometricTolerance.Value,
                self.source.MaximumCells, str(self.source.CornerPolicy), MixedBoundary._fingerprint(self.source),
                tuple((name, getattr(self.field, name).Value) for name in self.names[2:]
                      if name in self.field.PropertiesList
                      and self.field.getTypeIdOfProperty(name) == "App::PropertyLength"))

    def remember(self):
        self.observed = self.signature()

    def prepare(self, values, fit_domain):
        if (self.solid.Source != self.source or self.source.Field != self.field_input
                or self.source.Box != self.box_input
                or resolve(self.field_input)[0] is not self.field or resolve(self.box_input)[0] is not self.box
                or self.signature() != self.observed):
            raise ValueError("Source inputs changed externally; cancel and reopen the editor")
        values = {name: float(values[name]) for name in self.names}
        if any(not math.isfinite(v) for v in values.values()) or any(
                values[name] <= 0 for name in self.names if name != "IsoValue"):
            raise ValueError("Period/dimensions must be finite and positive; level must be finite")
        current = self.values()
        for name in self.names:
            target = self.field if name in self.names[:2] else self.box
            if values[name] != current[name] and (driven(target, name)
                    or (name in self.names[2:] and not self.parametric_box)):
                raise ValueError(name + " is expression-driven or not a parametric box dimension")
        mode = self.domain_mode()
        if fit_domain and mode is None:
            raise ValueError("Custom field-domain expressions must be edited at their source")
        low, high = self.bounds(values)
        domain_changed = fit_domain and (tuple(self.field.DomainMin) != low
            or tuple(self.field.DomainMax) != high or (mode == "dimensions" and any(
                getattr(self.field, name).Value != values[name] for name in self.names[2:])))
        changed = values != current or domain_changed
        if changed and any(o.Document != self.solid.Document
                for leaf in (self.field, self.box, self.source) for o in leaf.InListRecursive):
            raise ValueError("Cross-document shared-input editing is not supported by this task")
        return values, fit_domain, mode, low, high, changed

    def apply(self, plan, transaction):
        active = App.getActiveTransaction()
        if not transaction or not active or active[1] != transaction:
            raise RuntimeError("Shared parameter edits require the editor's owned transaction")
        values, fit_domain, mode, low, high, changed = plan
        if not changed:
            return []
        affected = sources_for(self.source, self.field, self.box)
        invalidate(affected)
        current = self.values()
        for name in self.names[:2]:
            if current[name] != values[name]:
                setattr(self.field, name, values[name])
        if self.parametric_box:
            for name in self.names[2:]:
                if getattr(self.box, name).Value != values[name]:
                    setattr(self.box, name, values[name])
            if not self.box.recompute():
                raise ValueError("Conventional box failed to recompute")
            # Single-object recompute evaluates geometry but, unlike document
            # recompute, does not clear its touched flag. Downstream objects
            # remain touched; only this successfully evaluated leaf is clean.
            self.box.purgeTouched()
        if fit_domain:
            self.field.DomainMin = low
            if mode == "dimensions":
                for name in self.names[2:]:
                    setattr(self.field, name, values[name])
            else:
                self.field.DomainMax = high
        if not self.field.recompute():
            raise ValueError("Gyroid field/domain expressions failed to recompute")
        self.field.purgeTouched()
        # Native task preparation requires clean immutable input snapshots.
        # Recompute only alias wrappers, in dependency order, after their shared
        # primitive targets; ordinary source/solid scheduling remains task-owned.
        aliases = {leaf for source in affected for operand in (source.Field, source.Box)
                   for leaf in [operand] + operand.OutListRecursive
                   if leaf.isDerivedFrom("App::Link")}
        for alias in sorted(aliases, key=lambda leaf: len(leaf.OutListRecursive)):
            if not alias.recompute():
                raise ValueError("Operand link failed to recompute")
            alias.purgeTouched()
        return affected
