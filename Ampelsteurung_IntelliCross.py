#!/usr/bin/env python3
"""
HC-SR04 Standalone-Test für Raspberry Pi 3 B+
TRIG = GPIO19, ECHO = GPIO23 (BCM-Nummerierung)
Echo-Pin benötigt Spannungsteiler 5V -> 3,3V!
Abbrechen mit Strg+C
"""
import RPi.GPIO as GPIO
import time

PIN_TRIG = 19
PIN_ECHO = 23

GPIO.setmode(GPIO.BCM)
GPIO.setup(PIN_TRIG, GPIO.OUT)
GPIO.setup(PIN_ECHO, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
GPIO.output(PIN_TRIG, GPIO.LOW)

print("HC-SR04 Test gestartet. Sensor stabilisieren (2s)...")
time.sleep(2)


def messen():
    GPIO.output(PIN_TRIG, GPIO.LOW)
    time.sleep(0.06)
    GPIO.output(PIN_TRIG, GPIO.HIGH)
    time.sleep(0.00002)
    GPIO.output(PIN_TRIG, GPIO.LOW)

    start = time.monotonic()
    while GPIO.input(PIN_ECHO) == 0:
        if time.monotonic() - start > 0.5:
            print("Timeout: kein HIGH am Echo-Pin erkannt.")
            return None

    t1 = time.monotonic()
    while GPIO.input(PIN_ECHO) == 1:
        if time.monotonic() - t1 > 0.5:
            print("Timeout: kein LOW am Echo-Pin erkannt.")
            return None

    dauer = time.monotonic() - t1
    distanz_cm = dauer * 17150
    return distanz_cm


try:
    while True:
        d = messen()
        if d is not None:
            print(f"Distanz: {d:6.1f} cm")
        else:
            print("Keine gültige Messung.")
        time.sleep(0.3)

except KeyboardInterrupt:
    print("\nBeende Test...")

finally:
    GPIO.cleanup()
    print("GPIO Cleanup durchgeführt.")
