"""i2: operational systems of record (PMS, channel manager, booking engine, WMS, EHR, ...) are read as a system of record by keyword."""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_round9 import run, sup  # noqa: E402


def ex(*systems, **kw):
    return run(**{"infrastructure.existing_systems": list(systems), **kw})


def integ(out, needle):
    return [s for s in sup(out, "other") if s["choice"].startswith("Integration with existing") and needle in s["choice"]]


class RecordKeywords(unittest.TestCase):
    def test_pms_and_channel_manager_get_integration_components(self):
        out = ex("Opera Cloud PMS (Oracle)", "SiteMinder channel manager")
        self.assertTrue(integ(out, "Opera"))
        self.assertTrue(integ(out, "SiteMinder"))

    def test_warehouse_system_gets_integration(self):
        self.assertTrue(integ(ex("Manhattan WMS"), "Manhattan"))

    def test_clinical_record_system_gets_integration(self):
        self.assertTrue(integ(ex("Epic EHR"), "Epic"))

    def test_booking_engine_gets_integration(self):
        self.assertTrue(integ(ex("Acme booking engine"), "Acme"))

    def test_unrelated_unknown_name_still_not_integrated(self):
        out = ex("Zorblax Gizmo")
        self.assertFalse(integ(out, "Zorblax"))

    def test_word_boundary(self):
        self.assertFalse(integ(ex("Spmsx Tool"), "Spmsx"))


if __name__ == "__main__":
    unittest.main()
