# Changelog / Änderungen

## [0.2.2] - 2026-11-27

### Deutsch

- Live-Fix: Tuya liefert `values` von Integer-Funktionen teilweise als JSON-String. Der Client normalisiert solche Werte jetzt zu einem Dictionary; die `number`-Plattform überspringt ungültige oder unvollständige Bereiche statt beim Setup abzubrechen.
- Zwei neue Regressionstests (JSON-String-Normalisierung und robustes Number-Setup); insgesamt 49 Tests grün, Ruff sauber.
- Version und Dokumentation auf 0.2.2 nachgezogen.

### English

- Live fix: Tuya sometimes returns integer function `values` as a JSON string. The client now normalizes such values into a dictionary; the `number` platform skips invalid or incomplete ranges instead of failing setup.
- Two new regression tests (JSON-string normalization and robust number setup); 49 tests passing, Ruff clean.
- Version and documentation updated to 0.2.2.

---

## [0.2.1] - 2026-11-27

### Deutsch

- CI: Der Autostart der Reauth-Flows wird im Auth-Fehler-Test während der Teardown-Phase unterdrückt; damit laufen alle 47 Tests auch auf dem GitHub-Runner sauber.
- HACS-Metadaten: Repository-Topics und eigene Brand-Assets (`icon.png`, `icon@2x.png`) ergänzt; die HACS-Validierung ist damit vollständig grün.
- Dokumentation und Version auf 0.2.1 nachgezogen.

### English

- CI: The automatic reauth flow is suppressed during teardown of the auth-failure test, so all 47 tests also pass on the GitHub runner.
- HACS metadata: repository topics and local brand assets (`icon.png`, `icon@2x.png`) added; HACS validation is now fully green.
- Documentation and version updated to 0.2.1.

---

## [0.2.0] - 2026-11-27

### Deutsch

- Thing-Shadow-Client (`GET /v2.0/cloud/thing/{id}/shadow/properties`) mit 16 flachen Lader-Sensoren für Spannung, Strom, Leistung, Energie, Ladestrom und Firmware.
- `camera`-Plattform mit kurzlebigen HLS-URLs aus `POST /v1.0/devices/{id}/stream/actions/allocate`; keine URL in State, Attributen, Logs, Recorder oder Diagnostics.
- Coordinator lädt Shadow-Daten einmal pro Gerät, meldet fehlende IoT-Core-Autorisierung als Repair und startet bei Auth-Fehlern den Reauth-Flow.
- Optionen für Shadow und Kamera; `OptionsFlowWithReload` lädt den Eintrag nach dem Speichern neu.
- Redaction um `stream_url`, `url`, `m3u8` und `token` erweitert; Diagnostics enthalten nur Shadow-Codes, keine Werte.
- 47 Tests grün, Ruff-Prüfung und Formatierung sauber, Live-Probe mit 8 Geräten und 23 Shadow-Properties erfolgreich.
- Testabhängigkeit `PyTurboJPEG` ergänzt: HA importiert `turbojpeg` beim Laden der Kamera-Plattform.

### English

- Thing shadow client (`GET /v2.0/cloud/thing/{id}/shadow/properties`) with 16 flat charger sensors for voltage, current, power, energy, charge current and firmware.
- `camera` platform using short-lived HLS URLs from `POST /v1.0/devices/{id}/stream/actions/allocate`; no URL in state, attributes, logs, recorder or diagnostics.
- Coordinator loads shadow data once per device, reports missing IoT Core authorization as a repair and starts reauth on authentication failures.
- Options for shadow data and camera; `OptionsFlowWithReload` reloads the entry after saving.
- Redaction extended to `stream_url`, `url`, `m3u8` and `token`; diagnostics contain shadow codes only, not values.
- 47 tests passing, Ruff check and format clean, live probe with 8 devices and 23 shadow properties successful.
- Added test dependency `PyTurboJPEG`: HA imports `turbojpeg` when loading the camera platform.

---

## [0.1.0] - 2026-11-27

### Deutsch

- Live-Machbarkeitsbeweis für reinen Projekt-Token (Access ID/Secret) ohne App-Login.
- Config Flow mit Access ID, Access Secret und Region; Reauth und Intervall-Optionen.
- Async OpenAPI-Client mit HMAC-SHA256, Token-Cache und Fehlerklassen.
- `DataUpdateCoordinator` für Geräteliste, Status, Funktionen und Spezifikationen.
- Dynamische Entitäten: Switch, Sensor, Number, Light, Climate, Cover.
- Diagnostics mit Redaction und Repairs für API-/Regionsprobleme.
- Unit-Tests und Dokumentation (de/en).

### English

- Live feasibility proof for project token only (Access ID/Secret), no app login.
- Config flow with Access ID, Access Secret and region; reauth and interval options.
- Async OpenAPI client with HMAC-SHA256, token cache and error classes.
- `DataUpdateCoordinator` for device list, status, functions and specifications.
- Dynamic entities: switch, sensor, number, light, climate, cover.
- Diagnostics with redaction and repairs for API/region problems.
- Unit tests and documentation (de/en).
