#!/usr/bin/venv python3
import time

import RPi.GPIO as GPIO

RELAY_PIN = 17

GPIO.setmode(GPIO.BCM)
GPIO.setup(RELAY_PIN, GPIO.OUT)

# relay ON -(press button)
GPIO.output(RELAY_PIN, GPIO.LOW)
time.sleep(0.2)
# relay OFF (release button)
GPIO.output(RELAY_PIN, GPIO.HIGH)

GPIO.cleanup()
