"""Toggle BCM GPIO 21 on and off every 5 seconds."""
import signal
import sys
import time

from gpiozero import DigitalOutputDevice

PIN = 26
INTERVAL = 5.0  # seconds between state changes

def main():
    relay = DigitalOutputDevice(PIN, active_high=True, initial_value=False)
    running = True

    def stop(signum, frame):
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    try:
        print(f"acuPilot hardware test: toggling GPIO {PIN} every {INTERVAL}s")
        while running:
            relay.on()
            print(f"GPIO {PIN}: ON")
            # Sleep in small slices so signals are handled promptly.
            for _ in range(int(INTERVAL * 10)):
                if not running:
                    break
                time.sleep(0.1)
            if not running:
                break
            relay.off()
            print(f"GPIO {PIN}: OFF")
            for _ in range(int(INTERVAL * 10)):
                if not running:
                    break
                time.sleep(0.1)
    finally:
        relay.off()
        relay.close()
        print(f"GPIO {PIN} released, exiting.")

if __name__ == "__main__":
    main()