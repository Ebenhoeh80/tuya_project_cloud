# Architecture `tuya_project_cloud` (as of 2026-11-27)

[Deutsch](architektur.md)

## 1. Goal and scope

Home Assistant custom integration that uses **exclusively the Tuya OpenAPI** with Access ID + Access Secret. No Smart Life app login, no user code, no QR scan, no password.

**Proven scope (live 2026-11-27):** Devices visible via `GET /v1.0/iot-01/associated-users/devices` with the project token. Reading and controlling via `GET/POST /v1.0/devices/...` are verified with the project token. Added: IoT Core thing shadow (`GET /v2.0/cloud/thing/{id}/shadow/properties`, 23 DPS values) and stream allocation (`POST /v1.0/devices/{id}/stream/actions/allocate`, HLS).

**Out of scope:** Devices without app account linking (invisible), `iot-03` family (not authorized for this project), LAN/local_key, Pulsar push (later phase).

## 2. Decisions

| Decision | Reason |
|---|---|
| Own async API client (`aiohttp`) instead of `tuya-connector-python` | The official SDK is sync (2021), uses `requests` and thus executor threads. The signature is stable and small; an own async client avoids blocking and gives full control over timeouts, redaction and errors. HA patterns are still reused. |
| Only `v1.0/devices` + `v1.0/iot-01/associated-users` | Proven live. `iot-03` returns `28841105 no permissions`. |
| `DataUpdateCoordinator` (polling) | No push channel in project-only mode. Coordinator is the HA standard for polling and provides `available`, `last_update_success`, repairs integration. |
| `entry.runtime_data` | Current HA standard, no global `hass.data`. |
| Dynamic entities from `functions` + `status` | Devices are product-specific; no fixed DPS table. Entity descriptions per platform with code→entity mapping. |
| Repair issues for auth/region/API authorization | User-correctable states (wrong region, missing API authorization) belong in the repair registry. |
| Diagnostics with redaction | Tokens, secrets and personal DPS values must never appear in diagnostics. |
| IoT Core thing shadow for charger data | The classic `/status`, `/functions` and `/specifications` return no values for the charger; only the thing shadow is authorized and returns 23 DPS. |
| Flat sensors instead of JSON attributes | `x_metrics` and `x_charger_info` are split in `shadow.py`, scaled and exposed as separate sensors with `device_class`/unit/`state_class`. |
| Camera with a fresh HLS URL | `stream_source()` allocates a new URL per stream start; the URL stays in memory only and never in state/attributes/recorder. HA's `Camera.async_create_stream()` provides the lock. |
| `OptionsFlowWithReload` | Shadow and camera options require rebuilding platforms; HA reloads the entry after saving. |

## 3. Data flow

```
Config flow (access_id, access_secret, region)
        │
        ▼
  TuyaOpenApi (async, HMAC-SHA256, token refresh)
        │
        ├─ GET /v1.0/token?grant_type=1
        ├─ GET /v1.0/iot-01/associated-users/devices  → device list
        ├─ GET /v1.0/devices/{id}/functions           → command vocabulary
        ├─ GET /v1.0/devices/{id}/status              → DPS values
        ├─ GET /v1.0/devices/{id}/specifications      → types/constraints
        ├─ POST /v1.0/devices/{id}/commands           → control
        ├─ GET /v2.0/cloud/thing/{id}/shadow/properties → charger data (once per device)
        └─ POST /v1.0/devices/{id}/stream/actions/allocate → short-lived HLS URL
        │
        ▼
  TuyaProjectCloudCoordinator (DataUpdateCoordinator)
        │  async_config_entry_first_refresh
        ▼
  Platforms: switch | sensor | light | climate | cover | number | camera
        │  entity description: dps_code or shadow_code → HA entity
        ▼
  Diagnostics / repairs
```

## 4. Modules

| File | Responsibility |
|---|---|
| `const.py` | Domain, configuration keys, regions→base URLs, DPS code constants, platforms |
| `api.py` | `TuyaOpenApi`: signature, token, device list, status, functions, specifications, commands, thing shadow, stream allocation. Own error classes. |
| `shadow.py` | `ShadowSensorDescription`, mapping of 16 charger sensors, JSON flattening and scaling |
| `config_flow.py` | `user` step (ID, secret, region), duplicate check, `reauth`, options (interval, shadow, camera) with reload |
| `coordinator.py` | `DataUpdateCoordinator[dict[str, TuyaDevice]]`, device mapping, shadow cache, errors→repairs/reauth |
| `entity.py` | `TuyaProjectCloudEntity` (DPS) and `TuyaShadowEntity` (shadow): `device_info`, `unique_id`, `available` |
| `switch.py`, `sensor.py`, `light.py`, `climate.py`, `cover.py`, `number.py`, `camera.py` | Dynamic entities from DPS and shadow codes or HLS stream |
| `diagnostics.py` | Redaction of token/secret/`local_key`/stream URL/`m3u8`; shadow codes only, no values |
| `repairs.py` | Auth, region, API and IoT Core authorization issues |
| `strings.json`, `translations/{de,en}.json` | UI texts and repair descriptions |

## 5. Data model

```python
@dataclass
class TuyaFunction:
    code: str
    type: str  # Boolean, Integer, Enum, String, Json
    values: dict  # min/max/step/scale or enum ranges


@dataclass
class TuyaShadowProperty:
    code: str
    value: Any = None
    dp_id: int | None = None
    time: int | None = None


@dataclass
class TuyaDevice:
    id: str
    name: str
    category: str
    product_id: str
    online: bool
    uid: str  # app account UID, not printed
    owner_id: str  # home ID, not printed
    status: dict[str, Any]  # code → value
    functions: dict[str, TuyaFunction]
    specifications: dict[str, TuyaFunction]
    shadow: dict[str, TuyaShadowProperty]  # IoT Core thing shadow
```

`local_key` is deliberately **not** stored – the integration is cloud-only.

## 6. Entity mapping (first iteration)

| Platform | Detection via DPS code / category |
|---|---|
| switch | Boolean functions with `switch`/`onoff`/`power`/`enable` in the code |
| sensor | Status codes without function (read-only), e.g. `battery`, `temperature`, `humidity`, `motion_record` |
| light | `switch_led`, `bright_value`, `colour_data`, `temp_value` |
| climate | `temp_set`, `mode`, `fan_speed`, `windspeed`, category `kt` |
| cover | `control`, `percent_control`, `position`, category `cl`/`curtain` |
| number | Integer functions with `min`/`max`/`step` not already used by light/climate/cover |
| sensor (shadow) | Devices with `x_work_state`, `x_metrics`, `x_charger_info` etc.; 16 mapped sensors with a `shadow_` prefix in the unique ID |
| camera | Category `sp` or functions containing `stream`; HLS via `stream_source()` |

Scaling `(unverified in detail)`: voltage/current/power/energy from `x_metrics` ×0.1, `x_charger_info.e` ×0.1; durations and raw counters with ambiguous units are omitted. Readable status codes with matching hints (`battery`, `temperature`, `humidity`, …) are created as `sensor` with `EntityCategory.DIAGNOSTIC`. Completely unknown codes are neither guessed nor controlled.

## 7. Error and reauth strategy

| Error | Reaction |
|---|---|
| `sign invalid`, `1004`, `1005`, 401 | `ConfigEntryAuthFailed` from setup **or coordinator** → reauth flow |
| `28841105` (API not authorized) | Repair issue "api_not_authorized", entities still from status, no commands |
| `28841105` on thing shadow | Repair issue "iot_core_not_authorized", remaining sensors stay available |
| `1106 illegal permission` | Repair issue "command_not_authorized", command disabled |
| Timeout / 5xx / 429 | `ConfigEntryNotReady` at setup, `UpdateFailed` in coordinator, backoff |
| Wrong region → empty list | Repair issue "region_mismatch" |
| Stream allocation failed | `stream_source()` returns `None`; setup and other entities stay healthy |

## 8. Tests

- `tests/test_api.py`: signature vectors, token refresh, error classes, shadow mapping, stream allocation.
- `tests/test_config_flow.py`: user/reauth/duplicate, options including shadow/camera.
- `tests/test_coordinator.py`: device mapping, auth→reauth, shadow cache, IoT Core authorization.
- `tests/test_init.py`: setup/unload, `runtime_data`, forwarding of the `camera` platform.
- `tests/test_entities.py`: DPS and shadow→entity mapping.
- `tests/test_camera.py`: fresh HLS URL, offline case, option, stream error.
- `tests/test_diagnostics.py`: redaction including stream URL/`m3u8`, shadow codes only in output.

Current state: 47 tests green, `ruff check` and `ruff format --check` clean (WSL, Python 3.13). `pytest.ini` sets `asyncio_mode = auto`. Camera tests additionally need `PyTurboJPEG` because HA imports `homeassistant.components.camera`.

## 9. Iteration plan

1. **Iteration A:** `const.py`, `api.py`, `config_flow.py`, `coordinator.py`, `__init__.py`, `manifest.json`, `strings.json`, translations – plus API/config-flow/coordinator tests.
2. **Iteration B:** `entity.py` + `switch.py`, `sensor.py`, `number.py` – plus entity tests.
3. **Iteration C:** `light.py`, `climate.py`, `cover.py` – plus tests.
4. **Iteration D:** `diagnostics.py`, `repairs.py` – plus redaction/repairs tests. ✅ complete
5. **Iteration E:** README de/en, `hacs.json`, `pytest.ini`, `requirements_test.txt`, changelog de/en, architecture/feasibility de/en. ✅ complete
6. **Iteration F:** Shadow client, `shadow.py`, `camera.py`, options, redaction, de/en docs per expansion plan. ✅ complete
7. **Iteration G:** Live probe of the new client methods (8 devices, 23 shadow properties, HLS allocation) without secret output. ✅ complete

After each iteration: document assumptions, verify tests, adjust architecture. Deployment into a running HA instance follows only after approval.
