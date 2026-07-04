#!/usr/bin/env python3
"""TC-S01 — Fail-Safe ≤ 500 ms. Kill-Signal → alle Rot. Ausführung: python3 test_tc_s01.py"""

import time
import unittest

import rpiza


class TC_S01_FailSafe(unittest.TestCase):

    GRENZE_MS = 500.0
    WIEDERHOLUNGEN = 10

    def test_fail_safe(self):
        messungen = []

        for i in range(self.WIEDERHOLUNGEN):
            z = rpiza.RPiZA(mock=True)
            try:
                z.starte()
                ende = time.monotonic() + 5.0
                while not z.led_zustaende["fza_gruen"]:
                    self.assertLess(time.monotonic(), ende, "FzA-GRÜN nicht erreicht")
                    time.sleep(0.0005)

                t0 = time.monotonic()
                z.fehler_ausloesen("Kill-Signal")
                leds = z.led_zustaende
                dt_ms = (time.monotonic() - t0) * 1000.0

                kein_gruen = not (leds["fza_gruen"] or leds["fga1_gruen"]
                                  or leds["fga2_gruen"])
                alle_rot = leds["fza_rot"] and leds["fga1_rot"] and leds["fga2_rot"]

                self.assertTrue(kein_gruen, f"Lauf {i+1}: Grün leuchtet noch: {leds}")
                self.assertTrue(alle_rot, f"Lauf {i+1}: nicht alle Rot: {leds}")
                self.assertEqual(z.zustand, rpiza.RPiZA.S_FEHLER)
                self.assertLessEqual(
                    dt_ms, self.GRENZE_MS,
                    f"Lauf {i+1}: Δt={dt_ms:.3f} ms > {self.GRENZE_MS} ms",
                )
                messungen.append(dt_ms)
                print(f"  Lauf {i+1:2d}: Δt = {dt_ms:7.3f} ms   (alle Rot, kein Grün)")
            finally:
                z.aufraeumen()

        print(f"\nTC-S01 Fail-Safe: n={len(messungen)}  "
              f"max={max(messungen):.3f} ms  Grenze ≤ {self.GRENZE_MS:.0f} ms  → PASSED")


if __name__ == "__main__":
    unittest.main(verbosity=2)
