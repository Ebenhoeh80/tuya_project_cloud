# Tuya Project Cloud for Home Assistant

[Deutsch](README.md)

A Home Assistant custom integration that controls devices **exclusively through the Tuya OpenAPI** using your own cloud project (Access ID + Access Secret). **No app login, app password, QR code or user token at runtime.** The app account is linked once in the Tuya console so that its devices become visible in the OpenAPI.

## Status

Feasibility proven live on 2026-11-27: token, device list, status, functions and an idempotent command (`POST /v1.0/devices/{id}/commands`) all work with the project token alone. Also implemented live: the `dé EV Charger` returns 23 DPS values via the IoT Core thing shadow, mapped to 16 sensors; the door viewer delivers a short-lived HLS live stream via `stream/actions/allocate`. See the [feasibility report](docs/machbarkeit.en.md), sections 10 and 11.

State 0.3.0: 168 tests passing, Ruff clean, minimum Home Assistant version 2025.8.0. Live view now runs through a local HLS reverse proxy with a stable `index.m3u8` for HA and go2rtc; signed Tuya URLs, AES keys and segments stay internal and are renewed transparently. The installation is live-verified for 0.3.0 as well: HACS upgrade, confirmed restart and 13/13 checks green – 8 devices, 85/85 unchanged entity IDs and unique IDs compared with 0.2.8, config entry `loaded`, both cameras with `STREAM`, 0 `unavailable`, 0 `unknown`, 0 repairs, no new stream errors. Two 10-minute soaks across the full resource lifetime ran without errors; active frontend playback remains `(unverified)`. 0.2.6 fixes the `dé EV Charger` being shown as unavailable despite fresh IoT Core shadow values: Tuya rejects the legacy `status`/`functions` endpoints for this device (errno `2003`/`2009`), so shadow sensors now derive their availability from the actual shadow data. Existing entity IDs, automations and configurations remain unchanged.

## Prerequisites

- Home Assistant 2025.8.0 or newer (required by `OptionsFlowWithReload`).

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
| Sensor | Read-only status codes such as `battery`, `temperature`, `humidity`, …; four verified integer measurement codes with `scale` from the specifications and fixed units/classes |
| Number | Integer functions with `min`/`max`/`step` |
| Light | `switch_led`/`led_switch`, optional `bright_value` |
| Climate | Category `kt`/`ykq`/`hvac` or `temp_set` |
| Cover | Category `cl`/`curtain`/`jc` or `control`/`position` |
| Sensor (shadow) | Devices with IoT Core `x_*` properties: work state, voltages, currents, power, energy, charge current, firmware; new sensors appear as soon as data arrives |
| Camera | Category `sp` or functions containing `stream`: HLS live view |

Unknown codes are neither guessed nor controlled. For the four verified integer measurement codes `cur_power`, `cur_voltage`, `cur_current` and `add_ele`, the integration takes `scale` from the device specifications and uses fixed, live-confirmed units plus matching device/state classes – like the original `tuya` integration, but without a fixed scaling factor. The interpretation is captured at setup; specification changes take effect only after a reload. All other DPS values remain explicitly raw. For the charger only observed shadow values with plausible scaling are mapped; ambiguous durations and raw counters are omitted. No write commands are sent to the wallbox.

## Technical limits

- Cloud polling only (`cloud_polling`), no LAN, no `local_key`, no Pulsar push (currently).
- The `iot-03` endpoint family is deliberately unused; it is not authorized for the tested project (`28841105`).
- Devices must be visible in the project via "Link App Account".
- Tuya rate limits apply per project (e.g. commands ~4/s).
- Diagnostics redact tokens, secrets, `local_key`, UID, location data, stream URLs and `m3u8`; device IDs are pseudonymized.
- Live view runs as a `camera` platform using HLS through a local reverse proxy: HA and go2rtc only see a stable local `index.m3u8`, while the proxy keeps and renews signed URLs, AES keys and segments in memory. The integration does not write these values to state, attributes, its own logs, recorder or diagnostics. When HA's stream worker reports an unusable source, the proxy allocation is dropped and `Stream.update_source()` is called with the same local URL (10 s minimum interval). The 144-bit path token is opaque and contains no Tuya secrets, but it grants access to the live stream and should not be shared publicly. WebRTC is not offered (`device not supports`).
- DPS scaling follows `value / 10**scale` with `scale` from the device's specifications; units and classes of the four verified codes are fixed. Without a reliable specification the raw value stays visible.
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
