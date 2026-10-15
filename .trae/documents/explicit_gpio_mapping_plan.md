# Explicit GPIO Mapping Plan

## Summary

Make GPIO assignment easy to read and edit by replacing positional pin assignment and name-based output routing with explicit dictionaries in `backend/config.py` and `backend/io.py`. Preserve all current BCM assignments and configuration compatibility.

## Current State Analysis

- `backend/config.py` defines `INPUTS`, `OUTPUTS`, and `PIN_KEYS` separately. `DEFAULTS["gpio"]` pairs `PIN_KEYS` with a positional tuple using `zip`.
- `backend/io.py` infers output GPIO configuration keys using `startswith("acu")` and an `alarm_` prefix. Digital inputs and DHT use direct configuration lookups.
- `config.json` already contains named GPIO assignments and overrides Python defaults through `Configuration` merging.
- The README identifies current assignments as installation candidates and deliberately leaves the water input and four alarm outputs unassigned.
- Validation already enforces supported BCM numbers and complete, distinct assignments in hardware mode.
- Existing tests cover configuration validation, polarity, simulated hardware, DHT scheduling, and cleanup, but do not explicitly assert every channel-to-pin binding.
- `main.py` has an existing unrelated modification; leave it untouched.

## Assumptions & Decisions

- User confirmed preserving current pins and prioritizing readability for any programmer.
- Use dictionaries, not arrays or positional assignment.
- Keep the existing flat `gpio` JSON schema and logical channel names. No configuration migration, API changes, or HMI changes.
- Use BCM numbering, not physical header numbering.
- Retain `None` for unconfirmed wiring. Never assign new hardware pins automatically.
- Keep DHT as a separate sensor channel because its driver manages its data protocol, not as an ordinary digital input.
- Keep runtime behavior, polarity, pull configuration, startup validation, simulation, and cleanup unchanged.
- Scope includes the two implementation files and focused regression tests. Do not modify `config.json` or README.

## Proposed Changes

### 1. `backend/config.py`

- Replace the `dict(zip(...))` GPIO defaults with a literal dictionary, one named channel per line.
- Group the dictionary using short comments for ACU relay outputs, digital inputs, the DHT sensor, and alarm relay outputs.
- Preserve these values:

| GPIO key | Role | BCM default |
| --- | --- | --- |
| acu1 | ACU1 relay output | 17 |
| acu2 | ACU2 relay output | 27 |
| door | Door digital input | 22 |
| water | Water digital input | None |
| smoke | Smoke digital input | 23 |
| dht | DHT11 data | 4 |
| alarm_water | Water alarm relay output | None |
| alarm_smoke | Smoke alarm relay output | None |
| alarm_temperature | Temperature alarm relay output | None |
| alarm_humidity | Humidity alarm relay output | None |

- Define explicit `INPUT_GPIO_KEYS`, `OUTPUT_GPIO_KEYS`, and `SENSOR_GPIO_KEYS` dictionaries mapping logical channel names to existing `gpio` configuration keys:
  - Inputs: door -> door, water -> water, smoke -> smoke.
  - Outputs: acu1 -> acu1, acu2 -> acu2, water -> alarm_water, smoke -> alarm_smoke, temperature -> alarm_temperature, humidity -> alarm_humidity.
  - Sensors: dht -> dht.
- Derive `INPUTS` and `OUTPUTS` tuples from the corresponding mapping keys, preserving their current order and types.
- Retain `PIN_KEYS` as a tuple derived from the explicit GPIO defaults dictionary, preserving its current order. Place its definition after `DEFAULTS`.
- Add concise comments explaining that pin numbers are assigned in `DEFAULTS["gpio"]`, `None` means unassigned, and installation values in `config.json` override those defaults. The channel-role dictionaries reference configuration keys, not another set of pin numbers.
- Leave validation and persistence behavior unchanged.

### 2. `backend/io.py`

- Import the explicit channel-role mappings from configuration.
- Initialize outputs by iterating `OUTPUT_GPIO_KEYS.items()` and looking up the configured pin by its explicit GPIO key. Remove the prefix/name inference.
- Initialize digital inputs by iterating `INPUT_GPIO_KEYS.items()` while preserving existing pull and active-state handling.
- Resolve the DHT process pin through `SENSOR_GPIO_KEYS["dht"]`.
- Preserve logical device names, output state handling, process behavior, and resource cleanup.

### 3. `backend/tests/test_config.py`

- Assert the exact named default GPIO dictionary, including all five unassigned pins.
- Assert that the role mappings cover every GPIO key exactly once and that input/output tuples match their mapping keys.
- Verify a partial named GPIO override changes only the selected pin and does not mutate defaults.
- Keep existing validation cases for missing, duplicate, invalid, and unsupported pins.

### 4. `backend/tests/test_io.py`

- Add a named, nonsequential hardware pin fixture for mapping-focused tests; keep all ten BCM pins valid and distinct.
- Assert every output and digital input factory receives the configured pin for its exact logical channel, especially water/smoke inputs versus their separate alarm outputs.
- Assert DHT process construction receives the configured DHT pin using the existing multiprocessing mock pattern.
- Preserve existing polarity, cleanup, simulation, and scheduling tests.

## Verification

After approval and implementation:

1. Run `python -m unittest discover -s backend/tests -p "test_config.py"`.
2. Run `python -m unittest discover -s backend/tests -p "test_io.py"`.
3. Run `python -m unittest discover -s backend/tests`.
4. Review the diff to confirm there is no positional default GPIO assignment or inferred alarm key routing in the implementation.
5. Confirm existing `config.json` loads unchanged, its effective GPIO assignments remain identical, and incomplete hardware configurations still fail validation.
6. Report any unavailable test dependencies. Mock-based tests do not establish physical wiring correctness; no physical GPIO activation is part of this task.

## Acceptance Criteria

- A programmer can identify and edit each default pin on a single clearly labeled dictionary line.
- Each channel's input/output/sensor role is explicit.
- Pin assignment and IO routing no longer rely on matching tuple positions or string naming conventions.
- Current defaults and configuration contracts are unchanged.
- Named overrides reach the correct devices, and backend regression tests pass.
