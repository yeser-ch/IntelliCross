#!/usr/bin/env python3
"""
RPiZA v3.0 — Raspberry Pi Zuflussregelungsanlage mit Fußgängerübergang

Hardware-Pinbelegung BCM:
FzA  : ROT=5   GELB=6   GRÜN=13
FgA1 : ROT=27  GRÜN=22
FgA2 : ROT=21  GRÜN=16
HC-SR04: TRIG=19  ECHO=23

Echo-Pin benötigt Spannungsteiler 5 V → 3,3 V.
"""

import logging
import threading
import time
import tkinter as tk
from tkinter import ttk


# ============================================================
# Logging
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(threadName)s — %(message)s",
)
log = logging.getLogger("RPiZA")


# ============================================================
# Hardware-Erkennung
# ============================================================

try:
    import RPi.GPIO as _RPIGPIO
    from gpiozero import LED
except (ImportError, RuntimeError) as exc:
    raise SystemExit(
        "Dieses Programm ist für den Raspberry Pi mit GPIO-Hardware gedacht. "
        "Bitte auf dem Raspberry Pi starten und ggf. RPi.GPIO/gpiozero installieren."
    ) from exc

log.info("RPi.GPIO und gpiozero erkannt — Echtbetrieb aktiv.")


# ============================================================
# Pin-Definitionen BCM
# ============================================================

PIN_FZA_ROT = 5
PIN_FZA_GELB = 6
PIN_FZA_GRUEN = 13

PIN_FGA1_ROT = 27
PIN_FGA1_GRUEN = 22

PIN_FGA2_ROT = 21
PIN_FGA2_GRUEN = 16

PIN_TRIG = 19
PIN_ECHO = 23


# ============================================================
# Zeitwerte
# ============================================================

T_GELB = 1.0
T_ROT_GELB = 1.0
T_ZWISCHENZEIT = 4.0
T_RAEUMZEIT = 4.0
T_MIN_GRUEN_FGA = 10.0

FZA_GRUEN_MIN = 120
FZA_GRUEN_MAX = 300

FGA_GRUEN_MIN = 10
FGA_GRUEN_MAX = 40


# ============================================================
# Sensorparameter
# ============================================================

SENSOR_BEREICH_CM = 5
SENSOR_BEST = 3
SENSOR_INTERVALL = 0.1


# ============================================================
# Sicherheitsüberwachung
# ============================================================

WATCHDOG_TIMEOUT = 0.4
WD_INTERVALL = 0.05
CONFLICT_BEST = 2


# ============================================================
# Fahrzeugsensor
# ============================================================

class FahrzeugSensor:
    def __init__(self):
        self._zaehler = 0
        self._erkannt = False
        self._lock = threading.Lock()
        self._stop_evt = threading.Event()

        _RPIGPIO.setmode(_RPIGPIO.BCM)
        _RPIGPIO.setup(PIN_TRIG, _RPIGPIO.OUT)
        _RPIGPIO.setup(PIN_ECHO, _RPIGPIO.IN)
        _RPIGPIO.output(PIN_TRIG, _RPIGPIO.LOW)
        log.info("HC-SR04 initialisiert.")

        self._thread = threading.Thread(
            target=self._poll_schleife,
            daemon=True,
            name="SensorPoll",
        )
        self._thread.start()

    def _messen(self):
        GPIO = _RPIGPIO

        GPIO.output(PIN_TRIG, GPIO.LOW)
        time.sleep(0.06)

        GPIO.output(PIN_TRIG, GPIO.HIGH)
        time.sleep(0.00002)
        GPIO.output(PIN_TRIG, GPIO.LOW)

        start = time.monotonic()

        while GPIO.input(PIN_ECHO) == 0:
            if time.monotonic() - start > 0.5:
                log.warning("HC-SR04: Echo-Timeout kein HIGH.")
                return None

        t1 = time.monotonic()

        while GPIO.input(PIN_ECHO) == 1:
            if time.monotonic() - t1 > 0.5:
                log.warning("HC-SR04: Echo-Timeout kein LOW.")
                return None

        distanz_cm = (time.monotonic() - t1) * 17150
        return distanz_cm

    def _poll_schleife(self):
        while not self._stop_evt.is_set():
            d = self._messen()
            vorhanden = d is not None and d < SENSOR_BEREICH_CM

            with self._lock:
                if vorhanden:
                    self._zaehler = min(self._zaehler + 1, SENSOR_BEST)
                else:
                    self._zaehler = 0

                self._erkannt = self._zaehler >= SENSOR_BEST

            time.sleep(SENSOR_INTERVALL)

    @property
    def erkannt(self) -> bool:
        with self._lock:
            return self._erkannt

    def stoppe(self):
        self._stop_evt.set()
        _RPIGPIO.cleanup()
        log.info("GPIO Cleanup durchgeführt.")


# ============================================================
# Zustandsmaschine
# ============================================================

class RPiZA:
    S_CONFIG = "CONFIG"
    S_FZA_GRUEN = "FZA_GRUEN"
    S_FZA_GELB = "FZA_GELB"
    S_ZWISCHENZEIT = "ZWISCHENZEIT"
    S_FGA_GRUEN = "FGA_GRUEN"
    S_RAEUMZEIT = "RAEUMZEIT"
    S_ROT_GELB = "FZA_ROT_GELB"
    S_FEHLER = "FEHLER"
    S_AUS = "AUS"

    def __init__(self):
        self.fza_rot = LED(PIN_FZA_ROT)
        self.fza_gelb = LED(PIN_FZA_GELB)
        self.fza_gruen = LED(PIN_FZA_GRUEN)

        self.fga1_rot = LED(PIN_FGA1_ROT)
        self.fga1_gruen = LED(PIN_FGA1_GRUEN)

        self.fga2_rot = LED(PIN_FGA2_ROT)
        self.fga2_gruen = LED(PIN_FGA2_GRUEN)

        self.sensor = FahrzeugSensor()

        self.fza_gruen_zeit = 120
        self.fga_gruen_zeit = 20

        self._zustand = self.S_CONFIG
        self._phase_start = time.monotonic()
        self.on_zustandswechsel = None

        self._stop_evt = threading.Event()
        self._fehler_evt = threading.Event()
        self._zyklus_thread = None
        self._fehler_grund = ""

        self._heartbeat = time.monotonic()
        self._konflikt_zaehler = 0
        self._wd_stop_evt = threading.Event()

        self._alle_rot()

        threading.Thread(
            target=self._sicherheits_schleife,
            daemon=True,
            name="Sicherheitsmonitor",
        ).start()

    # ------------------------------------------------------------
    # Lampenzustände
    # ------------------------------------------------------------

    def _alle_rot(self):
        self.fza_gruen.off()
        self.fza_gelb.off()
        self.fza_rot.on()

        self.fga1_gruen.off()
        self.fga2_gruen.off()
        self.fga1_rot.on()
        self.fga2_rot.on()

    def _alle_aus(self):
        self.fza_rot.off()
        self.fza_gelb.off()
        self.fza_gruen.off()

        self.fga1_rot.off()
        self.fga1_gruen.off()

        self.fga2_rot.off()
        self.fga2_gruen.off()

    def _schalte_fza_gruen(self):
        if self._fehler_evt.is_set():
            return

        self.fga1_gruen.off()
        self.fga2_gruen.off()
        self.fga1_rot.on()
        self.fga2_rot.on()

        self.fza_gelb.off()
        self.fza_rot.off()
        self.fza_gruen.on()

    def _schalte_fza_gelb(self):
        if self._fehler_evt.is_set():
            return

        self.fza_gruen.off()
        self.fza_rot.off()
        self.fza_gelb.on()

    def _schalte_fza_rot_gelb(self):
        if self._fehler_evt.is_set():
            return

        self.fga1_gruen.off()
        self.fga2_gruen.off()
        self.fga1_rot.on()
        self.fga2_rot.on()

        self.fza_gruen.off()
        self.fza_rot.on()
        self.fza_gelb.on()

    def _schalte_fga_gruen(self):
        if self._fehler_evt.is_set():
            return

        self.fza_gruen.off()
        self.fza_gelb.off()
        self.fza_rot.on()

        self.fga1_rot.off()
        self.fga2_rot.off()
        self.fga1_gruen.on()
        self.fga2_gruen.on()

    # ------------------------------------------------------------
    # Zeiten
    # ------------------------------------------------------------

    def _fza_gruen_dauer(self) -> float:
        # WICHTIG:
        # Keine Minus-Rechnung.
        # Die FzA-Grünzeit entspricht direkt dem konfigurierten Wert.
        return float(self.fza_gruen_zeit)

    def _warte(self, sekunden: float) -> bool:
        ende = time.monotonic() + sekunden

        while time.monotonic() < ende:
            if self._stop_evt.is_set() or self._fehler_evt.is_set():
                return False

            self._heartbeat = time.monotonic()
            time.sleep(0.02)

        return True

    def _warte_fga_gruen(self, max_sekunden: float):
        phasen_dauer = max(max_sekunden, T_MIN_GRUEN_FGA)
        start = time.monotonic()
        phasen_ende = start + phasen_dauer
        min_gruen_ende = start + T_MIN_GRUEN_FGA

        while time.monotonic() < phasen_ende:
            if self._stop_evt.is_set() or self._fehler_evt.is_set():
                return

            self._heartbeat = time.monotonic()

            if time.monotonic() >= min_gruen_ende and self.sensor.erkannt:
                log.info("Adaptive Verkürzung der FgA-Grünphase ausgelöst.")
                return

            time.sleep(0.02)

    # ------------------------------------------------------------
    # Zustand
    # ------------------------------------------------------------

    def _setze_zustand(self, zustand: str):
        self._zustand = zustand
        self._phase_start = time.monotonic()
        self._heartbeat = time.monotonic()

        log.info("Zustandswechsel → %s", zustand)

        if self.on_zustandswechsel:
            self.on_zustandswechsel()

    @property
    def zustand(self) -> str:
        return self._zustand

    @property
    def phase_vergangen(self) -> float:
        return time.monotonic() - self._phase_start

    @property
    def fehler_grund(self) -> str:
        return self._fehler_grund

    @property
    def led_zustaende(self) -> dict:
        return {
            "fza_rot": bool(self.fza_rot.value),
            "fza_gelb": bool(self.fza_gelb.value),
            "fza_gruen": bool(self.fza_gruen.value),
            "fga1_rot": bool(self.fga1_rot.value),
            "fga1_gruen": bool(self.fga1_gruen.value),
            "fga2_rot": bool(self.fga2_rot.value),
            "fga2_gruen": bool(self.fga2_gruen.value),
        }

    # ------------------------------------------------------------
    # Sicherheit
    # ------------------------------------------------------------

    def _zyklus_aktiv(self) -> bool:
        t = self._zyklus_thread
        return t is not None and t.is_alive() and not self._stop_evt.is_set()

    def _watchdog_abgelaufen(self) -> bool:
        return time.monotonic() - self._heartbeat > WATCHDOG_TIMEOUT

    def _pruefe_vertraeglichkeit(self) -> bool:
        leds = self.led_zustaende

        konflikt = leds["fza_gruen"] and (
            leds["fga1_gruen"] or leds["fga2_gruen"]
        )

        if konflikt:
            self._konflikt_zaehler += 1
        else:
            self._konflikt_zaehler = 0

        return self._konflikt_zaehler < CONFLICT_BEST

    def _sicherheits_schleife(self):
        while not self._wd_stop_evt.is_set():
            if not self._fehler_evt.is_set():
                if not self._pruefe_vertraeglichkeit():
                    self.fehler_ausloesen("Verträglichkeitsverletzung")
                elif self._zyklus_aktiv() and self._watchdog_abgelaufen():
                    self.fehler_ausloesen("Watchdog-Timeout")

            time.sleep(WD_INTERVALL)

    def fehler_ausloesen(self, grund: str = "manuell"):
        if self._fehler_evt.is_set():
            return

        self._fehler_grund = grund
        self._fehler_evt.set()
        self._stop_evt.set()

        self._alle_rot()
        self._setze_zustand(self.S_FEHLER)

        log.error("Fehler ausgelöst: %s — alle Ampeln Rot.", grund)

    # ------------------------------------------------------------
    # Zyklus
    # ------------------------------------------------------------

    def starte(self):
        self._stop_evt.clear()
        self._fehler_evt.clear()
        self._heartbeat = time.monotonic()

        t = threading.Thread(
            target=self._zyklus_wrapper,
            daemon=True,
            name="ZyklusThread",
        )

        self._zyklus_thread = t
        t.start()

    def _zyklus_wrapper(self):
        try:
            self._zyklus()
        except Exception:
            log.exception("Unbehandelte Ausnahme im Zyklus.")
            self.fehler_ausloesen("Ausnahme im Zyklus")

    def _zyklus(self):
        while not self._stop_evt.is_set():

            self._setze_zustand(self.S_FZA_GRUEN)
            self._schalte_fza_gruen()
            if not self._warte(self._fza_gruen_dauer()):
                break

            self._setze_zustand(self.S_FZA_GELB)
            self._schalte_fza_gelb()
            if not self._warte(T_GELB):
                break

            self._setze_zustand(self.S_ZWISCHENZEIT)
            self._alle_rot()
            if not self._warte(T_ZWISCHENZEIT):
                break

            self._setze_zustand(self.S_FGA_GRUEN)
            self._schalte_fga_gruen()
            self._warte_fga_gruen(self.fga_gruen_zeit)

            if self._stop_evt.is_set():
                break

            self._setze_zustand(self.S_RAEUMZEIT)
            self._alle_rot()
            if not self._warte(T_RAEUMZEIT):
                break

            self._setze_zustand(self.S_ROT_GELB)
            self._schalte_fza_rot_gelb()
            if not self._warte(T_ROT_GELB):
                break

        if self._fehler_evt.is_set():
            return

        self._alle_aus()
        self._setze_zustand(self.S_AUS)
        log.info("Zyklus beendet — Exit-Zustand AUS.")

    def stoppe(self):
        log.info("Stop angefordert.")

        self._stop_evt.set()

        t = self._zyklus_thread
        if t is not None and t.is_alive() and t is not threading.current_thread():
            t.join(timeout=2.0)

        if not self._fehler_evt.is_set():
            self._alle_aus()
            self._setze_zustand(self.S_AUS)

    def aufraeumen(self):
        self._wd_stop_evt.set()
        self.stoppe()
        self._alle_aus()
        self.sensor.stoppe()


# ============================================================
# GUI
# ============================================================

_HINTERGRUND = "#16213e"
_FZA_BG = "#1a1a3e"
_FGA_BG = "#1a3e1a"

_LED_AUS = "#2a2a2a"
_LED_ROT = "#ff3333"
_LED_GELB = "#ffcc00"
_LED_GRUEN = "#33ff66"


_ZUSTAND_TEXT = {
    RPiZA.S_CONFIG: "CONFIG — Parameter eingeben, dann Start drücken",
    RPiZA.S_FZA_GRUEN: "FzA: GRÜN — Fahrzeuge fahren",
    RPiZA.S_FZA_GELB: "FzA: GELB — Übergang Grün → Rot",
    RPiZA.S_ZWISCHENZEIT: "ZWISCHENZEIT — alle Ampeln Rot",
    RPiZA.S_FGA_GRUEN: "FgA: GRÜN — Fußgänger überqueren",
    RPiZA.S_RAEUMZEIT: "RÄUMZEIT — alle Ampeln Rot",
    RPiZA.S_ROT_GELB: "FzA: ROT + GELB — Vorbereitung Grün",
    RPiZA.S_FEHLER: "FEHLER — alle Ampeln Rot",
    RPiZA.S_AUS: "AUS — alle Ampeln aus",
}


class _Linse(tk.Canvas):
    def __init__(self, parent, farbe: str, groesse: int = 52, hg: str = "#111122"):
        super().__init__(
            parent,
            width=groesse,
            height=groesse,
            bg=hg,
            highlightthickness=0,
        )

        m = 5
        self._oval = self.create_oval(
            m,
            m,
            groesse - m,
            groesse - m,
            fill=_LED_AUS,
            outline="#444",
            width=2,
        )
        self._farbe_an = farbe

    def setze(self, an: bool):
        self.itemconfig(self._oval, fill=self._farbe_an if an else _LED_AUS)


class RPiZAGui:
    def __init__(self, root: tk.Tk, steuerung: RPiZA):
        self.root = root
        self.steuerung = steuerung

        steuerung.on_zustandswechsel = lambda: root.after(0, self._aktualisiere)

        root.title("RPiZA v3.0 — Zuflussregelungsanlage")
        root.configure(bg=_HINTERGRUND)
        root.resizable(False, False)

        self._baue_gui()
        self._poll()

    def _baue_gui(self):
        r = self.root

        tk.Label(
            r,
            text="RPiZA v3.0 — Fußgänger-Zuflussregelungsanlage",
            font=("Helvetica", 16, "bold"),
            bg=_HINTERGRUND,
            fg="white",
        ).pack(pady=(12, 2))

        tk.Label(
            r,
            text="StVO §37 · RiLSA 2015 · Lights! GmbH",
            font=("Helvetica", 9),
            bg=_HINTERGRUND,
            fg="#888888",
        ).pack(pady=(0, 2))

        tk.Label(
            r,
            text="Sicherheitsüberwachung aktiv — Watchdog + Verträglichkeit",
            font=("Helvetica", 8),
            bg=_HINTERGRUND,
            fg="#5a8a5a",
        ).pack(pady=(0, 4))

        self._zustand_var = tk.StringVar(value=_ZUSTAND_TEXT[RPiZA.S_CONFIG])

        tk.Label(
            r,
            textvariable=self._zustand_var,
            font=("Helvetica", 11),
            bg=_HINTERGRUND,
            fg="#aaaaff",
            width=54,
        ).pack(pady=(0, 2))

        self._timer_var = tk.StringVar(value="Phase: 0 s")

        tk.Label(
            r,
            textvariable=self._timer_var,
            font=("Courier", 11),
            bg=_HINTERGRUND,
            fg="#ffcc44",
        ).pack(pady=(0, 8))

        ampel_frame = tk.Frame(r, bg=_HINTERGRUND)
        ampel_frame.pack(padx=20, pady=4)

        self._fza_r, self._fza_y, self._fza_g = self._baue_fza_panel(ampel_frame, 0)
        self._fga1_r, self._fga1_g = self._baue_fga_panel(ampel_frame, 1, "FgA1")
        self._fga2_r, self._fga2_g = self._baue_fga_panel(ampel_frame, 2, "FgA2")

        ttk.Separator(r).pack(fill="x", padx=12, pady=8)

        cfg = tk.Frame(r, bg=_HINTERGRUND)
        cfg.pack(padx=20, pady=4)

        self._baue_konfiguration(cfg)

        ttk.Separator(r).pack(fill="x", padx=12, pady=8)

        btn_frame = tk.Frame(r, bg=_HINTERGRUND)
        btn_frame.pack(pady=4)

        self._btn_start = tk.Button(
            btn_frame,
            text="Start",
            width=12,
            bg="#1a6b3a",
            fg="white",
            command=self._start,
        )
        self._btn_start.grid(row=0, column=0, padx=6)

        self._btn_stop = tk.Button(
            btn_frame,
            text="Stop",
            width=12,
            bg="#6b1a1a",
            fg="white",
            command=self._stop,
            state="disabled",
        )
        self._btn_stop.grid(row=0, column=1, padx=6)

        self._btn_fehler = tk.Button(
            btn_frame,
            text="Fehler / Fail-Safe",
            width=18,
            bg="#7a3a00",
            fg="white",
            command=self._fehler_ausloesen,
        )
        self._btn_fehler.grid(row=0, column=2, padx=6)

    def _baue_fza_panel(self, parent, col):
        f = tk.Frame(parent, bg=_FZA_BG, bd=2, relief="ridge")
        f.grid(row=0, column=col, padx=14, pady=4)

        tk.Label(
            f,
            text="FzA\nFahrzeugampel",
            bg=_FZA_BG,
            fg="white",
            font=("Helvetica", 9, "bold"),
        ).pack(pady=(8, 2))

        rot = _Linse(f, _LED_ROT, hg=_FZA_BG)
        gelb = _Linse(f, _LED_GELB, hg=_FZA_BG)
        gruen = _Linse(f, _LED_GRUEN, hg=_FZA_BG)

        rot.pack(pady=3)
        gelb.pack(pady=3)
        gruen.pack(pady=3)

        return rot, gelb, gruen

    def _baue_fga_panel(self, parent, col, label):
        f = tk.Frame(parent, bg=_FGA_BG, bd=2, relief="ridge")
        f.grid(row=0, column=col, padx=14, pady=4)

        tk.Label(
            f,
            text=label,
            bg=_FGA_BG,
            fg="white",
            font=("Helvetica", 9, "bold"),
        ).pack(pady=(8, 2))

        rot = _Linse(f, _LED_ROT, hg=_FGA_BG)
        gruen = _Linse(f, _LED_GRUEN, hg=_FGA_BG)

        rot.pack(pady=3)
        gruen.pack(pady=3)

        return rot, gruen

    def _baue_konfiguration(self, parent):
        tk.Label(
            parent,
            text="Operator-Konfiguration",
            font=("Helvetica", 12, "bold"),
            bg=_HINTERGRUND,
            fg="#ffcc44",
        ).grid(row=0, column=0, columnspan=3, pady=(0, 8))

        tk.Label(
            parent,
            text=f"FzA-Grünphase [{FZA_GRUEN_MIN}–{FZA_GRUEN_MAX} s]:",
            bg=_HINTERGRUND,
            fg="#cccccc",
            width=36,
            anchor="w",
        ).grid(row=1, column=0, sticky="w", pady=4)

        self._eingabe_fza = tk.Entry(parent, width=7)
        self._eingabe_fza.insert(0, str(self.steuerung.fza_gruen_zeit))
        self._eingabe_fza.grid(row=1, column=1, padx=6)

        self._fehler_fza = tk.Label(
            parent,
            text="",
            bg=_HINTERGRUND,
            fg="#ff6666",
            width=38,
            anchor="w",
        )
        self._fehler_fza.grid(row=1, column=2, sticky="w")

        tk.Label(
            parent,
            text=f"FgA-Grünphase [{FGA_GRUEN_MIN}–{FGA_GRUEN_MAX} s]:",
            bg=_HINTERGRUND,
            fg="#cccccc",
            width=36,
            anchor="w",
        ).grid(row=2, column=0, sticky="w", pady=4)

        self._eingabe_fga = tk.Entry(parent, width=7)
        self._eingabe_fga.insert(0, str(self.steuerung.fga_gruen_zeit))
        self._eingabe_fga.grid(row=2, column=1, padx=6)

        self._fehler_fga = tk.Label(
            parent,
            text="",
            bg=_HINTERGRUND,
            fg="#ff6666",
            width=38,
            anchor="w",
        )
        self._fehler_fga.grid(row=2, column=2, sticky="w")

    def _validiere(self) -> bool:
        ok = True

        try:
            v_fza = int(self._eingabe_fza.get())

            if FZA_GRUEN_MIN <= v_fza <= FZA_GRUEN_MAX:
                self.steuerung.fza_gruen_zeit = v_fza
                self._fehler_fza.config(text="✓")
            else:
                self._fehler_fza.config(
                    text=f"Wert {v_fza} ungültig — Bereich [{FZA_GRUEN_MIN}, {FZA_GRUEN_MAX}]"
                )
                ok = False

        except ValueError:
            self._fehler_fza.config(text="Ganzzahl erforderlich")
            ok = False

        try:
            v_fga = int(self._eingabe_fga.get())

            if FGA_GRUEN_MIN <= v_fga <= FGA_GRUEN_MAX:
                self.steuerung.fga_gruen_zeit = v_fga
                self._fehler_fga.config(text="✓")
            else:
                self._fehler_fga.config(
                    text=f"Wert {v_fga} ungültig — Bereich [{FGA_GRUEN_MIN}, {FGA_GRUEN_MAX}]"
                )
                ok = False

        except ValueError:
            self._fehler_fga.config(text="Ganzzahl erforderlich")
            ok = False

        return ok

    def _start(self):
        if not self._validiere():
            return

        self._eingabe_fza.config(state="disabled")
        self._eingabe_fga.config(state="disabled")

        self._btn_start.config(state="disabled")
        self._btn_stop.config(state="normal")

        self.steuerung.starte()

    def _stop(self):
        self.steuerung.stoppe()

        self._eingabe_fza.config(state="normal")
        self._eingabe_fga.config(state="normal")

        self._btn_start.config(state="normal")
        self._btn_stop.config(state="disabled")

    def _fehler_ausloesen(self):
        self.steuerung.fehler_ausloesen("Manuell")

        self._eingabe_fza.config(state="disabled")
        self._eingabe_fga.config(state="disabled")

        self._btn_start.config(state="disabled")
        self._btn_stop.config(state="disabled")
        self._btn_fehler.config(state="disabled")

    def _timer_text(self) -> str:
        s = self.steuerung
        zustand = s.zustand
        vergangen = s.phase_vergangen
        if zustand in (RPiZA.S_CONFIG, RPiZA.S_AUS, RPiZA.S_FEHLER):
            return "—"

        if zustand == RPiZA.S_FZA_GRUEN:
            gesamt = s.fza_gruen_zeit
        elif zustand == RPiZA.S_FZA_GELB:
            gesamt = T_GELB
        elif zustand == RPiZA.S_ZWISCHENZEIT:
            gesamt = T_ZWISCHENZEIT
        elif zustand == RPiZA.S_FGA_GRUEN:
            gesamt = max(s.fga_gruen_zeit, T_MIN_GRUEN_FGA)
        elif zustand == RPiZA.S_RAEUMZEIT:
            gesamt = T_RAEUMZEIT
        elif zustand == RPiZA.S_ROT_GELB:
            gesamt = T_ROT_GELB
        else:
            return f"{vergangen:.0f} s"

        rest = max(gesamt - vergangen, 0)

        return f"{vergangen:.0f} s / {gesamt:.0f} s ({rest:.0f} s verbleibend)"

    def _aktualisiere(self):
        leds = self.steuerung.led_zustaende

        self._fza_r.setze(leds["fza_rot"])
        self._fza_y.setze(leds["fza_gelb"])
        self._fza_g.setze(leds["fza_gruen"])

        self._fga1_r.setze(leds["fga1_rot"])
        self._fga1_g.setze(leds["fga1_gruen"])

        self._fga2_r.setze(leds["fga2_rot"])
        self._fga2_g.setze(leds["fga2_gruen"])

        zustand = self.steuerung.zustand

        if zustand == RPiZA.S_FEHLER:
            self._zustand_var.set(
                f"FEHLER — {self.steuerung.fehler_grund} · alle Ampeln Rot"
            )
        else:
            self._zustand_var.set(_ZUSTAND_TEXT.get(zustand, zustand))

        self._timer_var.set(self._timer_text())

    def _poll(self):
        self._aktualisiere()
        self.root.after(80, self._poll)


# ============================================================
# Einstiegspunkt
# ============================================================

def main():
    root = tk.Tk()
    steuerung = RPiZA()
    RPiZAGui(root, steuerung)

    def beim_schliessen():
        steuerung.aufraeumen()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", beim_schliessen)
    root.mainloop()


if __name__ == "__main__":
    main()
