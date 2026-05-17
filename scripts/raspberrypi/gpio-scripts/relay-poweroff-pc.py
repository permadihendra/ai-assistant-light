#!/usr/bin/venv python3
import time

import RPi.GPIO as GPIO

RELAY_PIN = 17

GPIO.setmode(GPIO.BCM)
GPIO.setup(RELAY_PIN, GPIO.OUT)

try:
    GPIO.output(RELAY_PIN, GPIO.LOW)
    time.sleep(5)
    GPIO.output(RELAY_PIN, GPIO.HIGH)

except KeyboardInterrupt:
    print("interupted")

finally:
    GPIO.cleanup()
    print("GPIO Cleanup")
