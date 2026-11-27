# bdew_api

Python-Paket zur Kommunikation mit der BDEW-Schnittstelle. Es stellt eine `BDEW`-Klasse bereit, mit der Steuerungsanfragen und Statusmeldungen zwischen zwei Netzwerkteilnehmern (AEMT und PEMT) gesendet werden können.

## Inhaltsverzeichnis

- [Voraussetzungen](#voraussetzungen)
- [Installation](#installation)
- [Verwendung](#verwendung)
- [Paket ausführen](#paket-ausführen)
- [Konfigurationsparameter](#konfigurationsparameter)
- [TLS](#tls)

## Voraussetzungen

Python ≥ 3.10. Die folgenden Abhängigkeiten installiert `pip` automatisch mit:

| Paket           | Version              |
|-----------------|----------------------|
| flask           | \>= 3.1.2             |
| pydantic        | \>= 2.13.3            |
| pydantic_core   | \>= 2.46.3            |
| requests        | \>= 2.25.1            |

Nur zum Bauen des Pakets (Wheel) wird zusätzlich `setuptools` \>= 64 benötigt.

## Installation

```bash
python -m pip install bdew-api
```

Optional vorher die Abhängigkeiten mit festen Versionen installieren:

```bash
python -m pip install flask==3.1.2 pydantic==2.13.3 pydantic_core==2.46.3 requests==2.25.1
```

## Verwendung

### Im Terminal prüfen

```python
import bdew_api

# optional: Version anzeigen
print(bdew_api.__version__)
```

### Im Projekt

Jede Seite betreibt nur ihre eigene Hälfte der Schnittstelle (`role`). Ohne
`role` laufen beide Seiten in einem Prozess (`role="both"`, für Demo und Tests).
Für die eigene Seite ist der Host die Bind-Adresse, für die Gegenseite die
Zieladresse.

```python
from bdew_api import bdew

# AEMT-Seite: nimmt Steuerungsanfragen an (:8301), antwortet dem PEMT (:8202)
aemt = bdew.BDEW(
    aemt_id="001",
    aemt_host="0.0.0.0",       # eigene Seite: Bind-Adresse
    aemt_port=8301,
    pemt_id="002",
    pemt_host="10.0.0.2",      # Gegenseite: Zieladresse
    pemt_port=8202,
    role="aemt",
    control_demand_callback=lambda location_id, command, kind, remote_addr: print(location_id, kind),
    answer_to_sender=True,     # Antwort an den Absender der Anfrage statt an pemt_host
)

# PEMT-Seite: sendet Steuerungsanfragen an den AEMT, nimmt dessen Antworten an
pemt = bdew.BDEW(
    aemt_id="001",
    aemt_host="10.0.0.1",      # Gegenseite: Zieladresse
    aemt_port=8301,
    pemt_id="002",
    pemt_host="0.0.0.0",       # eigene Seite: Bind-Adresse
    pemt_port=8202,
    role="pemt",
    answer_callback=lambda route, body: print(route),
)
```

Die Server starten beim Erzeugen in Hintergrund-Threads (abschaltbar mit
`autostart=False`, dann später `start()` aufrufen).

### Verfügbare Funktionen

| Funktion                                                  | Beschreibung                |
|-----------------------------------------------------------|-----------------------------|
| `bdew.send_control_request(command_control, location_id)` | Sendet eine Steuerungsanfrage |
| `bdew.send_control_status(result)`                        | Sendet einen Steuerungsstatus |
| `bdew.start()`                                            | Startet die Server der eigenen Seite (nur nötig bei `autostart=False`) |

## Paket ausführen

Das Paket enthält eine Demo, die beide Seiten in einem Prozess startet, eine
Steuerungsanfrage und eine positive Antwort (`positive`) sendet und sich dann
beendet:

```bash
python -m bdew_api <aemt_id> <aemt_host> <aemt_port> <pemt_id> <pemt_host> <pemt_port>
# gleichwertig, als Konsolenbefehl:
bdew_api <aemt_id> <aemt_host> <aemt_port> <pemt_id> <pemt_host> <pemt_port>
```

Beispiel:

```bash
python -m bdew_api 001 127.0.0.1 8301 002 127.0.0.1 8202
```

Die Demo braucht die TLS-Dateien beider Seiten im Arbeitsverzeichnis
(`aemt-cert.pem`, `aemt-key.pem`, `pemt-cert.pem`, `pemt-key.pem`,
`wan-ca.pem`, siehe [TLS](#tls)); ohne sie werden nur Warnungen ausgegeben.

## Konfigurationsparameter

| Parameter   | Typ   | Beschreibung              |
|-------------|-------|---------------------------|
| `aemt_id`   | `str` | ID des AEMT               |
| `aemt_host` | `str` | Hostname/IP des AEMT (AEMT-Seite: Bind-Adresse, PEMT-Seite: Zieladresse) |
| `aemt_port` | `int` | Port des AEMT             |
| `pemt_id`   | `str` | ID des PEMT               |
| `pemt_host` | `str` | Hostname/IP des PEMT (PEMT-Seite: Bind-Adresse, AEMT-Seite: Zieladresse) |
| `pemt_port` | `int` | Port des PEMT             |
| `role`      | `str` | `"aemt"`, `"pemt"` oder `"both"` (Standard): welche Hälfte der Schnittstelle dieser Prozess betreibt |
| `control_demand_callback` | Funktion | AEMT-Seite: aufgerufen als `(location_id, command, kind, remote_addr)` für jede gültige Steuerungsanfrage (`kind`: `"control"` oder `"regular"`) |
| `answer_callback` | Funktion | PEMT-Seite: aufgerufen als `(route, body)` für jede Antwort des AEMT |
| `answer_to_sender` | `bool` | AEMT-Seite: Antworten an die Adresse der letzten Anfrage statt an `pemt_host` (Standard: `False`) |
| `autostart` | `bool` | Server beim Erzeugen starten (Standard: `True`) |
| `aemt_certfile` / `aemt_keyfile` | `str` | Zertifikat + Schlüssel des AEMT (Standard: `aemt-cert.pem` / `aemt-key.pem`) |
| `pemt_certfile` / `pemt_keyfile` | `str` | Zertifikat + Schlüssel des PEMT (Standard: `pemt-cert.pem` / `pemt-key.pem`) |
| `cafile`    | `str` | WAN-CA, gegen die beide Seiten prüfen (Standard: `wan-ca.pem`) |

## TLS

Beide Verbindungen (PEMT → AEMT :8301, AEMT → PEMT :8202) nutzen gegenseitig
authentisiertes TLS 1.2 nach TR-03116-3 (`bdew_api.tls_config`):
ECDHE_ECDSA-Cipher-Suites, Kurve brainpoolP256r1, Client-Zertifikat Pflicht.

Benötigt werden je Seite ein ECDSA-Zertifikat mit Schlüssel auf der Kurve
brainpoolP256r1 (PEM) und das CA-Zertifikat, mit dem beide Zertifikate
signiert sind. Die Dateien werden standardmäßig im Arbeitsverzeichnis gesucht.
Fehlen sie oder sind sie unbrauchbar, wird eine Warnung (mit Dateinamen)
geloggt und die betroffene Seite bleibt inaktiv: Ihr Server startet nicht,
ihre Anfragen werden nicht gesendet (jeweils mit Warnung).
