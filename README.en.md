# Tuya Project Cloud for Home Assistant

[Deutsch](README.md)

A Home Assistant custom integration that controls devices **exclusively through the Tuya OpenAPI** using your own cloud project (Access ID + Access Secret). **No app login, app password, QR code or user token at runtime.** The app account is linked once in the Tuya console so that its devices become visible in the OpenAPI.

## Status

Feasibility proven live on 2026-11-27: token, device list, status, functions and an idempotent command (`POST /v1.0/devices/{id}/commands`) all work with the project token alone. Also implemented live: the `dé EV Charger` returns 23 DPS values via the IoT Core thing shadow, mapped to 16 sensors; the door viewer delivers a short-lived HLS live stream via `stream/actions/allocate`. See the [feasibility report](docs/machbarkeit.en.md), sections 10 and 11.

State 0.2.4: 81 tests passing, Ruff clean, HACS/Hassfest validation last green for 0.2.3. The live installation with 8 devices, 16 charger sensors and HLS camera is verified for 0.2.3; 0.2.4 will be checked against that baseline after release.

## Prerequisites

1. Create a Tuya IoT project in the [Tuya Developer Console](https://platform.tuya.com/).
2. Note the Access ID and Access Secret.
3. Use **Link App Account** in the console and confirm with the Smart Life / Tuya app QR code. The app account's devices then appear in the project.
4. Authorize the Device API under **Service API → Add Authorization**. Without it, Tuya responds with `28841105`.
5. For charger data, enable IoT Core and authorize the cloud project; otherwise the thing shadow API denies access.

> No app login is needed at runtime. Linking an app account once in the Tuya console is still required for devices to appear in the OpenAPI. Devices without that link are invisible to every cloud project.

## Installation

1. HACS → Integrations → add custom repository.
2. Repository `Ebenhoeh80/tuya_project_cloud`, category `Integration`.
3. Install "Tuya Project Cloud" and restart Home Assistant.
4. Settings → Devices & Services → Add Integration → "Tuya Project Cloud".
5. Enter Access ID, Access Secret and region.

Alternatively copy `custom_components/tuya_project_cloud` to `/config/custom_components/`.

## Configuration

| Field | Meaning |
|---|---|
| Access ID | Client ID of the Tuya project |
| Access Secret | Client secret of the Tuya project |
| Region | `cn`, `us`, `us_east`, `eu`, `eu_west`, `in`, `sg` |

The options cover the polling interval (10–900 s, default 30 s), reading IoT Core shadow data and the camera platform. Charger values refresh once per minute; an empty response is retried immediately. Saving options reloads the entry.

## Supported entities

Entities are generated dynamically from each device's DPS functions and status codes:

| Platform | Detection |
|---|---|
| Switch | Functions with `switch`, `onoff`, `power`, `enable`, …; Boolean and existing Enum/Integer/String codes are retained, light codes are excluded |
| Sensor | Read-only status codes such as `battery`, `temperature`, `humidity`, … |
| Number | Integer functions with `min`/`max`/`step` |
| Light | `switch_led`/`led_switch`, optional `bright_value` |
| Climate | Category `kt`/`ykq`/`hvac` or `temp_set` |
| Cover | Category `cl`/`curtain`/`jc` or `control`/`position` |
| Sensor (shadow) | Devices with IoT Core `x_*` properties: work state, voltages, currents, power, energy, charge current, firmware; new sensors appear as soon as data arrives |
| Camera | Category `sp` or functions containing `stream`: HLS live view |

Unknown codes are neither guessed nor controlled. For the charger only observed values with plausible scaling are mapped; ambiguous durations and raw counters are omitted. No write commands are sent to the wallbox.

## Technical limits

- Cloud polling only (`cloud_polling`), no LAN, no `local_key`, no Pulsar push (currently).
- The `iot-03` endpoint family is deliberately unused; it is not authorized for the tested project (`28841105`).
- Devices must be visible in the project via "Link App Account".
- Tuya rate limits apply per project (e.g. commands ~4/s).
- Diagnostics redact tokens, secrets, `local_key`, UID, location data, stream URLs and `m3u8`; device IDs are pseudonymized.
- Live view runs as a `camera` platform using HLS; the signed URL is allocated anew for each stream start, kept only in memory and never written to state, attributes, logs, recorder or diagnostics. WebRTC is not offered (`device not supports`).
- Scaling of `x_*` values comes from community references, not from the manufacturer; `(unverified)`.

## Development

```bash
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements_test.txt
.venv\Scripts\pytest tests/
```

Architecture and assumptions (each de/en): [docs/architektur.md](docs/architektur.md) / [docs/architektur.en.md](docs/architektur.en.md), [docs/machbarkeit.md](docs/machbarkeit.md) / [docs/machbarkeit.en.md](docs/machbarkeit.en.md), [docs/api-testplan.md](docs/api-testplan.md) / [docs/api-testplan.en.md](docs/api-testplan.en.md).

## License

MIT
