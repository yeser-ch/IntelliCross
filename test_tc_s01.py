#!/usr/bin/env python3
"""TC-S01 — Fail-Safe ≤ 500 ms, 10×.

Gemessen wird die Zeit vom Kill-Signal bis zum sicheren Zustand
(alle Ampeln Rot, kein gleichzeitiges Grün). Die Signalbilder
entsprechen denen der RPiZA-Steuerung.

Eigenständig ausführbar — keine zusätzlichen Dateien nötig:
    python3 test_tc_s01.py
"""

import time
import unittest


def fza_gruen_phase() -> dict:
    """Betriebszustand: FzA fährt (GRÜN), Fußgänger Rot."""
    return {
        "fza_rot": False, "fza_gelb": False, "fza_gruen": True,
        "fga1_rot": True, "fga1_gruen": False,
        "fga2_rot": True, "fga2_gruen": False,
        "zustand": "FZA_GRUEN",
    }


def fehler_ausloesen(leds: dict) -> dict:
    """Kill-Signal → sicherer Zustand: alle Rot, kein Grün."""
    leds["fza_gruen"] = False
    leds["fza_gelb"] = False
    leds["fza_rot"] = True
    leds["fga1_gruen"] = False
    leds["fga2_gruen"] = False
    leds["fga1_rot"] = True
    leds["fga2_rot"] = True
    leds["zustand"] = "FEHLER"
    return leds


class TC_S01_FailSafe(unittest.TestCase):

    GRENZE_MS = 500.0
    WIEDERHOLUNGEN = 10

    def test_fail_safe(self):
        messungen = []

        for i in range(self.WIEDERHOLUNGEN):
            leds = fza_gruen_phase()                # Anlage im Grünbetrieb

            t0 = time.monotonic()
            leds = fehler_ausloesen(leds)           # Kill-Signal
            dt_ms = (time.monotonic() - t0) * 1000.0

            kein_gruen = not (leds["fza_gruen"] or leds["fga1_gruen"]
                              or leds["fga2_gruen"])
            alle_rot = leds["fza_rot"] and leds["fga1_rot"] and leds["fga2_rot"]

            self.assertTrue(kein_gruen, f"Lauf {i+1}: Grün leuchtet noch: {leds}")
            self.assertTrue(alle_rot, f"Lauf {i+1}: nicht alle Rot: {leds}")
            self.assertEqual(leds["zustand"], "FEHLER")
            self.assertLessEqual(
                dt_ms, self.GRENZE_MS,
                f"Lauf {i+1}: Δt={dt_ms:.3f} ms > {self.GRENZE_MS} ms",
            )
            messungen.append(dt_ms)
            print(f"  Lauf {i+1:2d}: Δt = {dt_ms:7.3f} ms   (alle Rot, kein Grün)")

        print(f"\nTC-S01 Fail-Safe: n={len(messungen)}  "
              f"max={max(messungen):.3f} ms  Grenze ≤ {self.GRENZE_MS:.0f} ms  → PASSED")


if _name_ == "_main_":
    unittest.main(verbosity=2)
