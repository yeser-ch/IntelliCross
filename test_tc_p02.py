#!/usr/bin/env python3
"""TC-P02 — Phasenwechsellatenz ≤ 100 ms, 20×. Δt Timer → GPIO-Wechsel.
Ausführung: python3 test_tc_p02.py"""

import time
import unittest

import rpiza


class TC_P02_Phasenwechsellatenz(unittest.TestCase):

    GRENZE_MS = 100.0
    WIEDERHOLUNGEN = 20
    SOLL_DAUER = 0.13   # kein Vielfaches des Schleifentakts (0,02 s)

    def test_phasenwechsellatenz(self):
        z = rpiza.RPiZA(mock=True)
        messungen = []
        try:
            for i in range(self.WIEDERHOLUNGEN):
                t0 = time.monotonic()
                ok = z._warte(self.SOLL_DAUER)
                _leds = z.led_zustaende
                ist_dauer = time.monotonic() - t0

                self.assertTrue(ok, f"Lauf {i+1}: Timer vorzeitig abgebrochen")

                dt_ms = (ist_dauer - self.SOLL_DAUER) * 1000.0
                self.assertGreaterEqual(dt_ms, 0.0)
                self.assertLessEqual(
                    dt_ms, self.GRENZE_MS,
                    f"Lauf {i+1}: Δt={dt_ms:.2f} ms > {self.GRENZE_MS} ms",
                )
                messungen.append(dt_ms)
                print(f"  Lauf {i+1:2d}: Δt = {dt_ms:6.2f} ms")
        finally:
            z.aufraeumen()

        print(f"\nTC-P02 Phasenwechsellatenz: n={len(messungen)}  "
              f"max={max(messungen):.2f} ms  Grenze ≤ {self.GRENZE_MS:.0f} ms  → PASSED")


if __name__ == "__main__":
    unittest.main(verbosity=2)
