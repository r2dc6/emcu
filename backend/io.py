"""Named relay I/O and independently scheduled, terminable DHT acquisition."""
import math
import multiprocessing
import queue
import time

from .config import (ACU_SECONDARY_GPIO_KEYS, INPUT_GPIO_KEYS, OUTPUT_GPIO_KEYS,
                     OUTPUTS, SENSOR_GPIO_KEYS, validate)

DIGITAL_FIELDS = {"door": "door_open", "water": "water_level_alarm", "smoke": "smoke_alarm"}
DHT_FIELDS = ("temperature_c", "humidity_pct")


def valid_sample(value, maximum):
    return type(value) in (int, float) and math.isfinite(value) and 0 <= value <= maximum


def _dht_worker(pin, interval, samples, stop):
    device = None
    try:
        import board
        import adafruit_dht
        device = adafruit_dht.DHT11(getattr(board, f"D{pin}"), use_pulseio=False)
        while not stop.is_set():
            started = time.monotonic()
            try:
                temperature, humidity = device.temperature, device.humidity
                sample = (temperature, humidity, time.monotonic())
                try:
                    samples.put_nowait(sample)
                except queue.Full:
                    pass
            except Exception:
                pass
            stop.wait(max(0, interval.value - (time.monotonic() - started)))
    finally:
        if device is not None:
            device.exit()


class IO:
    def __init__(self, config, output_factory=None, input_factory=None,
                 dht_reader=None, clock=time.monotonic):
        validate(config)
        self.sim = config["simulation"]
        self.config = config
        self.clock = clock
        self.outputs = {key: False for key in OUTPUTS}
        self.devices = {}
        self.secondary_devices = {}
        self.inputs = {}
        self.closed = False
        self.dht_reader = dht_reader
        self.process = None
        self.samples = None
        self.dht_stop = None
        self.next_poll = 0
        self.sim_values = {"temperature_c": 24.0, "humidity_pct": 50.0,
                           **{key: False for key in DIGITAL_FIELDS.values()}}
        self.sim_times = {key: clock() for key in self.sim_values}
        if self.sim:
            return
        try:
            if output_factory is None or input_factory is None:
                from gpiozero import DigitalInputDevice, DigitalOutputDevice
                output_factory = output_factory or DigitalOutputDevice
                input_factory = input_factory or DigitalInputDevice
            for key, pin_key in OUTPUT_GPIO_KEYS.items():
                self.devices[key] = output_factory(
                    config["gpio"][pin_key],
                    active_high=True if key in ("acu1", "acu2", "door") else config["output_active_high"][key],
                    initial_value=False)
                if key in ACU_SECONDARY_GPIO_KEYS:
                    self.secondary_devices[key] = output_factory(
                        config["gpio"][ACU_SECONDARY_GPIO_KEYS[key]],
                        active_high=True, initial_value=False)
            for key, pin_key in INPUT_GPIO_KEYS.items():
                pull = config["input_pull"][key]
                kwargs = {"pull_up": {"none": None, "up": True, "down": False}[pull]}
                if pull == "none":
                    kwargs["active_state"] = True
                self.inputs[key] = input_factory(config["gpio"][pin_key], **kwargs)
        except BaseException:
            self.close()
            raise

    def write(self, name, value):
        if self.closed:
            raise RuntimeError("I/O is closed")
        value = bool(value)
        if not self.sim:
            devices = [self.devices[name]]
            if name in self.secondary_devices:
                devices.append(self.secondary_devices[name])
            error = None
            # Attempt both relays even if one fails, especially for fail-OFF.
            for device in devices:
                try:
                    device.on() if value else device.off()
                except Exception as exc:
                    if error is None:
                        error = exc
            if error is not None:
                raise error
        self.outputs[name] = value

    def read_digital(self, active_high):
        if self.sim:
            return {key: self.sim_values[key] for key in DIGITAL_FIELDS.values()}
        return {field: bool(self.inputs[key].pin.state) == active_high[key]
                for key, field in DIGITAL_FIELDS.items()}

    def simulation_update(self, patch):
        now = self.clock()
        self.sim_values.update(patch)
        for key in patch:
            self.sim_times[key] = now if patch[key] is not None else None

    def start(self, poll_seconds):
        if self.sim or self.dht_reader is not None or self.process is not None:
            return
        try:
            context = multiprocessing.get_context("spawn")
            self.samples = context.Queue(maxsize=4)
            self.dht_stop = context.Event()
            self.interval = context.Value("d", poll_seconds)
            self.process = context.Process(target=_dht_worker,
                                           args=(self.config["gpio"][SENSOR_GPIO_KEYS["dht"]], self.interval,
                                                 self.samples, self.dht_stop), daemon=True)
            self.process.start()
        except BaseException:
            self.close()
            raise

    def poll_dht(self, poll_seconds):
        if self.sim:
            return {key: (self.sim_values[key], self.sim_times[key]) for key in DHT_FIELDS}
        if self.dht_reader is not None:
            now = self.clock()
            if now < self.next_poll:
                return {}
            self.next_poll = now + poll_seconds
            try:
                temperature, humidity = self.dht_reader()
            except Exception:
                return {}
            sample = (temperature, humidity, self.clock())
        else:
            if self.process is None:
                return {}
            self.interval.value = poll_seconds
            sample = None
            while True:
                try:
                    sample = self.samples.get_nowait()
                except queue.Empty:
                    break
            if sample is None:
                return {}
        temperature, humidity, sampled_at = sample
        return {key: (value, sampled_at) for key, value, maximum in
                (("temperature_c", temperature, 50), ("humidity_pct", humidity, 100))
                if valid_sample(value, maximum)}

    def close(self):
        if self.closed:
            return
        for name, device in self.devices.items():
            try:
                self.write(name, False)
            except Exception:
                pass
        # A blocked DHT driver is isolated from relay cleanup and forcibly terminable.
        def attempt(operation):
            try:
                operation()
            except Exception:
                pass

        if self.process is not None:
            def alive():
                try:
                    return self.process.is_alive()
                except Exception:
                    return True

            attempt(self.dht_stop.set)
            attempt(lambda: self.process.join(0.5))
            if alive():
                attempt(self.process.terminate)
                attempt(lambda: self.process.join(0.5))
            if alive():
                attempt(self.process.kill)
                attempt(lambda: self.process.join(0.5))
            attempt(self.process.close)
        if self.samples is not None:
            attempt(self.samples.close)
            attempt(self.samples.cancel_join_thread)
        for device in (*self.devices.values(), *self.secondary_devices.values(),
                       *self.inputs.values()):
            try:
                device.close()
            except Exception:
                pass
        self.closed = True
