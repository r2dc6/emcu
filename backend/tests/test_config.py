import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.config import (ACU_SECONDARY_GPIO_KEYS, Configuration, DEFAULTS, INPUT_GPIO_KEYS, INPUTS,
                            OUTPUT_GPIO_KEYS, OUTPUTS, PIN_KEYS, SENSOR_GPIO_KEYS, validate)


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "config.json"
        self.config = Configuration(self.path, {})

    def test_defaults_and_copy_isolation(self):
        self.assertEqual(self.config.effective, DEFAULTS)
        self.config.contract()["defaults"]["gpio"]["acu1"] = 17
        self.assertEqual(DEFAULTS["gpio"]["acu1"], 16)

    def test_explicit_gpio_defaults_and_channel_coverage(self):
        self.assertEqual(DEFAULTS["gpio"], {
            "acu1": 16, "acu1_2": 11, "acu2": 9, "acu2_2": 10,
            "door": 24, "water": 23, "smoke": 25,
            "dht": 4, "alarm_water": 26, "alarm_smoke": 19,
            "alarm_temperature": 13, "alarm_humidity": 6, "alarm_door": 0,
        })
        pin_keys = [pin_key for mapping in
                    (INPUT_GPIO_KEYS, OUTPUT_GPIO_KEYS, ACU_SECONDARY_GPIO_KEYS, SENSOR_GPIO_KEYS)
                    for pin_key in mapping.values()]
        self.assertCountEqual(pin_keys, DEFAULTS["gpio"])
        self.assertEqual(len(pin_keys), len(set(pin_keys)))
        self.assertEqual(PIN_KEYS, tuple(DEFAULTS["gpio"]))
        self.assertEqual(INPUTS, tuple(INPUT_GPIO_KEYS))
        self.assertEqual(OUTPUTS, tuple(OUTPUT_GPIO_KEYS))
        self.assertEqual(INPUTS, ("door", "water", "smoke"))
        self.assertEqual(OUTPUTS, ("acu1", "acu2", "water", "smoke", "temperature", "humidity", "door"))
        self.assertEqual(DEFAULTS["door_alarm_seconds"], 3)

    def test_legacy_six_output_config_inherits_door_without_rewrite(self):
        self.path.write_text(json.dumps({
            "gpio": {"door": 22}, "door_alarm_seconds": 60,
            "output_active_high": {key: True for key in OUTPUTS if key != "door"},
        }))
        before = self.path.read_bytes()
        config = Configuration(self.path)
        self.assertEqual(config.effective["gpio"]["alarm_door"], 0)
        self.assertEqual(config.effective["gpio"]["door"], 22)
        self.assertTrue(config.effective["output_active_high"]["door"])
        self.assertEqual(config.effective["door_alarm_seconds"], 60)
        self.assertEqual(self.path.read_bytes(), before)

    def test_named_gpio_override_preserves_other_defaults(self):
        before = copy.deepcopy(DEFAULTS)
        config = Configuration(self.path, {"gpio": {"water": 24}})
        expected = copy.deepcopy(before["gpio"])
        expected["water"] = 24
        self.assertEqual(config.effective["gpio"], expected)
        self.assertEqual(DEFAULTS, before)

    def test_legacy_boolean_polarity_conversion(self):
        config = Configuration(self.path, {"output_active_high": True})
        self.assertEqual(config.effective["output_active_high"], dict.fromkeys(OUTPUTS, True))
        candidate = config.candidate({"water_alarm_seconds": 7})
        config.save({"water_alarm_seconds": 7}, candidate)
        self.assertEqual(json.loads(self.path.read_text())["output_active_high"],
                         dict.fromkeys(OUTPUTS, True))
        self.assertEqual(Configuration(self.path).effective["water_alarm_seconds"], 7)
        with self.assertRaisesRegex(ValueError, "output_active_high.acu1"):
            Configuration(self.path, {"output_active_high": False})

    def test_unknown_startup_keys_rejected_without_rewriting(self):
        for raw in ({"unknown": 1}, {"obsolete_seconds": 1},
                    {"gpio": {"unknown": 24}}, {"input_active_high": {"unknown": True}},
                    {"input_pull": {"unknown": "none"}}, []):
            with self.subTest(raw=raw):
                self.path.write_text(json.dumps(raw))
                before = self.path.read_bytes()
                with self.assertRaises(ValueError):
                    Configuration(self.path)
                self.assertEqual(self.path.read_bytes(), before)
        candidate = copy.deepcopy(DEFAULTS)
        candidate["unknown"] = 1
        with self.assertRaisesRegex(ValueError, "Unknown configuration setting"):
            validate(candidate)

    def test_acu_polarity_requires_exact_true_in_both_modes(self):
        for simulation in (True, False):
            for channel in ("acu1", "acu2", "door"):
                for value in (False, 0, 1, None, "true"):
                    raw = {"simulation": simulation,
                           "gpio": dict(zip(DEFAULTS["gpio"], range(len(PIN_KEYS)))),
                           "output_active_high": {channel: value}}
                    with self.subTest(simulation=simulation, channel=channel, value=value):
                        with self.assertRaisesRegex(ValueError, f"output_active_high.{channel}"):
                            Configuration(self.path, raw)

    def test_alarm_active_low_is_supported_in_both_modes(self):
        for simulation in (True, False):
            config = Configuration(self.path, {
                "simulation": simulation, "gpio": dict(zip(DEFAULTS["gpio"], range(len(PIN_KEYS)))),
                "output_active_high": {key: False for key in OUTPUTS if key not in ("acu1", "acu2", "door")},
            })
            self.assertTrue(config.effective["output_active_high"]["acu1"])
            self.assertTrue(config.effective["output_active_high"]["acu2"])
            self.assertFalse(config.effective["output_active_high"]["smoke"])

    def test_saved_installation_loads_unchanged(self):
        path = Path(__file__).resolve().parents[2] / "config.json"
        before = path.read_bytes()
        config = Configuration(path)
        self.assertEqual(config.raw["gpio"], DEFAULTS["gpio"])
        self.assertEqual(config.effective["gpio"], DEFAULTS["gpio"])
        expected_pull = {"door": "up", "water": "up", "smoke": "up"}
        self.assertEqual(DEFAULTS["input_pull"], expected_pull)
        self.assertEqual(config.raw["input_pull"], expected_pull)
        self.assertEqual(config.effective["input_pull"], expected_pull)
        self.assertEqual(config.effective["input_active_high"],
                         config.raw["input_active_high"])
        self.assertEqual(config.effective["door_alarm_seconds"],
                         config.raw["door_alarm_seconds"])
        self.assertEqual(path.read_bytes(), before)

    def test_nonnegative_restart_delay_is_valid_and_persists(self):
        for value in (0, 1, 60, 120, 179, 180):
            with self.subTest(value=value):
                candidate = self.config.candidate({"min_off_seconds": value})
                self.config.save({"min_off_seconds": value}, candidate)
                self.assertEqual(Configuration(self.path).effective["min_off_seconds"], value)

    def test_invalid_runtime_values(self):
        cases = [{"rotation_seconds": 1799}, {"min_off_seconds": -1},
                 {"sensor_poll_seconds": 1}, {"sensor_stale_seconds": 3},
                 {"control_tick_seconds": 0}, {"boost_on_c": 25},
                 {"boost_off_c": -1}, {"high_temp_alarm_c": 51},
                 {"high_humidity_alarm_pct": 101}, {"door_alarm_seconds": -1},
                 {"water_alarm_seconds": True}, {"smoke_alarm_seconds": "3"},
                 {"humidity_alarm_seconds": float("nan")},
                 {"temperature_alarm_seconds": float("inf")},
                 {"gpio": {}}, {"simulation": False}, {"unknown": 1},
                 {"input_active_high": {"water": 1}},
                 {"input_active_high": {"unknown": True}},
                 {"input_active_high": None}]
        for value in cases:
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.config.candidate(value)

    def test_hardware_validation(self):
        config = copy.deepcopy(DEFAULTS)
        config["simulation"] = False
        config["gpio"]["water"] = None
        with self.assertRaises(ValueError):
            validate(config)
        config["gpio"] = dict(zip(config["gpio"], range(len(PIN_KEYS))))
        validate(config)
        candidate = copy.deepcopy(config)
        candidate["gpio"]["alarm_door"] = candidate["gpio"]["acu1"]
        with self.assertRaisesRegex(ValueError, "distinct"):
            validate(candidate)
        for value in (None, 28, -1, True, 1.5, 1):
            candidate = copy.deepcopy(config)
            candidate["gpio"]["acu1"] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate(candidate)

    def test_installation_types_and_pulls(self):
        for group, value in (("simulation", "false"), ("gpio", []),
                             ("input_pull", {"door": "invalid"}),
                             ("output_active_high", {"water": "LOW"})):
            with self.subTest(group=group), self.assertRaises(ValueError):
                Configuration(self.path, {group: value})

    def test_failed_persistence_changes_nothing(self):
        self.path.write_text("{}")
        old = copy.deepcopy(self.config.effective)
        with patch("backend.config.os.replace", side_effect=OSError("disk")), self.assertRaises(OSError):
            self.config.save({"water_alarm_seconds": 4},
                             self.config.candidate({"water_alarm_seconds": 4}))
        self.assertEqual(self.config.effective, old)
        self.assertEqual(self.path.read_text(), "{}")
        self.assertEqual(list(self.path.parent.glob(".config-*")), [])

    def test_partial_polarity_merge_and_threshold_independence(self):
        candidate = self.config.candidate({"input_active_high": {"water": False},
                                           "high_temp_alarm_c": 10})
        self.assertFalse(candidate["input_active_high"]["water"])
        self.assertTrue(candidate["input_active_high"]["smoke"])
        self.assertEqual(candidate["high_temp_alarm_c"], 10)
