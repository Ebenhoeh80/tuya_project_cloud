# Tuya Project Cloud für Home Assistant

[English](README.en.md)

Eine Home-Assistant-Custom-Integration, die Geräte **ausschließlich über die Tuya OpenAPI** mit einem eigenen Cloud-Projekt (Access ID + Access Secret) steuert. **Zur Laufzeit kein App-Login, kein App-Passwort, kein QR-Code und kein User-Token.** Das App-Konto wird einmalig in der Tuya-Konsole verknüpft, damit dessen Geräte in der OpenAPI sichtbar sind.

## Status

Machbarkeit am 27.11.2026 live bewiesen: Token, Geräteliste, Status, Funktionen und ein idempotenter Steuerbefehl (`POST /v1.0/devices/{id}/commands`) funktionieren mit dem reinen Projekt-Token. Ebenfalls live umgesetzt: Der `dé EV Charger` liefert über den IoT-Core-Shadow 23 DPS-Werte, aus denen 16 Sensoren entstehen; der Türspion liefert über `stream/actions/allocate` ein kurzlebiges HLS-Livebild. Siehe [Machbarkeitsbericht](docs/machbarkeit.md), Abschnitte 10 und 11.

Stand 0.3.0: 168 Tests grün, Ruff sauber, Mindestversion Home Assistant 2025.8.0. Das Livebild läuft über einen lokalen HLS-Re-Proxy mit stabiler `index.m3u8` für HA und go2rtc; signierte Tuya-URLs, AES-Keys und Segmente bleiben intern und werden transparent erneuert. Die Installation ist auch für 0.3.0 live verifiziert: HACS-Upgrade, bestätigter Neustart und 13/13 Checks grün – 8 Geräte, 85/85 unveränderte Entity-IDs und Unique-IDs gegenüber 0.2.8, Config Entry `loaded`, beide Kameras mit `STREAM`, 0 `unavailable`, 0 `unknown`, 0 Repairs, keine neuen Stream-Fehler. Zwei 10-Minuten-Soaks über die volle Ressourcen-Gültigkeit liefen fehlerfrei; aktive Frontend-Wiedergabe bleibt `(unbelegt)`. 0.2.6 behebt, dass der `dé EV Charger` trotz frischer IoT-Core-Shadow-Werte als unverfügbar erschien: Tuya lehnt für dieses Gerät die klassischen `status`/`functions`-Endpunkte ab (errno `2003`/`2009`), weshalb die Shadow-Sensoren ihre Verfügbarkeit jetzt aus den tatsächlichen Shadow-Daten ableiten. Bestehende Entity-IDs, Automationen und Konfigurationen bleiben unverändert.

## Voraussetzungen

- Home Assistant 2025.8.0 oder neuer (wegen `OptionsFlowWithReload`).

1. Tuya-IoT-Projekt in der [Tuya Developer Console](https://platform.tuya.com/) anlegen.
2. Access ID und Access Secret notieren.
3. In der Konsole **Link App Account** nutzen und das Smart-Life-/Tuya-App-Konto per QR bestätigen. Die Geräte des App-Kontos werden dadurch im Projekt sichtbar.
4. Die Device-API unter **Service API → Add Authorization** freischalten. Ohne diese Freischaltung antwortet Tuya mit `28841105`.
5. Für Laderdaten IoT Core aktivieren und das Cloud-Projekt autorisieren; sonst verweigert die Thing-Shadow-API den Zugriff.

> Die Integration benötigt keinen App-Login zur Laufzeit. Das einmalige Verknüpfen eines App-Kontos in der Tuya-Konsole ist jedoch nötig, damit Geräte in der OpenAPI erscheinen. Geräte ohne diese Verknüpfung sind für jedes Cloud-Projekt unsichtbar.

## Installation

1. In HACS → Integrationen → Benutzerdefiniertes Repository hinzufügen.
2. Repository `Ebenhoeh80/tuya_project_cloud`, Kategorie `Integration`.
3. Integration „Tuya Project Cloud" installieren und Home Assistant neu starten.
4. Einstellungen → Geräte & Dienste → Integration hinzufügen → „Tuya Project Cloud".
5. Access ID, Access Secret und Region eingeben.

Alternativ: `custom_components/tuya_project_cloud` nach `/config/custom_components/` kopieren.

## Konfiguration

| Feld | Bedeutung |
|---|---|
| Access ID | Client ID des Tuya-Projekts |
| Access Secret | Client Secret des Tuya-Projekts |
| Region | `cn`, `us`, `us_east`, `eu`, `eu_west`, `in`, `sg` |

Unter Optionen lassen sich das Abfrageintervall (10–900 s, Standard 30 s), das Lesen der IoT-Core-Shadow-Daten und die Kamera-Plattform einstellen. Laderwerte werden dabei einmal pro Minute aktualisiert; bei leerer Antwort wird sofort erneut versucht. Optionen lösen einen Reload des Eintrags aus.

## Unterstützte Entitäten

Die Integration erzeugt Entitäten dynamisch aus den DPS-Funktionen und Statuscodes jedes Geräts:

| Plattform | Erkennung |
|---|---|
| Switch | Functions mit `switch`, `onoff`, `power`, `enable`, …; Boolean und bestehende Enum-/Integer-/String-Codes bleiben erhalten, Light-Codes sind ausgeschlossen |
| Sensor | Lesbare Statuscodes wie `battery`, `temperature`, `humidity`, …; vier verifizierte Integer-Messcodes mit `scale` aus den Specifications und fest hinterlegten Einheiten/Klassen |
| Number | Integer-Functions mit `min`/`max`/`step` |
| Light | `switch_led`/`led_switch`, optional `bright_value` |
| Climate | Kategorie `kt`/`ykq`/`hvac` oder `temp_set` |
| Cover | Kategorie `cl`/`curtain`/`jc` oder `control`/`position` |
| Sensor (Shadow) | Geräte mit IoT-Core-`x_*`-Properties: Arbeitszustand, Spannungen, Ströme, Leistung, Energie, Ladestrom, Firmware; neue Sensoren erscheinen, sobald Daten eintreffen |
| Camera | Kategorie `sp` oder Functions mit `stream`: HLS-Livebild |

Unbekannte Codes werden nicht geraten und nicht gesteuert. Für die vier verifizierten Integer-Messcodes `cur_power`, `cur_voltage`, `cur_current` und `add_ele` übernimmt die Integration `scale` aus den Geräte-Specifications und verwendet fest hinterlegte, live bestätigte Einheiten sowie passende Device-/State-Classes – entsprechend der Original-`tuya`-Integration, aber ohne festen Skalierungsfaktor. Die Auslegung wird beim Setup festgehalten; Änderungen der Specifications wirken erst nach einem Reload. Alle übrigen DPS-Werte bleiben ausdrücklich Rohwerte. Für den Lader werden nur live beobachtete und plausibel skalierte Shadow-Werte abgebildet; nicht eindeutige Zeiten und Zähler-Rohwerte bleiben außen vor. Es werden keine Schreibbefehle an die Wallbox gesendet.

## Technische Grenzen

- Nur Cloud-Polling (`cloud_polling`), kein LAN, kein `local_key`, kein Pulsar-Push (derzeit).
- Die `iot-03`-Endpunktfamilie wird bewusst nicht verwendet; sie ist für das getestete Projekt nicht autorisiert (`28841105`).
- Geräte müssen über „Link App Account" im Projekt sichtbar sein.
- Tuya-Rate-Limits gelten pro Projekt (z. B. Commands ~4/s).
- Diagnostics redaktieren Tokens, Secrets, `local_key`, UID, Standortdaten, Stream-URLs und `m3u8`; Geräte-IDs werden pseudonymisiert.
- Livevideo läuft als `camera`-Plattform mit HLS über einen lokalen Re-Proxy: HA und go2rtc sehen nur eine stabile lokale `index.m3u8`, während der Proxy signierte URLs, AES-Keys und Segmente im Speicher hält und erneuert. Die Integration schreibt diese Werte nicht in State, Attribute, eigene Logs, Recorder oder Diagnostics. Meldet der HA-Stream-Worker eine unbrauchbare Quelle, wird die Proxy-Allokation verworfen und `Stream.update_source()` mit derselben lokalen URL aufgerufen (Mindestabstand 10 s). Der 144-Bit-Pfad-Token ist opak und enthält keine Tuya-Geheimnisse, gewährt aber Zugriff auf den Livestream und sollte nicht öffentlich geteilt werden. WebRTC wird nicht angeboten (`device not supports`).
- Die DPS-Skalierung folgt `Wert / 10**scale` mit dem `scale` aus den Specifications des Geräts; Einheiten und Klassen der vier verifizierten Codes sind fest hinterlegt. Ohne verlässliche Specification bleibt der Rohwert sichtbar.
- Die Skalierung der `x_*`-Werte stammt aus Community-Referenzen, nicht vom Hersteller; `(unbelegt)`.

## Entwicklung

```bash
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements_test.txt
.venv\Scripts\pytest tests/
```

Architektur und Annahmen (jeweils de/en): [docs/architektur.md](docs/architektur.md) / [docs/architektur.en.md](docs/architektur.en.md), [docs/machbarkeit.md](docs/machbarkeit.md) / [docs/machbarkeit.en.md](docs/machbarkeit.en.md), [docs/api-testplan.md](docs/api-testplan.md) / [docs/api-testplan.en.md](docs/api-testplan.en.md).

## Lizenz

MIT
