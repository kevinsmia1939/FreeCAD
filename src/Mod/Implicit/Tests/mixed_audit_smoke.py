# SPDX-License-Identifier: LGPL-2.1-or-later
"""Explicit transient triangle-contact audit, never a native solid certificate."""
import traceback
import FreeCAD as App
import ImplicitMixed
import ImplicitOCCT as native


def main():
    for crossing in (False, True):
        obj = ImplicitMixed.demo(open_contours=crossing)
        doc = obj.Document
        for operation in ("Common", "BoxMinusField"):
            obj.Operation = operation
            doc.recompute()
            handle = obj.Geometry
            record = native.dumps_mixed(handle)
            audit = native.audit_mixed_mesh(handle)
            print("native contact audit", crossing, operation, audit)
            assert audit["state"] == "clear" and audit["triangle_contacts_clear"]
            assert audit["first_triangle"] == audit["second_triangle"] == -1
            assert audit["pair_tests"] > 0 and audit["broad_tests"] >= audit["pair_tests"]
            assert not audit["surface_coverage_verified"] and not audit["solid_validated"]
            assert native.dumps_mixed(handle) == record
            limited = native.audit_mixed_mesh(handle, .1, 256, 1, 1)
            assert limited["state"] == "limit" and not limited["triangle_contacts_clear"]
        App.closeDocument(doc.Name)
        assert native.audit_mixed_mesh(handle, .1, 256, 1, 1)["state"] == "limit"
    for args, error in (((None,), TypeError), ((handle, .1, 256, 0), ValueError)):
        try:
            native.audit_mixed_mesh(*args)
        except error:
            pass
        else:
            raise AssertionError("invalid native mesh audit accepted")
    print("native implicit mixed contact audit smoke test passed")


try:
    main()
except Exception:
    traceback.print_exc()
    raise
