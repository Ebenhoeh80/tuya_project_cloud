# Architektur `tuya_project_cloud` (Stand 2026-11-27)

[English](architektur.en.md)

## 1. Ziel und Scope

Home-Assistant-Custom-Integration, die **ausschließlich die Tuya OpenAPI** mit Access ID + Access Secret nutzt. Kein Smart-Life-App-Login, kein User Code, kein QR-Scan, kein Passwort.

**Bewiesener Scope (Live 2026-11-27):** Geräte, die über `GET /v1.0/iot-01/associated-users/devices` mit dem Projekt-Token sichtbar sind. Lesen und Steuern über `GET/POST /v1.0/devices/...` sind mit dem Projekt-Token verifiziert. Ergänzt: IoT-Core-Shadow (`GET /v2.0/cloud/thing/{id}/shadow/properties`, 23 DPS-Werte) und Stream-Allokation (`POST /v1.0/devices/{id}/stream/actions/allocate`, HLS).

**Nicht im Scope:** Geräte ohne App-Konto-Verknüpfung (unsichtbar), `iot-03`-Familie ( für dieses Projekt nicht autorisiert), LAN/local_key, Pulsar-Push (spätere Phase).

## 2. Entscheidungen

| Entscheidung | Begründung |
|---|---|
| Eigener.async API-Client (`aiohttp`) statt `tuya-connector-python` | Das offizielle SDK ist sync (2021), nutzt `requests` und damit Executor-Threads. Die Signatur ist stabil und klein; ein eigener Async-Client vermeidet Blocking und gibt volle Kontrolle über Timeouts, Redaction und Fehler. HA-seitig werden dennoch bestehende Patterns wiederverwendet. |
| Nur `v1.0/devices` + `v1.0/iot-01/associated-users` | Live bewiesen. `iot-03` liefert `28841105 no permissions`. |
| `DataUpdateCoordinator` (Polling) | Kein Push-Kanal im Projekt-only-Modus. Coordinator ist der HA-Standard für Polling und liefert `available`, `last_update_success`, Repairs-Integration. |
| `entry.runtime_data` | Aktueller HA-Standard, kein globals `hass.data`. |
| Dynamische Entitäten aus `functions` + `status` | Geräte sind produktspezifisch; keine feste DPS-Tabelle. Entity-Descriptions pro Plattform mit Code→Entity-Mapping. |
| Repair-Issues für Auth/Region/API-Autorisierung | Nutzer-korrigierbare Zustände (falsche Region, fehlende API-Freischaltung) gehören in den Repair Registry. |
| Diagnostics mit Redaction | Tokens, Secrets und personenbezogene DPS-Werte dürfen nie in Diagnostics erscheinen. |
| IoT-Core-Shadow für Laderdaten | Die klassischen `/status`, `/functions` und `/specifications` liefern beim Charger keine Werte; nur der Thing-Shadow ist autorisiert und liefert 23 DPS. |
| Flache Sensoren statt JSON-Attribute | `x_metrics` und `x_charger_info` werden in `shadow.py` zerlegt, skaliert und als eigene Sensoren mit `device_class`/Einheit/`state_class` abgebildet. |
| Kamera mit frischer HLS-URL | `stream_source()` allokiert pro Streamstart neu; die URL bleibt nur im Speicher und nie in State/Attributen/Recorder. HA's `Camera.async_create_stream()` liefert das Lock. |
| `OptionsFlowWithReload` | Shadow- und Kamera-Optionen erfordern einen Neuaufbau der Plattformen; HA lädt den Entry nach dem Speichern automatisch neu. |

## 3. Datenfluss

```
Config Flow (access_id, access_secret, region)
        │
        ▼
  TuyaOpenApi (async, HMAC-SHA256, Token-Refresh)
        │
        ├─ GET /v1.0/token?grant_type=1
        ├─ GET /v1.0/iot-01/associated-users/devices  → Geräteliste
        ├─ GET /v1.0/devices/{id}/functions           → Command-Vokabular
        ├─ GET /v1.0/devices/{id}/status              → DPS-Werte
        ├─ GET /v1.0/devices/{id}/specifications      → Typen/Constraints
        ├─ POST /v1.0/devices/{id}/commands           → Steuerung
        ├─ GET /v2.0/cloud/thing/{id}/shadow/properties → Laderdaten (einmal pro Gerät)
        └─ POST /v1.0/devices/{id}/stream/actions/allocate → kurzlebige HLS-URL
        │
        ▼
  TuyaProjectCloudCoordinator (DataUpdateCoordinator)
        │  async_config_entry_first_refresh
        ▼
  Plattformen: switch | sensor | light | climate | cover | number | camera
        │  Entity-Description: dps_code oder shadow_code → HA-Entity
        ▼
  Diagnostics / Repairs
```

## 4. Module

| Datei | Verantwortung |
|---|---|
| `const.py` | Domain, Konfigurationsschlüssel, Regions→Base-URL, DPS-Code-Konstanten, Plattformen |
| `api.py` | `TuyaOpenApi`: Signatur, Token, Geräteliste, Status, Functions, Specifications, Commands, Thing-Shadow, Stream-Allokation. Eigene Fehlerklassen. |
| `shadow.py` | `ShadowSensorDescription`, Mapping der 16 Lader-Sensoren, JSON-Zerlegung und Skalierung |
| `config_flow.py` | `user`-Step (ID, Secret, Region), Duplikatprüfung, `reauth`, Options (Intervall, Shadow, Kamera) mit Reload |
| `coordinator.py` | `DataUpdateCoordinator[dict[str, TuyaDevice]]`, Geräte-Mapping, Shadow-Cache, Fehler→Repairs/Reauth |
| `entity.py` | `TuyaProjectCloudEntity` (DPS) und `TuyaShadowEntity` (Shadow): `device_info`, `unique_id`, `available` |
| `switch.py`, `sensor.py`, `light.py`, `climate.py`, `cover.py`, `number.py`, `camera.py` | Dynamische Entitäten aus DPS- und Shadow-Codes bzw. HLS-Stream |
| `diagnostics.py` | Redaction von Token/Secret/`local_key`/Stream-URL/`m3u8`; nur Shadow-Codes, keine Werte |
| `repairs.py` | Auth-, Region-, API- und IoT-Core-Autorisierungs-Issues |
| `strings.json`, `translations/{de,en}.json` | UI-Texte und Repair-Beschreibungen |

## 5. Datenmodell

```python
@dataclass
class TuyaFunction:
    code: str
    type: str  # Boolean, Integer, Enum, String, Json
    values: dict  # min/max/step/scale oder Enum-Ranges


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
    uid: str  # App-Account-UID, nicht ausgeben
    owner_id: str  # Home-ID, nicht ausgeben
    status: dict[str, Any]  # code → value
    functions: dict[str, TuyaFunction]
    specifications: dict[str, TuyaFunction]
    shadow: dict[str, TuyaShadowProperty]  # IoT-Core-Thing-Shadow
```

`local_key` wird bewusst **nicht** gespeichert – die Integration ist Cloud-only.

## 6. Entity-Mapping (erste Iteration)

| Plattform | Erkennung über DPS-Code / Kategorie |
|---|---|
| switch | Boolean-Functions mit `switch`/`onoff`/`power`/`enable` im Code |
| sensor | Status-Codes ohne Function (Read-only), z. B. `battery`, `temperature`, `humidity`, `motion_record` |
| light | `switch_led`, `bright_value`, `colour_data`, `temp_value` |
| climate | `temp_set`, `mode`, `fan_speed`, `windspeed`, Kategorie `kt` |
| cover | `control`, `percent_control`, `position`, Kategorie `cl`/`curtain` |
| number | Integer-Functions mit `min`/`max`/`step`, die nicht bereits zu light/climate/cover gehören |
| sensor (Shadow) | Geräte mit `x_work_state`, `x_metrics`, `x_charger_info` o. ä.; 16 gemappte Sensoren mit `shadow_`-Präfix in der Unique-ID |
| camera | Kategorie `sp` oder Functions mit `stream`; HLS über `stream_source()` |

Skalierung `(unbelegt im Detail)`: Spannung/Strom/Leistung/Energie aus `x_metrics` ×0,1, `x_charger_info.e` ×0,1; Zeiten und Rohzähler mit unklarer Einheit werden nicht abgebildet. Lesbare Status-Codes mit passenden Hinweisen (`battery`, `temperature`, `humidity`, …) werden als `sensor` mit `EntityCategory.DIAGNOSTIC` erzeugt. Völlig unbekannte Codes werden nicht geraten und nicht gesteuert.

## 7. Fehler- und Reauth-Strategie

| Fehler | Reaktion |
|---|---|
| `sign invalid`, `1004`, `1005`, 401 | `ConfigEntryAuthFailed` aus Setup **oder Coordinator** → Reauth-Flow |
| `28841105` (API nicht autorisiert) | Repair-Issue „api_not_authorized", Entitäten trotzdem aus Status, keine Commands |
| `28841105` auf Thing-Shadow | Repair-Issue „iot_core_not_authorized", übrige Sensoren bleiben verfügbar |
| `1106 illegal permission` | Repair-Issue „command_not_authorized", Command deaktiviert |
| Timeout / 5xx / 429 | `ConfigEntryNotReady` beim Setup, `UpdateFailed` im Coordinator, Backoff |
| Falsche Region → leere Liste | Repair-Issue „region_mismatch" |
| Stream-Allokation fehlgeschlagen | `stream_source()` liefert `None`; Setup und andere Entitäten bleiben gesund |

## 8. Tests

- `tests/test_api.py`: Signatur-Vektoren, Token-Refresh, Fehlerklassen, Shadow-Mapping, Stream-Allokation.
- `tests/test_config_flow.py`: user/reauth/duplicate, Options inkl. Shadow/Kamera.
- `tests/test_coordinator.py`: Geräte-Mapping, Auth→Reauth, Shadow-Cache, IoT-Core-Autorisierung.
- `tests/test_init.py`: Setup/Unload, `runtime_data`, Forwarding der `camera`-Plattform.
- `tests/test_entities.py`: DPS- und Shadow→Entity-Mapping.
- `tests/test_camera.py`: frische HLS-URL, Offline-Fall, Option, Stream-Fehler.
- `tests/test_diagnostics.py`: Redaction inkl. Stream-URL/`m3u8`, nur Shadow-Codes im Output.

Ist: 47 Tests grün, `ruff check` und `ruff format --check` sauber (WSL, Python 3.13). `pytest.ini` setzt `asyncio_mode = auto`. Die Kamera-Tests benötigen zusätzlich `PyTurboJPEG`, weil HA `homeassistant.components.camera` importiert.

## 9. Iterationsplan

1. **Iteration A:** `const.py`, `api.py`, `config_flow.py`, `coordinator.py`, `__init__.py`, `manifest.json`, `strings.json`,translations – plus API/Config-Flow/Coordinator-Tests.
2. **Iteration B:** `entity.py` + `switch.py`, `sensor.py`, `number.py` – plus Entity-Tests.
3. **Iteration C:** `light.py`, `climate.py`, `cover.py` – plus Tests.
4. **Iteration D:** `diagnostics.py`, `repairs.py` – plus Redaction-/Repairs-Tests. ✅ abgeschlossen
5. **Iteration E:** README de/en, `hacs.json`, `pytest.ini`, `requirements_test.txt`, Changelog de/en, Architektur/Machbarkeit de/en. ✅ abgeschlossen
6. **Iteration F:** Shadow-Client, `shadow.py`, `camera.py`, Optionen, Redaction, de/en-Doku gemäß Ausbauplan. ✅ abgeschlossen
7. **Iteration G:** Live-Probe der neuen Client-Methoden (8 Geräte, 23 Shadow-Properties, HLS-Allokation) ohne Geheimnisausgabe. ✅ abgeschlossen

Nach jeder Iteration: Annahmen dokumentieren, Tests verifizieren, Architektur anpassen. Ein Einsatz in einer laufenden HA-Instanz folgt erst nach Freigabe.
