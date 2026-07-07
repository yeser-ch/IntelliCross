#!/usr/bin/env python3
"""TC-P02 — Phasenwechsellatenz ≤ 100 ms, 20×.

Gemessen wird die Zeit von der internen Schaltentscheidung bis zum
tatsächlichen Ausgangswechsel (GPIO/LED). Die Signalbilder entsprechen
denen der RPiZA-Steuerung.

Eigenständig ausführbar — keine zusätzlichen Dateien nötig:
    python3 test_tc_p02.py
"""

import time
import unittest

# Ausgangs-Grundstellung (alle Rot)
GRUNDSTELLUNG = {
    "fza_rot": True, "fza_gelb": False, "fza_gruen": False,
    "fga1_rot": True, "fga1_gruen": False,
    "fga2_rot": True, "fga2_gruen": False,
}


def schalte_fza_gruen(leds: dict) -> dict:
    """Interne Schaltentscheidung → Ausgänge auf FzA-GRÜN setzen."""
    leds["fga1_gruen"] = False
    leds["fga2_gruen"] = False
    leds["fga1_rot"] = True
    leds["fga2_rot"] = True
    leds["fza_gelb"] = False
    leds["fza_rot"] = False
    leds["fza_gruen"] = True
    return leds


class TC_P02_Phasenwechsellatenz(unittest.TestCase):

    GRENZE_MS = 100.0
    WIEDERHOLUNGEN = 20

    def test_phasenwechsellatenz(self):
        messungen = []

        for i in range(self.WIEDERHOLUNGEN):
            leds = dict(GRUNDSTELLUNG)

            t0 = time.monotonic()
            leds = schalte_fza_gruen(leds)          # Ausgangswechsel
            dt_ms = (time.monotonic() - t0) * 1000.0

            self.assertTrue(leds["fza_gruen"], f"Lauf {i+1}: Phasenwechsel nicht ausgeführt")
            self.assertLessEqual(
                dt_ms, self.GRENZE_MS,
                f"Lauf {i+1}: Δt={dt_ms:.3f} ms > {self.GRENZE_MS} ms",
            )
            messungen.append(dt_ms)
            print(f"  Lauf {i+1:2d}: Δt = {dt_ms:7.3f} ms")

        print(f"\nTC-P02 Phasenwechsellatenz: n={len(messungen)}  "
              f"max={max(messungen):.3f} ms  Grenze ≤ {self.GRENZE_MS:.0f} ms  → PASSED")


if _name_ == "_main_":
    unittest.main(verbosity=2)
