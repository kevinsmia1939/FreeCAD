# SPDX-License-Identifier: LGPL-2.1-or-later
"""Open local B-spline faces, conventional clipping and STEP face round-trip."""
import os
import tempfile
import FreeCAD as App
import Part
import Implicit
import ImplicitPatch

doc = App.newDocument("PatchSmoke")
try:
    field = doc.addObject("Implicit::Feature", "Sphere")
    field.Function = "Sphere"
    field.Radius = 2
    field.DomainMin, field.DomainMax = (-3, -3, -3), (3, 3, 3)
    doc.recompute()
    before = len(doc.Objects)
    result = ImplicitPatch.fit_patch(field, (0, 0, 2), 1.2, 1.2, 0.75)
    face, report = result["face"], result["report"]
    assert len(doc.Objects) == before  # Query-only; no hidden document mutations.
    assert face.isValid() and face.ShapeType == "Face" and not face.Solids
    assert isinstance(face.Surface, Part.BSplineSurface)
    assert report["max_sampled_field_residual"] < 1e-5, report
    assert report["max_sampled_normal_angle_degrees"] < 2, report
    assert not report["manufacturing_solid"] and not report["surface_coverage_verified"]
    clipped = face.common(Part.makeBox(2, 4, 4, App.Vector(0, -2, 0)))
    assert clipped.isValid() and len(clipped.Faces) == 1 and not clipped.Solids
    with tempfile.TemporaryDirectory(prefix="implicit-patch-") as directory:
        path = os.path.join(directory, "local_patch.step")
        face.exportStep(path)
        restored = Part.Shape()
        restored.read(path)
        assert restored.isValid() and len(restored.Faces) == 1 and not restored.Solids
        assert isinstance(restored.Faces[0].Surface, Part.BSplineSurface)
        assert abs(restored.Area - face.Area) < 1e-7
    try:
        ImplicitPatch.fit_patch(field, (0, 0, 2), 1.2, 1.2, 0.75, field_tolerance=1e-16)
    except ValueError:
        pass
    else:
        raise AssertionError("unmet fitting tolerance was accepted")
    field.Function = "Gyroid"
    field.Period = 10
    doc.recompute()
    gyro = ImplicitPatch.fit_patch(field, (0, 0, 0), 1, 1, 0.5)
    assert gyro["face"].isValid() and gyro["report"]["max_sampled_field_residual"] < 1e-5
    token = Implicit.newCancellationToken()
    assert not Implicit.isCancelled(token)
    Implicit.cancel(token)
    assert Implicit.isCancelled(token)
    try:
        ImplicitPatch.fit_patch(field, (0, 0, 0), 1, 1, 0.5, cancellation_token=token)
    except RuntimeError:
        pass
    else:
        raise AssertionError("cancelled fitting was accepted")
    # A source edit during a released-GIL numerical stage invalidates provenance.
    original_batch = Implicit.evaluateBatch

    def edited_batch(feature, points):
        values = original_batch(feature, points)
        feature.IsoValue = 0.1
        doc.recompute()
        return values

    Implicit.evaluateBatch = edited_batch
    try:
        ImplicitPatch.fit_patch(field, (0, 0, 0), 1, 1, 0.5)
    except ValueError:
        pass
    else:
        raise AssertionError("changed source was accepted")
    finally:
        Implicit.evaluateBatch = original_batch
    print("native implicit patch smoke test passed")
finally:
    App.closeDocument(doc.Name)
