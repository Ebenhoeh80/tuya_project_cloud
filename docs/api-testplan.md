# Minimaler Live-API-Testplan (vom Nutzer mit eigenen Credentials auszuführen)

[English](api-testplan.en.md)

Zweck: Beweis, ob die Tuya OpenAPI ohne Smart-Life-Benutzerkonzept Geräte listen, lesen und steuern kann. **Keine Secrets oder Tokens in dieses Repository oder in den Chat kopieren.** Antworten vor dem Teilen maskieren.

Stand: 2026-11-27. Alle Pfade mit Platzhaltern.

## Vorbereitung

Region passend zum Projekt wählen:

| Region | Base URL |
|---|---|
| CN | `https://openapi.tuyacn.com` |
| US (West) | `https://openapi.tuyaus.com` |
| US (East) | `https://openapi-ueaz.tuyaus.com` |
| EU (Zentral) | `https://openapi.tuyaeu.com` |
| EU (West) | `https://openapi-weaz.tuyaeu.com` |
| IN | `https://openapi.tuyain.com` |
| SG | `https://openapi-sg.iotbing.com` |

Signatur (pro Request):

```text
stringToSign = METHOD + "\n" + SHA256(body_hex) + "\n" + "" + "\n" + path?query

Token-Call:
sign = UPPER(HMAC_SHA256(secret, client_id + t + nonce + stringToSign))

Business-Call:
sign = UPPER(HMAC_SHA256(secret, client_id + access_token + t + nonce + stringToSign))
```

- Leerer Body-Hash: `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`
- Query-Parameter alphabetisch sortieren.
- `t` = 13-stelliger Unix-Millisekunden-Timestamp.
- `nonce` = zufällige UUID, identisch in Header und Signatur.
- Header: `client_id`, `sign`, `sign_method: HMAC-SHA256`, `t`, `nonce`, bei Business-Calls `access_token`.
- Bei POST: `Content-Type: application/json`.

Empfehlung: Signatur von `tuya-connector-python` berechnen lassen, statt sie selbst zu implementieren. Dann bleibt der Test trotzdem ein echter OpenAPI-Call mit Access ID/Secret.

## T0 – Projekt-Token

```http
GET {BASE}/v1.0/token?grant_type=1
client_id: <ACCESS_ID>
sign_method: HMAC-SHA256
t: <MS>
nonce: <UUID>
sign: <SIGN>
```

**Erwartung:** `access_token`, `refresh_token`, `expire_time`, `uid` (je nach Parser mit/ohne `result`-Wrapper).

**Beweis:** Access ID/Secret, Region, Timestamp und Signatur stimmen. Ohne Erfolg alles Weitere wertlos.

## T1 – Geräte im Projektdatenbereich listen

```http
GET {BASE}/v1.3/iot-03/devices?page_size=20
access_token: <PROJECT_TOKEN>
...Signatur-Header...
```

Alternative für Smart-Home-Projekte:

```http
GET {BASE}/v1.0/devices?page_no=1&page_size=20
```

**Erwartung:** `result.list[]` oder `result.devices[]` mit `id`, `uuid`, `name`, `product_id`, `category`, `online`, `owner_id`, `local_key`, `has_more`, `last_row_key`, `total`.

**Beweis:** Der Projekt-Token sieht Geräte **ohne App-User-Login**. Leere Liste: falsche Region, keine Geräte im Projekt oder Geräte liegen nur im App-Account.

## T2 – Gerätestatus lesen

```http
GET {BASE}/v1.0/iot-03/devices/{DEVICE_ID}/status
access_token: <PROJECT_TOKEN>
```

**Erwartung:** `result[]` mit `code` und `value`, z. B. `{"code":"switch_led","value":true}`.

**Beweis:** Lesender Zugriff auf den aktuellen Zustand.

## T3 – DPS-/Funktionsvokabular

```http
GET {BASE}/v1.0/iot-03/devices/{DEVICE_ID}/specification
GET {BASE}/v1.0/iot-03/devices/{DEVICE_ID}/functions
```

**Erwartung:** `result.category`, `result.functions[] {code,type,values}`, `result.status[] {code,type,values}`.

**Beweis:** Gültige DPS-Codes für dieses Gerät. Ohne diesen Schritt darf kein Command geraten werden.

## T4 – Steuerung mit reinem Projekt-Token (entscheidend)

Nur mit einem **eigenen, ungefährlichen Gerät** und einem aus T3 bekannten Code:

```http
POST {BASE}/v1.0/iot-03/devices/{DEVICE_ID}/commands
Content-Type: application/json
access_token: <PROJECT_TOKEN>

{"commands":[{"code":"<SAFE_CODE>","value":<SAFE_VALUE>}]}
```

**Erwartung:** `result: true`, `success: true`. Danach T2 wiederholen und Änderung prüfen.

**Beweis:** Endgültig, ob Projekt-only nicht nur lesen, sondern **steuern** kann. Ein Permission-Fehler hier ist der entscheidende Negativbefund.

## T5 – Verlinkte App-Geräte sichtbar machen

```http
GET {BASE}/v1.0/iot-01/associated-users/devices?size=20
access_token: <PROJECT_TOKEN>
```

**Erwartung:** `result.devices[]`, `has_more`, `last_row_key`, `total`; pro Gerät `id`, `uid`, `owner_id`, `local_key`, `status`, `product_id`.

**Beweis:** „Link App Account“ hat Geräte in den Projektdatenbereich gestellt. `uid` mit der in der Console angezeigten App-Account-UID vergleichen.

## T6 – Steuerberechtigung für verlinkte Geräte (umstritten)

```http
POST {BASE}/v1.0/iot-03/devices/{LINKED_DEVICE_ID}/commands
Content-Type: application/json
access_token: <PROJECT_TOKEN>

{"commands":[{"code":"<SAFE_CODE>","value":<SAFE_VALUE>}]}
```

**Mögliche Ergebnisse:**

- `result: true` → Steuerung mit Projekt-Token in diesem Projekt/Berechtigungspaket erlaubt.
- Fehler, typischerweise `1106 illegal permission` → deckt sich mit der offiziellen Aussage „view device status only“.

**Beweis:** Die umstrittene Kernfrage für die konkrete Konfiguration. Wichtiger als jede allgemeine Doku-Aussage.

## T7 – User-Kontext prüfen (nur falls T6 negativ)

Variante A:

```http
POST {BASE}/v1.0/iot-01/associated-users/actions/authorized-login
Content-Type: application/json

{"username":"<APP_LOGIN>","password":"<APP_PASSWORD>","country_code":<CC>,"schema":"tuyaSmart"}
```

**Erwartung:** `result.access_token`, `result.refresh_token`, `result.uid`, `result.expire_time`.

Danach T6 mit `access_token: <USER_TOKEN>` wiederholen.

Variante B: Home-Assistant-ähnlicher QR-User-Code-Flow über `tuya_sharing.LoginControl`.

**Beweis:** Wenn T6 mit Projekt-Token scheitert und mit User-Token Erfolg hat, ist endgültig geklärt: Linking + App-Login nötig → die wichtige Regel wäre für verlinkte Geräte verletzt.

## T8 – UID/Home/Asset sauber trennen

```http
GET {BASE}/v2.0/apps/{SCHEMA}/users?page_no=1&page_size=50&start_time=<10_STELLIG>&end_time=<10_STELLIG>
GET {BASE}/v1.0/users/{UID}/homes
GET {BASE}/v1.0/homes/{HOME_ID}/devices
```

**Beweis:** Ob `open_uid`/App-Account-UID dieselbe Identität ist wie in Home-/Associated-User-APIs. Verhindert Verwechslung von `uid`, `home_id`, `owner_id`, `asset_id`.

## T9 – IoT-Core-Thing-Shadow (Laderdaten)

```http
GET {BASE}/v2.0/cloud/thing/{DEVICE_ID}/shadow/properties
access_token: <PROJECT_TOKEN>
```

**Erwartung:** `success=true`, `result.properties[]` mit `code`, `value`, `dp_id`, `time`. Im konkreten Fall 23 Einträge, u. a. `x_work_state`, `x_work_st_debug`, `x_metrics`, `x_charger_info`, `x_charge_current`.

**Beweis:** Der Thing-Shadow liefert auch dann Werte, wenn `v1.0/devices/{id}/status`, `/functions` und `/specifications` leer oder nicht unterstützt sind. Ohne IoT-Core-Autorisierung: `28841105`. Nur Ergebnisform und Anzahl berichten, keine Values mit Gerätebezug veröffentlichen.

## T10 – Stream-Allokation (Livebild)

```http
POST {BASE}/v1.0/devices/{DEVICE_ID}/stream/actions/allocate
Content-Type: application/json
access_token: <PROJECT_TOKEN>

{"type":"hls"}
```

**Erwartung:** `success=true`, `result.url` mit `.m3u8` und Signatur-Query. Mit `{"type":"rtsp"}` ebenfalls `success=true`. `webrtc-configs` meldet `device not supports`.

**Beweis:** Livebild mit dem reinen Projekt-Token. Die URL ist kurzlebig und darf **niemals** in Repo, Chat, Log, Diagnostics, State oder Attributen landen. Der Test meldet nur Erfolg und URL-Form.

## Auswertung

| Tests | Ergebnis | Konsequenz |
|---|---|---|
| T0–T4 grün | Projekt-only für eigene Geräte bewiesen | Implementierung darf starten (Scope: projekteigene Geräte) |
| T0–T3, T5 grün, T4/T6 rot | Nur Lesen ohne App-Konto | Keine Steuerung → Ziel nicht erreichbar; Architektur muss User-Token-Layer oder anderes Gerätemodell prüfen |
| T1 leer, T5 grün | Geräte nur im App-Konto | Ohne App-Konto keine Geräte → Ziel nicht erreichbar |
| T6 rot, T7 grün | App-Login zwingend für Steuerung | Wichtige Regel verletzt; Integration wäre nicht „ohne Smart-Life-Login“ |
| T0 rot | Credentials/Region/Signatur falsch | Allgemeiner Fehler, kein Machbarkeitsurteil |
| T9 grün | Laderdaten ohne App-Konto lesbar | Shadow-Sensoren dürfen gebaut werden |
| T10 grün | HLS-Livebild mit Projekt-Token | Kamera-Plattform darf gebaut werden |

**Wichtig:** Für jeden Test nur das Ergebnis (`success`, `errno`, Feldnamen, Anzahl Datensätze) maskiert berichten – niemals Tokens, Secrets, `local_key`-Werte oder personenbezogene Gerätenamen.
