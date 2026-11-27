# Changelog / Änderungen

## [0.3.0] - 2026-11-27

### Deutsch

- Das Kamera-Livebild läuft jetzt über einen lokalen HLS-Re-Proxy. Home Assistant und go2rtc sehen pro Kamera eine stabile lokale `index.m3u8`; die kurzlebigen signierten Tuya-URLs, AES-Keys und Mediensegmente bleiben ausschließlich im Proxy-Speicher.
- Der Proxy registriert jede Kamera unter einem opaken Token, schreibt Key- und Segment-URLs auf lokale Pfade mit `.ts`/`.key` um und erneuert eine Allokation automatisch nach 120 Sekunden oder bei einer fehlgeschlagenen Playlist. Meldet der HA-Stream-Worker eine unbrauchbare Quelle, wird die Allokation verworfen und `Stream.update_source()` mit derselben lokalen URL aufgerufen. Die go2rtc-Stream-Registry muss dadurch nicht neu registriert werden.
- Stream-URLs, Tokens und AES-Keys erscheinen weiterhin nicht in State, Attributen, eigenen Logs, Recorder, Diagnostics oder Config Entry. Die lokalen Proxy-Pfade sind opak und enthalten keine Tuya-Geheimnisse; der 144-Bit-Pfad-Token wirkt aber wie ein Bearer-Zugang zum Livestream und sollte nicht öffentlich geteilt werden. Beim Entladen des Config Entries werden alle Routen entfernt. Es werden keine Geräte-Schreibbefehle eingeführt; die Wallbox bleibt read-only.
- Alle bestehenden Entity-IDs, Unique-IDs und Automationen bleiben unverändert. WebRTC wird weiterhin nicht angeboten (`device not supports`); die signierte RTSPS-Alternative lieferte in der Probe keine Frames und wird nicht verwendet.
- Qualität: 168 Tests grün, Ruff und Formatierung sauber. Eine End-to-End-Probe beider Kameras lief je 180 Sekunden über den Proxy – PyAV und ffmpeg (go2rtc-kompatibel) – ohne Fehler. Unabhängige Freigabe durch Claude Sonnet 5.5 ohne verbleibende Blocker.

### English

- Camera live view now runs through a local HLS reverse proxy. Home Assistant and go2rtc see one stable local `index.m3u8` per camera; short-lived signed Tuya URLs, AES keys and media segments stay in proxy memory only.
- The proxy registers each camera under an opaque token, rewrites key and segment URLs to local `.ts`/`.key` paths and renews an allocation after 120 seconds or when a playlist request fails. If HA's stream worker reports an unusable source, the allocation is dropped and `Stream.update_source()` is called with the same local URL. The go2rtc stream registry therefore does not need to be re-registered.
- Stream URLs, tokens and AES keys still never appear in state, attributes, integration logs, recorder, diagnostics or the config entry. The local proxy paths are opaque and contain no Tuya secrets; the 144-bit path token nevertheless acts like a bearer for the live stream and should not be shared publicly. All routes are removed when the config entry is unloaded. No device write commands are introduced; the wallbox stays read-only.
- All existing entity IDs, unique IDs and automations remain unchanged. WebRTC is still not offered (`device not supports`); the signed RTSP alternative produced no frames in the probe and is not used.
- Quality: 168 tests passing, Ruff and formatting clean. An end-to-end probe of both cameras ran for 180 seconds each through the proxy – with PyAV and ffmpeg (go2rtc-compatible) – without errors. Independent approval by Claude Sonnet 5.5 with no remaining blockers.

---

## [0.2.8] - 2026-11-27

### Deutsch

- Behebt das Problem, dass ein Kamera-Livebild nach kurzer Zeit stehen blieb und die Oberfläche danach `mpegts: wrong sync byte` sowie `DESCRIBE failed: 404` meldete. Ursache war nicht WebRTC, sondern eine abgelaufene signierte HLS-URL: Der HA-Stream-Worker retryt eine fehlgeschlagene Quelle unbegrenzt mit exakt derselben URL, ohne `stream_source()` erneut aufzurufen.
- Die Kamera verfolgt jetzt den vom HA-Stream-Worker gemeldeten Verfügbarkeitswechsel und ersetzt eine unbrauchbar gewordene Quelle über die öffentliche API `Stream.update_source()` durch eine neu allokierte signierte URL. Ein Mindestabstand von 10 Sekunden verhindert wiederholte Allokationen bei kurz aufeinanderfolgenden Fehlern; bei offline- oder veraltetem Gerät wird keine URL angefordert.
- Signierte URLs bleiben weiterhin nur im Speicher. Die Integration schreibt sie nicht in State, Attribute, eigene Logs, Recorder oder Diagnostics; ihre Fehlermeldungen nutzen pseudonymisierte Gerätekennungen.
- Alle bestehenden Entity-IDs, Unique-IDs und Automationen bleiben unverändert. Es werden keine Geräte-Schreibbefehle eingeführt; die Wallbox bleibt read-only. WebRTC wird weiterhin nicht angeboten (`device not supports`); der lokale 404 war ein Folgefehler der ungültigen HLS-Daten.
- Qualität: 152 Tests grün, Ruff und Formatierung sauber. Unabhängige Code-Freigabe nach Gegenprüfung der HA-Quellen ohne verbleibende Blocker.

### English

- Fixes the live view stopping after a short time, followed by `mpegts: wrong sync byte` and `DESCRIBE failed: 404` in the UI. The cause was not WebRTC but an expired signed HLS URL: HA's stream worker retries a failed source indefinitely with exactly the same URL and does not call `stream_source()` again.
- The camera now observes the availability change reported by HA's stream worker and replaces an unusable source with a newly allocated signed URL via the public `Stream.update_source()` API. A ten-second minimum interval avoids repeated allocations for closely spaced failures; no URL is requested while the device is offline or stale.
- Signed URLs still stay in memory only. The integration does not write them to state, attributes, its own logs, recorder or diagnostics; its error messages use pseudonymized device identifiers.
- All existing entity IDs, unique IDs and automations remain unchanged. No device write commands are introduced; the wallbox stays read-only. WebRTC is still not offered (`device not supports`); the local 404 was a follow-up error caused by invalid HLS data.
- Quality: 152 tests passing, Ruff and formatting clean. Independent code approval after verification against the HA sources, with no remaining blockers.

---

## [0.2.7] - 2026-11-27

### Deutsch

- Die vier verifizierten DPS-Integer-Codes werden anhand der Geräte-Specifications ausgelegt: `Wert / 10**scale` mit dem `scale` des Geräts und fest hinterlegten, live bestätigten Einheiten sowie passenden Device-/State-Classes. Damit gleicht die Anzeige der Original-`tuya`-Integration, ohne einen geratenen festen Faktor.
- Für das Balkonkraftwerk erscheinen `cur_power` in W (`power`/`measurement`), `cur_voltage` in V (`voltage`/`measurement`), `cur_current` in mA mit empfohlener Anzeige in A (`current`/`measurement`) und `add_ele` in kWh (`energy`/`total_increasing`). Diese Sensoren tragen lesbare Namen ohne „(Rohwert)" und behalten ihre bisherigen Entity-IDs.
- Unbekannte Codes, Kalibrierungswerte wie `power_coe`, Temperatur-, Feuchte- und Akku-Codes sowie fehlende oder ungültige Specifications bleiben unverändert roh. Die Auslegung wird beim Setup eingefroren; später eintreffende oder geänderte Specifications wirken erst nach einem Reload. Die Befehlspfade für Switch, Number, Light, Climate und Cover wurden nicht angefasst; die Wallbox bleibt read-only.
- Alle bestehenden Unique-IDs, Entity-IDs und Automationen bleiben stabil. Neu hinzu kommt `add_ele`, sofern das Gerät den Code meldet – ohne gültige Specification als Rohwert, mit gültiger Specification als Messsensor. `cur_power`, `cur_voltage` und `cur_current` behalten ihre Entity-IDs und erhalten nur bei gültiger Specification Einheiten und Classes.
- Diagnostics geben weiterhin keine Specifications-Metadaten aus; Redaction, Pseudonymisierung und die DE/EN-Übersetzungen wurden entsprechend erweitert und geprüft.
- Qualität: 142 Tests grün, Ruff und Formatierung sauber. Unabhängige Code-Freigabe nach drei Prüfrunden ohne verbleibende Blocker.

### English

- The four verified integer DPS codes are now interpreted from the device specifications: `value / 10**scale` with the device's `scale` and fixed, live-confirmed units plus matching device/state classes. The display matches the original `tuya` integration without a guessed fixed factor.
- For the balcony power meter, `cur_power` appears in W (`power`/`measurement`), `cur_voltage` in V (`voltage`/`measurement`), `cur_current` in mA with a suggested display unit of A (`current`/`measurement`) and `add_ele` in kWh (`energy`/`total_increasing`). These sensors use readable names without "(raw value)" and keep their existing entity IDs.
- Unknown codes, calibration values such as `power_coe`, temperature, humidity and battery codes, and missing or invalid specifications remain raw. The interpretation is captured at setup; specifications arriving or changing later take effect only after a reload. Command paths for switch, number, light, climate and cover were untouched; the wallbox stays read-only.
- All existing unique IDs, entity IDs and automations remain stable. `add_ele` is added when the device reports the code – as a raw value without a valid specification and as a measurement sensor with one. `cur_power`, `cur_voltage` and `cur_current` keep their entity IDs and gain units/classes only with a valid specification.
- Diagnostics still omit specification metadata; redaction, pseudonymization and the DE/EN translations were extended and verified accordingly.
- Quality: 142 tests passing, Ruff and formatting clean. Independent code approval after three review rounds with no remaining blockers.

---

## [0.2.6] - 2026-11-27

### Deutsch

- Behebt einen Fehler, durch den der `dé EV Charger` trotz vorhandener IoT-Core-Shadow-Daten als unverfügbar angezeigt wurde. Tuya lehnt die klassischen Endpunkte `status`, `functions` und `specifications` für dieses Gerät mit den errno `2003`/`2009` („function not support" bzw. „not support this device") ab; die Werte liegen jedoch weiterhin frisch im Thing-Shadow vor.
- Die Antwortcodes `2003`/`2009` werden nun als erwartetes Merkmal von IoT-Core-only-Geräten erkannt. Ein fehlgeschlagener Legacy-Status markiert das Gerät nicht mehr als Fehler, löst keine Repairs aus und verändert keine bestehenden Entity-IDs, Automationen oder Konfigurationen.
- Sensoren aus dem Thing-Shadow richten ihre Verfügbarkeit nach den tatsächlich vorhandenen und erfolgreich aktualisierten Shadow-Daten statt nach dem Legacy-Status. Damit bleiben die 16 Lader-Sensoren verfügbar, sobald der Shadow Werte liefert; echte Shadow-Fehler und offline-Geräte bleiben weiterhin `unavailable`.
- Ein fehlgeschlagener oder abgelehnter Shadow-Abruf markiert die Sensoren jetzt ausdrücklich als nicht aktuell; veraltete Werte bleiben nicht `available`. Wird der Legacy-Status nicht unterstützt, wird ein zuvor gespeicherter Status verworfen, damit keine alten DPS-Werte als aktuell erscheinen. Echte IoT-Core-Berechtigungsfehler lösen weiterhin einen Repair aus.
- Diagnostics weist nun beide Aktualisierungsstatusse (`last_update_success`, `shadow_last_update_success`) pro Gerät aus; ohne sensible Werte. Echte Fehler (Autorisierung, Netzwerk, Rate-Limits, ungültige Antworten) werden unverändert erkannt; Redaction und Pseudonymisierung bleiben intakt. Es wurden keine Übersetzungsschlüssel geändert.
- Qualität: 117 Tests grün, Ruff und Formatierung sauber. Unabhängige Freigabe durch Claude Sonnet 5.5 ohne verbleibende Blocker.

### English

- Fixes an issue where the `dé EV Charger` was shown as unavailable despite the presence of fresh IoT Core thing-shadow data. Tuya rejects the legacy `status`, `functions` and `specifications` endpoints for this device with errno `2003`/`2009` ("function not support" / "not support this device"), while the thing shadow keeps returning current values.
- Response codes `2003`/`2009` are now recognized as an expected trait of IoT Core-only devices. A rejected legacy status no longer marks the device as failed, raises repairs or changes any existing entity IDs, automations or configurations.
- Thing-shadow sensors base their availability on the actually present, successfully refreshed shadow data instead of the legacy status. The 16 charger sensors therefore become available as soon as the shadow returns values; genuine shadow failures and offline devices remain `unavailable`.
- A failed or denied shadow refresh now explicitly marks the sensors as stale; old values are no longer reported as available. When the legacy status is unsupported, a previously stored status is discarded so old DPS values cannot appear as current. Genuine IoT Core permission errors still raise a repair.
- Diagnostics now reports both freshness flags (`last_update_success`, `shadow_last_update_success`) per device; no sensitive values are included. Real errors (authorization, network, rate limits, invalid responses) are still detected; redaction and pseudonymization remain intact. No translation keys were changed.
- Quality: 117 tests passing, Ruff and formatting clean. Independent approval by Claude Sonnet 5.5 with no remaining blockers.

---

## [0.2.5] - 2026-11-27

### Deutsch

- UX: Bekannte DPS-Codes erhalten lesbare, de/en-lokalisierte Namen statt technischer Codes. Da die Skalierung pro Gerät unterschiedlich sein kann, bleiben alle DPS-Werte ausdrücklich als Rohwerte gekennzeichnet; es werden keine Einheiten, Device-Classes oder Statistiken erfunden.
- Der doppelten Helligkeitssteuerung wird nur vorgebeugt, wenn die Light tatsächlich denselben Code nutzt. Andernfalls bleibt `bright_value_v2` wie in 0.2.4 als Number verfügbar. Alle 73 bestehenden Entity-IDs, Automationen und Konfigurationen bleiben unverändert.
- Bestehende Switches behalten ihre Platzierung auf der Gerätekarte; es werden keine Entity-Kategorien nachträglich geändert. `work_state_debug` ist nun als Diagnose gekennzeichnet, und die Firmware aus dem Shadow erscheint als Geräte-Firmware. Zustandsübersetzungen gibt es nur für live belegte Werte (`101` = Bereitschaft, `300` = Lädt); die Anzeigenamen einiger Shadow-Sensoren wurden präzisiert (z. B. „Configured maximum current“), ihre Entity-IDs bleiben gleich.
- Fehler und Repairs nutzen vollständig lokalisierte Sätze statt englischer Rohmeldungen. Auch andere Befehlsfehler als Code 1106 werden als verständlicher `HomeAssistantError` gemeldet; Debug-Logs behalten Fehlercodes, aber keine sensiblen Rohtexte.
- Die Kamera folgt jetzt derselben Verfügbarkeitslogik wie die übrigen Plattformen; die Stream-URL wird weiterhin nie gespeichert oder protokolliert. Regionsnamen vermeiden doppelte Klammern, Geräte ohne Namen erhalten einen freundlichen Platzhalter statt der internen ID.
- Alle Plattformen deklarieren `PARALLEL_UPDATES`. Die Mindestversion steigt auf Home Assistant 2025.8.0, weil `OptionsFlowWithReload` dort eingeführt wurde.
- Qualität: 109 Tests grün, Ruff und Formatierung sauber. Zwei unabhängige Review-Runden durch Claude Sonnet 5.5, abschließend ohne verbleibende Release-Blocker.

### English

- UX: Known DPS codes now get readable, localized DE/EN names instead of technical codes. Because scaling can differ per device, all DPS values are explicitly marked as raw values; no units, device classes or statistics are invented.
- Duplicate brightness controls are prevented only when the light actually uses the same code. Otherwise `bright_value_v2` stays available as a number as in 0.2.4. All 73 existing entity IDs, automations and configurations remain unchanged.
- Existing switches keep their place on the device card; no entity categories are changed retroactively. `work_state_debug` is now diagnostic, and firmware from the shadow is shown as the device firmware. State translations exist only for live-observed values (`101` = standby, `300` = charging); a few shadow sensor display names were clarified (e.g. "Configured maximum current") while their entity IDs stay the same.
- Errors and repairs use fully localized sentences instead of raw English messages. Command failures other than code 1106 are also reported as a friendly `HomeAssistantError`; debug logs keep error codes but no sensitive raw text.
- The camera now follows the same availability logic as the other platforms; the stream URL is still never stored or logged. Region names avoid nested parentheses, and unnamed devices get a friendly fallback instead of the internal ID.
- All platforms declare `PARALLEL_UPDATES`. The minimum version rises to Home Assistant 2025.8.0 because `OptionsFlowWithReload` was introduced there.
- Quality: 109 tests passing, Ruff and formatting clean. Two independent review rounds by Claude Sonnet 5.5, ending with no remaining release blockers.

---

## [0.2.4] - 2026-11-27

### Deutsch

- Qualitäts-Audit der Integration ohne Funktionsverlust: alle bestehenden Plattformen, Entitäten, Services, Automationen, Dashboards und Konfigurationen bleiben erhalten.
- API-Härtung: HTTP-Status werden geprüft (401/403/429/5xx), Token-Refresh ist gegen parallele Requests abgesichert, kurze Token-Laufzeiten werden begrenzt und die Geräteliste unterstützt Pagination.
- Coordinator: Shadow-Werte werden alle 60 Sekunden aktualisiert und bei leerer oder fehlgeschlagener Antwort sofort erneut versucht; neue Lader-Sensoren erscheinen dynamisch, sobald Daten eintreffen. Fehlgeschlagene Statuslesevorgänge markieren betroffene Geräte als unverfügbar.
- Setup-Fehler werden korrekt als `ConfigEntryNotReady`/`ConfigEntryAuthFailed` gemeldet; Repairs werden gedrosselt und beim Entfernen des Eintrags gelöscht. Ein abgelehnter Befehl (1106) erzeugt einen Repair und eine lokalisierte `ServiceValidationError`.
- Datenschutz: Redaction und Pseudonymisierung für Tokens, Secrets, Access-ID/Secret-Werte, Geräte-IDs, UIDs, Stream-URLs und `m3u8`; Diagnostics enthalten weiterhin keine vertraulichen Werte.
- Stabilität der Entity-IDs: Light- und Cover-DPS-Codes werden in fester Reihenfolge gewählt. Der Switch-Filter behält bewusst alle live beobachteten Boolean-, Enum-, Integer- und String-Codes bei und schließt nur doppelte Light-Codes aus.
- UX/DE/EN: lokalisierte Regionsauswahl, Reauth ohne erneute Validierung alter Daten, korrekte Options-Texte zu deaktivierten Entitäten und präzisere Sensorbezeichnungen. Die Doku beschreibt jetzt eindeutig, dass nur zur Laufzeit kein App-Login nötig ist.
- Tests/CI: 81 Tests grün, `pytest.ini` mit `strict-markers`/`strict-config`, `validate.yml` mit Concurrency und Timeouts, Ruff und Formatierung sauber.

### English

- Quality audit without feature loss: all existing platforms, entities, services, automations, dashboards and configurations are preserved.
- API hardening: HTTP statuses are checked (401/403/429/5xx), token refresh is protected against parallel requests, short token lifetimes are clamped and device listing supports pagination.
- Coordinator: shadow values refresh every 60 seconds and are retried immediately on empty or failed responses; new charger sensors appear dynamically once data arrives. Failed status reads mark the affected devices as unavailable.
- Setup errors are correctly reported as `ConfigEntryNotReady`/`ConfigEntryAuthFailed`; repairs are throttled and deleted when the entry is removed. A rejected command (1106) creates a repair and a localized `ServiceValidationError`.
- Privacy: redaction and pseudonymization for tokens, secrets, Access ID/Secret values, device IDs, UIDs, stream URLs and `m3u8`; diagnostics still contain no confidential values.
- Stable entity IDs: light and cover DPS codes are selected in a fixed order. The switch filter deliberately retains all observed Boolean, Enum, Integer and String codes and only excludes duplicate light codes.
- UX/DE/EN: localized region selector, reauth without revalidating old data, corrected option text for disabled entities and more precise sensor names. The docs now state clearly that no app login is needed at runtime only.
- Tests/CI: 81 tests passing, `pytest.ini` with `strict-markers`/`strict-config`, `validate.yml` with concurrency and timeouts, Ruff and formatting clean.

---

## [0.2.3] - 2026-11-27

### Deutsch

- Die Climate-Entity nutzt jetzt `native_current_temperature`, `native_target_temperature` und `_attr_native_temperature_unit`. Damit verschwinden die Deprecation-Warnungen, die ab Home Assistant 2027.11 zum Fehler würden.
- Ein doppelt gesetztes `TARGET_TEMPERATURE`-Feature bei Geräten mit `mode`-DPS wurde entfernt.
- Version und Dokumentation auf 0.2.3 nachgezogen; 49 Tests grün, Ruff sauber.

### English

- The climate entity now uses `native_current_temperature`, `native_target_temperature` and `_attr_native_temperature_unit`, removing deprecation warnings that would become errors in Home Assistant 2027.11.
- Removed a duplicate `TARGET_TEMPERATURE` feature assignment for devices with a `mode` DPS.
- Version and documentation updated to 0.2.3; 49 tests passing, Ruff clean.

---

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
