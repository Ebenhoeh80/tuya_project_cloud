# Feasibility: `tuya_project_cloud` (as of 2026-11-27)

[Deutsch](machbarkeit.md)

Status: **Phase 0/1 complete – live proof provided, implementation released.**

## 1. Important rule and compliance

> Do not code before proving that the Tuya OpenAPI allows the required device access without a Smart Life user account concept.

This rule was followed. Initially only research and documentation were done – **without any implementation code**. The credentials were later located in the Bitwarden item `Credential_Tuya_AccessID` (see `SecondBrain/wiki/konzepte/zugangsdaten-fundorte.md`) and used specifically for the live tests (values only in process, never printed or stored). Code was created only after the successful control proof (section 8).

## 2. Key finding

The goal is **not universally feasible**, but only with a clear constraint:

| Device origin | Project token (`grant_type=1`) without app login | Assessment |
|---|---|---|
| Devices created/activated in the **own cloud project** (e.g. virtual device, Tuya Spatial / Smart Industry) | Read **and** control possible per docs | Feasible |
| Existing **Smart Life / Tuya app devices** linked via "Link App Account" | Reading via `associated-users/devices` proven; **control is disputed in documentation** and depends on the permission package/token context | Not proven without live test |
| Devices only in an app account (not linked) | Not visible | Not feasible |

**Critical contradiction in the official docs:**

- `Device Control Practice` / `Link Devices` say for linked devices: *"not authorized to control these linked devices, but only has permissions to view device status"*.
- `Link Devices` (another page) says: linking enables *"device control and management on the Tuya Developer Platform"*.
- HA Core's practice additionally uses a user token (`tuya_sharing`, user code + QR).

Resolution only through live test T6 (see `docs/api-testplan.en.md`).

## 3. Reuse of existing components – reviewed

| Component | Result |
|---|---|
| HA Core `tuya` (dev, 2026-11-27) | Strictly requires `user_code` + QR scan. No Access ID/Secret field. `cloud_push`, no LAN fallback. `support_local` only concerns MQTT topics (`/pen` vs `/sta`), not LAN. Dependencies: `tuya-device-sharing-sdk==0.2.15`, `tuya-device-handlers` (dev `2026.12.1`). |
| Xtend Tuya 4.5.4 | Also starts with `user_code` + QR. OpenAPI option requires **additionally** app account + password and linked app account. Project-only is not provided in the UI flow. |
| `tuya-connector-python` (official, MIT) | Uses `GET /v1.0/token?grant_type=1` – suitable for pure project token. Sync/`requests`, older (PyPI 0.1.2). Optionally includes Pulsar push. |
| `tuya-device-sharing-sdk` (official, MIT, active) | Used by HA Core; user/sharing context, not a pure project-token client. Only useful if a user-token layer is allowed. |
| `tinytuya` (community, MIT, active) | LAN + cloud, flexible DPS mapping. Cloud is a subset, not official. Good for debugging, not recommended as a core dependency. |

**Conclusion:** No existing HA component directly satisfies "project-only without app account". Reusable, however, are HA patterns (coordinator/dispatcher, entity descriptions, diagnostics, repairs) and possibly `tuya-connector-python` for signature/token.

## 4. Local evidence (not publicly reproducible)

From `SecondBrain/wiki/projekte/aosu.md` and `research_notes/AoSu OEM Pfad Risiken/technik.md` (2026-11-26):

- Project `SmartHome` (formerly `aosu-desktop-local`), region EU: token, device list with **6 devices (5 online)** and stream allocation were genuinely successful – **all devices came from Smart Life**.
- `from=sharing` returned `count=0`.
- The AoSu cameras are not in the Tuya device list; they use their own manufacturer backend (`api-eu.aosulife.com`).
- This evidence proves access to **linked Smart Life devices**, not to devices without app context and not to AoSu hardware.

## 5. Technical constraints (assets, users, homes, devices)

- **Access ID/Secret** identifies the project, not the end user.
- **Project token** (`grant_type=1`) applies to project-specific data. **User token** (`grant_type=2` / `authorized-login` / QR) applies to app account data.
- **`uid` / `open_uid`**: UID of the linked app account; not a token and alone not a control permission. Community term `open_uid`, official docs mostly say "App Account UID".
- **`owner_id`** in device records corresponds to the app account's home ID, not the project.
- **`asset_id`** is an industry asset node (tree, root `parent_asset_id=-1`), **not** the same as a smart-home `home_id`.
- **`space_id`** is the newer IoT Core structure (`/v2.0/cloud/space/...`).
- Linking does **not** transfer ownership; at most **two projects** per app/app account.
- Without linking, app devices do not appear in `/v1.0/devices` or `/v1.3/iot-03/devices`.

## 6. DPS and functions

- No universal DPS numbering; codes are product-specific.
- `functions` = possible commands, `status` = reportable states. Both must be fetched per device via `specifications`/`functions`.
- Types: `Boolean`, `Integer`, `Enum`, `Json`, `String`; `values` contains `min`, `max`, `step`, `scale` or enum ranges.
- Standard instruction sets are only a subset; empty results require a Tuya ticket.
- Rate limits (excerpt, per project): `shadow/actions` 4/s, `shadow/properties` GET 50/s, `thing/{id}/state` 5/s, `thing/batch` 4/s.

## 7. Architecture consequence (implemented, see `docs/architektur.en.md`)

The live tests showed that the `v1.0/devices` family works for linked devices. Based on that:

1. **Config flow**: Access ID, Access Secret, region. No app account, no password. An optional later step for linked devices with user context – only if the user explicitly wants it.
2. **Client**: Own async HTTP client (signature per current docs) or wrapper around `tuya-connector-python` via executor. No `tuya_sharing` in the project-only path.
3. **Data model**: `entry.runtime_data` with client + `DataUpdateCoordinator` (polling, since no push channel). Push (Pulsar) in a later phase.
4. **Entities**: Dynamic from `functions`/`status` + DPS codes. Platforms: switch, sensor, light, climate, cover, number, camera; additional shadow sensors from the IoT Core thing shadow. Entity descriptions with `device_class`, `native_unit_of_measurement`, `EntityCategory`.
5. **Device/range**: `DeviceInfo` per Tuya device, `identifiers={(DOMAIN, device_id)}`; child devices where applicable.
6. **Diagnostics/repairs**: Redaction of tokens, secrets, DPS values with personal data; repairs for auth errors, wrong region, missing API authorization.
7. **Tests**: `pytest-homeassistant-custom-component`, 0.1.0 intermediate state: 36 tests green, 84 % overall coverage; 0.2.4 state: 81 tests green, `ruff check`/`format` clean. Config flow, coordinator, entity mapping, camera, redaction, error paths.

## 8. Live proof (2026-11-27) – important rule fulfilled

Targeted retrieval of the **single** Bitwarden item `Credential_Tuya_AccessID` (vault unlocked, values only in process, never printed or stored). Real OpenAPI calls against `https://openapi.tuyaeu.com`:

| Test | Result | Proof |
|---|---|---|
| T0 `GET /v1.0/token?grant_type=1` | `success=True` | Project token without app login |
| T1 `GET /v1.3/iot-03/devices` | `success=True`, **0 devices** | No devices in the `iot-03` data area |
| T5 `GET /v1.0/iot-01/associated-users/devices` | `success=True`, **6 devices** | Linked Smart Life devices with `uid`, `owner_id`, `local_key`, `status` |
| `iot-03` status on linked device | Error `28841105` "This project is not authorized to call this API" | `iot-03` family **not authorized** for this project |
| `GET /v1.0/devices/{id}/status`, `/functions`, `/specifications` | all `success=True` | Read access to linked devices **with project token** |
| **T6 `POST /v1.0/devices/{id}/commands`** | **`success=True`**, readback `success=True` | **Control with pure project token proven** |

The command test was **idempotent**: the exact previously read value (`wireless_lowpower`, Int64) was written back unchanged, so the device state did not change. **No** app password, no user token and no QR login were used.

**Resolution of the doc contradiction:** The statement "view device status only" apparently does not apply to this project/permission package or to the `v1.0/devices` endpoint family. The concrete live finding wins. The architecture therefore uses **only** the `v1.0/devices` and `v1.0/iot-01/associated-users` families; `iot-03` is not used.

**Consequence:** The important rule is fulfilled. Implementation is released. Scope: devices of the linked app account visible via `associated-users/devices`. Devices without linking remain invisible (design limit, see section 5).

## 9. Verification of the implementation (2026-11-27)

After implementation, the **own Python client** (`custom_components/tuya_project_cloud/api.py`) was tested live against the real Tuya API again – no longer the PowerShell probe script, but the code that runs in Home Assistant:

```
T0 token=OK
T1 devices=6
DEV cat=sp functions=12 status_codes=21 specs=21
COMMON codes=12
CONTROL code=wireless_lowpower type=int success=OK
READBACK code_present=True unchanged=True
```

The command was again **idempotent** (exact read value written back). This proves **`device control and management` with the actual integration implementation**.

**Test and quality status:**

| Check | Result |
|---|---|
| Unit tests (WSL, Python 3.13, `pytest-homeassistant-custom-component`) | **81 passed** (0.2.4) |
| `ruff check` / `ruff format --check` | **All checks passed** / clean |
| Live smoke test of own client | **Success** (see above) |
| Live shadow/stream probe of own client | **Success** (8 devices, 23 DPS, HLS allocation; see section 11) |

**Goal achieved:** The integration lists devices, reads status/functions/specifications and controls devices via the Tuya OpenAPI – exclusively with Access ID + Access Secret, without Smart Life app login at runtime. The set goal is achieved.

## 10. Live-view feasibility at the door spion (2026-11-27)

Afterwards, a read-only probe checked whether the same project token can also deliver a live image. The `IoT Video Live Stream` service is authorized free of charge in the `SmartHome` project.

| Check | Result |
|---|---|
| `POST /v1.0/devices/{id}/stream/actions/allocate`, `{"type":"hls"}` | `success=True`, signed HTTPS URL, `.m3u8`, `signInfo` |
| same endpoint with `{"type":"rtsp"}` | `success=True`, `result.url` |
| `POST /v1.0/users/{uid}/devices/{id}/stream/actions/allocate` (HLS and RTSP) | both `success=True` |
| `GET /v1.0/devices/{id}/webrtc-configs` | `device not supports` |

Both stream endpoints are listed in the official User Permission Package (as of 2026-11-05). The signed URL was **neither printed nor stored**; the probe reported only success, error classes and the URL shape (scheme/port/suffix). No app password, no user token, no device modification.

**Context:** The historic HA entity `camera.turspion` delivered 404 streams and put the whole integration into `setup_error` on 2026-10-06 (ADR 0009 in the SecondBrain wiki). The original cause remains unproven; the OpenAPI now really delivers the stream with the project token. A `camera` platform is therefore feasible and **implemented in 0.2.0** (see section 11).

**Implementation:** `stream_source()` re-allocates on every start; the URL stays in-process only – never in logs, diagnostics, recorder or config entry. WebRTC is not offered; go2rtc `tuya://` is optional for two-way audio. URL lifetime and HLS stability in a real HA instance remain untested.

Evidence in the SecondBrain wiki: `wiki/fragen/2026-11-27-tuya-tuer-spion-livebild.md` (not part of this repository).

## 11. Implementation in 0.2.0: charger data and live view (2026-11-27)

After IoT Core authorization, the integration client was probed live again. Output of the secret-free probe (no device IDs, tokens or stream URLs):

```
DEVICES count=8
SHADOW count=23 mapped=16 has_sensors=True
  work_state=101
  work_state_debug='SLEEP'
  power=0.0
  charge_current=16
  firmware='2.9.3'
STREAM allocated=True m3u8_in_url=True query_keys=1
```

| Check | Result |
|---|---|
| `GET /v2.0/cloud/thing/{id}/shadow/properties` via `TuyaOpenApi.async_get_thing_shadow()` | `23` properties, `16` mapped sensors |
| `POST /v1.0/devices/{id}/stream/actions/allocate` via `TuyaOpenApi.async_allocate_stream()` | URL with `.m3u8` and signature query, memory only |
| `camera` platform | HLS via `stream_source()`, no WebRTC |
| Redaction | Stream URL and `m3u8` masked in diagnostics, `_unrecorded_attributes = frozenset(MATCH_ALL)` |

**Limits:** Scaling of `x_*` values follows community references (evcc/tuya-local), not the manufacturer `(unverified in detail)`. `d`/`t` from `x_metrics` and `x_charge_history` remain unassessed because their units are ambiguous. No write commands are sent to the wallbox. The installation in a running HA instance is verified for 0.2.4: HACS upgrade, config entry `loaded`, readback 73/73 entity IDs unchanged (0 missing, 0 new). Active HLS playback and URL renewal after expiry remain `(unverified)`.

Evidence in the SecondBrain wiki: `wiki/fragen/2026-11-27-tuya-ev-charger-werte.md`, `wiki/projekte/tuya-project-cloud-ausbauplan.md`.
