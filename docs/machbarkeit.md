# Machbarkeit: `tuya_project_cloud` (Stand 2026-11-27)

[English](machbarkeit.en.md)

Status: **Phase 0/1 abgeschlossen – Live-Beweis erbracht, Implementierung freigegeben.**

## 1. Important rule und Einhaltung

> Nicht coden, bevor bewiesen wurde, dass die Tuya OpenAPI die benötigten Gerätezugriffe ohne Smart-Life-Benutzerkonzept zulässt.

Diese Regel wurde eingehalten. Zuerst wurde ausschließlich recherchiert und dokumentiert – **ohne jeglichen Implementierungscode**. Die Zugangsdaten wurden später im Bitwarden-Item `Credential_Tuya_AccessID` lokalisiert (siehe `SecondBrain/wiki/konzepte/zugangsdaten-fundorte.md`) und gezielt für die Live-Tests verwendet (Werte nur im Prozess, nie ausgegeben oder gespeichert). Erst nach dem erfolgreichen Steuerbeweis (Abschnitt 8) wurde Code erzeugt.

## 2. Zentrale Erkenntnis

Die Zielsetzung ist **nicht pauschal machbar**, sondern nur mit einer klaren Einschränkung:

| Geräteherkunft | Projekt-Token (`grant_type=1`) ohne App-Login | Bewertung |
|---|---|---|
| Geräte, die im **eigenen Cloud-Projekt** erstellt/aktiviert wurden (z. B. Virtual Device, Tuya Spatial / Smart Industry) | Lesen **und** Steuern laut Doku möglich | Machbar |
| Bestehende **Smart-Life-/Tuya-App-Geräte**, die per „Link App Account“ verknüpft wurden | Lesen über `associated-users/devices` belegt; **Steuern ist dokumentationsseitig umstritten** und hängt vom Berechtigungspaket/Token-Kontext ab | Nicht ohne Live-Test bewiesen |
| Geräte, die nur in einem App-Konto liegen (unverknüpft) | Nicht sichtbar | Nicht machbar |

**Kritischer Widerspruch in der offiziellen Doku:**

- `Device Control Practice` / `Link Devices` sagen für verlinkte Geräte: *„not authorized to control these linked devices, but only has permissions to view device status“*.
- `Link Devices` (andere Seite) sagt: Verlinken enable *„device control and management on the Tuya Developer Platform“*.
- Die Praxis von HA Core nutzt zusätzlich einen User-Token (`tuya_sharing`, User Code + QR).

Auflösung nur durch Live-Test T6 (siehe `docs/api-testplan.md`).

## 3. Bestehende Komponenten – Wiederverwendung geprüft

| Komponente | Ergebnis |
|---|---|
| HA Core `tuya` (dev, 27.11.2026) | Verlangt zwingend `user_code` + QR-Scan. Kein Access-ID/Secret-Feld. `cloud_push`, kein LAN-Fallback. `support_local` betrifft nur MQTT-Topics (`/pen` vs `/sta`), nicht LAN. Abhängigkeiten: `tuya-device-sharing-sdk==0.2.15`, `tuya-device-handlers` (dev `2026.12.1`). |
| Xtend Tuya 4.5.4 | Startet ebenfalls mit `user_code` + QR. OpenAPI-Option verlangt **zusätzlich** App-Konto + Passwort und verlinkten App-Account. Projekt-only im UI-Flow nicht vorgesehen. |
| `tuya-connector-python` (offiziell, MIT) | Nutzt `GET /v1.0/token?grant_type=1` – passend für reinen Projekt-Token. Sync/`requests`, älter (PyPI 0.1.2). Enthält optional Pulsar-Push. |
| `tuya-device-sharing-sdk` (offiziell, MIT, aktiv) | Wird von HA Core genutzt; User-/Sharing-Kontext, kein reiner Projekt-Token-Client. Nur sinnvoll, wenn wir einen User-Token-Layer zulassen. |
| `tinytuya` (Community, MIT, aktiv) | LAN + Cloud, flexibles DPS-Mapping.Cloud ist Teilmenge, nicht offiziell. Gut zum Debuggen, nicht als Kernabhängigkeit empfohlen. |

**Fazit:** Keine bestehende HA-Komponente erfüllt „Projekt-only ohne App-Konto“ direkt. Wiederverwendbar sind aber HA-Pattern (Coordinator/Dispatcher, Entity-Descriptions, Diagnostics, Repairs) und ggf. `tuya-connector-python` für Signatur/Token.

## 4. Lokale Evidenz (nicht öffentlich reproduzierbar)

Aus `SecondBrain/wiki/projekte/aosu.md` und `research_notes/AoSu OEM Pfad Risiken/technik.md` (26.11.2026):

- Projekt `SmartHome` (vormals `aosu-desktop-local`), Region EU: Token, Geräteliste mit **6 Geräten (5 online)** und Stream-Allokation waren echt erfolgreich – **alle Geräte stammten aus SmartLife**.
- `from=sharing` ergab `count=0`.
- Die AoSu-Kameras sind nicht in der Tuya-Geräteliste; sie nutzen ein eigenes Hersteller-Backend (`api-eu.aosulife.com`).
- Diese Evidenz beweist Zugriff auf **verknüpfte SmartLife-Geräte**, nicht auf Geräte ohne App-Kontext und nicht auf AoSu-Hardware.

## 5. Technische Constraints (Assets, User, Homes, Geräte)

- **Access ID/Secret** identifiziert das Projekt, nicht den Endnutzer.
- **Projekt-Token** (`grant_type=1`) gilt für projektspezifische Daten. **User-Token** (`grant_type=2` / `authorized-login` / QR) gilt für App-Account-Daten.
- **`uid` / `open_uid`**: UID des verlinkten App-Accounts; kein Token und allein keine Steuerberechtigung. Community-Begriff `open_uid`, offizielle Doku sagt meist „App Account UID“.
- **`owner_id`** in Geräterecords entspricht der Home-ID des App-Accounts, nicht dem Projekt.
- **`asset_id`** ist ein Industry-Asset-Knoten (Baum, Wurzel `parent_asset_id=-1`), **nicht** dasselbe wie ein Smart-Home-`home_id`.
- **`space_id`** ist die neuere IoT-Core-Struktur (`/v2.0/cloud/space/...`).
- Linking übernimmt **nicht die Ownership**; pro App/App-Account maximal **zwei Projekte**.
- Ohne Linking erscheinen App-Geräte nicht in `/v1.0/devices` oder `/v1.3/iot-03/devices`.

## 6. DPS und Funktionen

- Keine universelle DPS-Nummerierung; Codes sind produktspezifisch.
- `functions` = mögliche Commands, `status` = meldbare Zustände. Beides muss pro Gerät über `specifications`/`functions` geholt werden.
- Typen: `Boolean`, `Integer`, `Enum`, `Json`, `String`; `values` enthält `min`, `max`, `step`, `scale` oder Enum-Ranges.
- Standard-Instruction-Sets sind nur eine Teilmenge; leere Ergebnisse brauchen ein Tuya-Ticket.
- Rate-Limits (Auszug, pro Projekt): `shadow/actions` 4/s, `shadow/properties` GET 50/s, `thing/{id}/state` 5/s, `thing/batch` 4/s.

## 7. Architektur-Konsequenz (implementiert, siehe `docs/architektur.md`)

Die Live-Tests haben gezeigt, dass die `v1.0/devices`-Familie für verlinkte Geräte funktioniert. Davon ausgehend:

1. **Config Flow**: Access ID, Access Secret, Region. Kein App-Konto, kein Passwort. Optionaler späterer Schritt für verlinkte Geräte mit User-Kontext – aber nur, wenn der Nutzer das ausdrücklich will.
2. **Client**: Eigener async HTTP-Client (Signatur nach aktueller Doku) oder Wrapper um `tuya-connector-python` via Executor. Kein `tuya_sharing` im Projekt-only-Pfad.
3. **Datenmodell**: `entry.runtime_data` mit Client + `DataUpdateCoordinator` (Polling, da ohne Push-Kanal). Push (Pulsar) erst in einer späteren Phase.
4. **Entities**: Dynamisch aus `functions`/`status` + DPS-Codes. Plattformen: Switch, Sensor, Light, Climate, Cover, Number, Camera; zusätzliche Shadow-Sensoren aus dem IoT-Core-Thing-Shadow. Entity-Descriptions mit `device_class`, `native_unit_of_measurement`, `EntityCategory`.
5. **Geräte/Range**: `DeviceInfo` pro Tuya-Gerät, `identifiers={(DOMAIN, device_id)}`; Child Devices wo zutreffend.
6. **Diagnostics/Repairs**: Redaction von Tokens, Secrets, DPS-Werten mit personenbezogenen Daten; Repairs für Auth-Fehler, falsche Region, fehlende API-Autorisierung.
7. **Tests**: `pytest-homeassistant-custom-component`, Zwischenstand 0.1.0: 36 Tests grün, 84 % Gesamt-Coverage; Stand 0.2.3: 49 Tests grün, `ruff check`/`format` sauber. Config-Flow, Coordinator, Entity-Mapping, Kamera, Redaction.

## 8. Live-Beweis (2026-11-27) – Important rule erfüllt

Gezielter Abruf des **einzelnen** Bitwarden-Items `Credential_Tuya_AccessID` (Tresor entsperrt, Werte nur im Prozess, nie ausgegeben oder gespeichert). Echte OpenAPI-Calls gegen `https://openapi.tuyaeu.com`:

| Test | Ergebnis | Beweis |
|---|---|---|
| T0 `GET /v1.0/token?grant_type=1` | `success=True` | Projekt-Token ohne App-Login |
| T1 `GET /v1.3/iot-03/devices` | `success=True`, **0 Geräte** | Keine Geräte im `iot-03`-Datenbereich |
| T5 `GET /v1.0/iot-01/associated-users/devices` | `success=True`, **6 Geräte** | Verknüpfte SmartLife-Geräte mit `uid`, `owner_id`, `local_key`, `status` |
| `iot-03` Status auf verlinktem Gerät | Fehler `28841105` „This project is not authorized to call this API" | `iot-03`-Familie für dieses Projekt **nicht autorisiert** |
| `GET /v1.0/devices/{id}/status`, `/functions`, `/specifications` | alle `success=True` | Lesender Zugriff auf verlinkte Geräte **mit Projekt-Token** |
| **T6 `POST /v1.0/devices/{id}/commands`** | **`success=True`**, Readback `success=True` | **Steuerung mit reinem Projekt-Token bewiesen** |

Der Command-Test war **idempotent**: Der exakt zuvor gelesene Wert (`wireless_lowpower`, Int64) wurde unverändert zurückgeschrieben, sodass sich der Gerätezustand nicht änderte. Es wurde **kein** App-Passwort, kein User-Token und kein QR-Login verwendet.

**Auflösung des Doku-Widerspruchs:** Die Aussage „view device status only" gilt offenbar nicht für dieses Projekt/Berechtigungspaket bzw. nicht für die `v1.0/devices`-Endpunktfamilie. Der konkrete Live-Befund gewinnt. Die Architektur nutzt daher **ausschließlich die `v1.0/devices`- und `v1.0/iot-01/associated-users`-Familie**; `iot-03` wird nicht verwendet.

**Konsequenz:** Die wichtige Regel ist erfüllt. Implementierung ist freigegeben. Scope: Geräte des verlinkten App-Kontos, die über `associated-users/devices` sichtbar sind. Geräte ohne Verknüpfung bleiben unsichtbar (Design-Grenze, siehe Abschnitt 5).

## 9. Verifikation der Implementierung (2026-11-27)

Nach der Implementierung wurde der **eigene Python-Client** (`custom_components/tuya_project_cloud/api.py`) erneut live gegen die echte Tuya-API getestet – nicht mehr das PowerShell-Probe-Skript, sondern der Code, der in Home Assistant läuft:

```
T0 token=OK
T1 devices=6
DEV cat=sp functions=12 status_codes=21 specs=21
COMMON codes=12
CONTROL code=wireless_lowpower type=int success=OK
READBACK code_present=True unchanged=True
```

Der Befehl war wieder **idempotent** (exakt der gelesene Wert wurde zurückgeschrieben). Damit ist **`device control and management` mit der tatsächlichen Integrationsimplementierung bewiesen**.

**Test- und Qualitätsstatus:**

| Prüfung | Ergebnis |
|---|---|
| Unit-Tests (WSL, Python 3.13, `pytest-homeassistant-custom-component`) | **49 passed** (Stand 0.2.3) |
| `ruff check` / `ruff format --check` | **All checks passed** / sauber |
| Live-Smoke-Test des eigenen Clients | **Erfolg** (siehe oben) |
| Live-Probe Shadow/Stream des eigenen Clients | **Erfolg** (8 Geräte, 23 DPS, HLS-Allokation; siehe Abschnitt 11) |

**Zielerreichung:** Die Integration listet Geräte, liest Status/Funktionen/Spezifikationen und steuert Geräte über die Tuya OpenAPI – ausschließlich mit Access ID + Access Secret, ohne Smart-Life-App-Login zur Laufzeit. Das gesetzte Ziel ist damit erreicht.

## 10. Livebild-Machbarkeit am Türspion (27.11.2026)

Anschließend wurde rein lesend geprüft, ob derselbe Projekt-Token auch ein Livebild liefert. Der Dienst `IoT Video Live Stream` ist im Projekt `SmartHome` kostenlos autorisiert.

| Prüfung | Ergebnis |
|---|---|
| `POST /v1.0/devices/{id}/stream/actions/allocate`, `{"type":"hls"}` | `success=True`, signierte HTTPS-URL, `.m3u8`, `signInfo` |
| gleicher Endpunkt mit `{"type":"rtsp"}` | `success=True`, `result.url` |
| `POST /v1.0/users/{uid}/devices/{id}/stream/actions/allocate` (HLS und RTSP) | beide `success=True` |
| `GET /v1.0/devices/{id}/webrtc-configs` | `device not supports` |

Beide Stream-Endpunkte sind im offiziellen User Permission Package (Stand 05.11.2026) gelistet. Die signierte URL wurde **weder ausgegeben noch gespeichert**; der Probe meldete nur Erfolg, Fehlerklassen und die URL-Form (Schema/Port/Suffix). Kein App-Passwort, kein User-Token, keine Geräteveränderung.

**Einordnung:** Die historische HA-Entität `camera.turspion` lieferte 404-Streams und riss am 06.10.2026 das Setup in `setup_error` (ADR 0009 im SecondBrain-Wiki). Die damalige Ursache bleibt unbelegt; die OpenAPI liefert den Stream mit dem Projekt-Token jetzt aber echt. Eine `camera`-Plattform ist für diese Integration damit machbar und in 0.2.0 **implementiert** (siehe Abschnitt 11).

**Umsetzung:** `stream_source()` allokiert bei jedem Start neu; die URL bleibt nur im Prozess – nie in Log, Diagnostics, Recorder oder Config Entry. WebRTC wird nicht angeboten; optional go2rtc-`tuya://` für Gegensprechen. Gültigkeitsdauer der URL und HLS-Stabilität in einer echten HA-Instanz sind weiterhin ungetestet.

Nachweis im SecondBrain-Wiki: `wiki/fragen/2026-11-27-tuya-tuer-spion-livebild.md` (nicht Teil dieses Repos).

## 11. Umsetzung in 0.2.0: Laderdaten und Livebild (27.11.2026)

Nach der IoT-Core-Freigabe wurde der eigene Client erneut live geprüft. Ausgabe der geheimnisfreien Probe (ohne Geräte-IDs, Tokens und Stream-URL):

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

| Prüfung | Ergebnis |
|---|---|
| `GET /v2.0/cloud/thing/{id}/shadow/properties` über `TuyaOpenApi.async_get_thing_shadow()` | `23` Properties, `16` gemappte Sensoren |
| `POST /v1.0/devices/{id}/stream/actions/allocate` über `TuyaOpenApi.async_allocate_stream()` | URL mit `.m3u8` und Signatur-Query, nur im Speicher |
| `camera`-Plattform | HLS über `stream_source()`, kein WebRTC |
| Redaction | Stream-URL und `m3u8` in Diagnostics maskiert, `_unrecorded_attributes = frozenset(MATCH_ALL)` |

**Grenzen:** Die Skalierung der `x_*`-Werte folgt Community-Referenzen (evcc/tuya-local), nicht dem Hersteller `(unbelegt im Detail)`. `d`/`t` aus `x_metrics` und `x_charge_history` bleiben wegen unklarer Einheit unbewertet. Es werden keine Schreibbefehle an die Wallbox gesendet. Ein Einsatz in einer laufenden HA-Instanz steht noch aus.

Nachweis im SecondBrain-Wiki: `wiki/fragen/2026-11-27-tuya-ev-charger-werte.md`, `wiki/projekte/tuya-project-cloud-ausbauplan.md`.
