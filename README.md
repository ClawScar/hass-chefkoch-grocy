# Chefkoch → Grocy (Home Assistant Integration)

Importiert Rezepte von **chefkoch.de** mit einem Klick in das **Grocy**-Add-on von Home Assistant.

Dabei wird **nur das Rezept** angelegt: Name, Portionen, Zutaten und Zubereitung landen im
Rezept-Beschreibungstext. Es werden **keine Produkte, Zutatenstämme, Mengeneinheiten oder
Lagerbestände** in Grocy erzeugt – genau so, wie es für eine reine Rezeptsammlung gewünscht ist.

## Funktionen

- Einrichtung komplett über die Home-Assistant-Oberfläche (Config Flow, kein YAML)
- Service `chefkoch_grocy.import_recipe` – eine oder mehrere URLs in einem Aufruf
- mitgelieferte Lovelace-Karte `custom:chefkoch-grocy-card`: URL einfügen, Button drücken, fertig
- Zutaten + Zubereitung als Markdown-Beschreibung, Basisportionen aus dem Rezept
- Titelbild wird optional nach Grocy geladen
- Duplikat-Behandlung: überspringen / aktualisieren / zweites Rezept anlegen
- `not_check_shoppinglist` wird gesetzt, damit Grocy nicht nach fehlenden Zutaten fragt

## Voraussetzungen

- Home Assistant 2024.7 oder neuer
- Grocy-Add-on (oder eine andere Grocy-Instanz) mit API-Zugriff
- Internetzugang aus dem Heimnetz (Chefkoch blockt Rechenzentrums-/VPN-IPs)

## Installation

### Manuell

1. Ordner `custom_components/chefkoch_grocy` aus diesem Repository nach
   `/config/custom_components/chefkoch_grocy` kopieren.
2. Home Assistant neu starten.

### Über HACS

1. HACS → Integrationen → ⋮ → **Benutzerdefinierte Repositories**.
2. URL dieses Repositories eintragen, Kategorie **Integration**.
3. Integration installieren und Home Assistant neu starten.

## Grocy vorbereiten

1. Grocy öffnen → Zahnrad → **API-Schlüssel verwalten** → neuen Schlüssel anlegen.
2. Schlüssel kopieren.
3. URL des Grocy-Add-ons: `http://homeassistant.local:9283`
   (alternativ der interne Add-on-Hostname `http://a0d7b954-grocy`).
   Bei einer eigenen Installation die passende URL verwenden.

## Einrichtung in Home Assistant

**Einstellungen → Geräte & Dienste → Integration hinzufügen → „Chefkoch to Grocy“**

Dort Grocy-URL und API-Schlüssel eintragen. Die Verbindung wird sofort geprüft; bei falschem
Schlüssel erscheint eine Fehlermeldung direkt im Dialog.

## Benutzung

### Lovelace-Karte (einfachster Weg)

Karte hinzufügen → **Manuell** → folgenden Code einfügen:

```yaml
type: custom:chefkoch-grocy-card
title: Rezept importieren
```

Dann die Chefkoch-URL einfügen und **Importieren** drücken. Für mehrere Rezepte einfach
mehrere URLs untereinander schreiben.

### Service-Aufruf

```yaml
action: chefkoch_grocy.import_recipe
data:
  url: https://www.chefkoch.de/rezepte/15845/Kaesespaetzle.html
  existing: skip
  picture: true
response_variable: import_ergebnis
```

Die Antwort enthält pro URL ein Ergebnis:

```yaml
results:
  - url: https://www.chefkoch.de/rezepte/15845/Kaesespaetzle.html
    name: Käsespätzle
    recipe_id: 7
    action: created        # created | updated | skipped
    servings: 4
    ingredients: 3
    steps: 3
```

Bei Fehlern steht statt der Felder `error` im Ergebnis (z. B. wenn Chefkoch mit HTTP 403
antwortet). Schlägt jede URL fehl, wird der Service mit einer Fehlermeldung abgebrochen.

### Parameter

| Feld | Pflicht | Standard | Bedeutung |
| --- | --- | --- | --- |
| `url` | ja | – | Chefkoch-Rezeptlink; mehrere URLs durch Leerzeichen/Zeilenumbrüche |
| `existing` | nein | `skip` | `skip`, `overwrite` oder `create` bei gleichem Rezeptnamen |
| `picture` | nein | `true` | Titelbild nach Grocy laden |
| `servings` | nein | Chefkoch-Angabe | Portionen überschreiben |
| `entry_id` | nein | – | nur bei mehreren Grocy-Instanzen nötig |

## Was in Grocy ankommt

- **Name**: Rezepttitel von Chefkoch
- **Basisportionen / gewünschte Portionen**: Portionsangabe des Rezepts (Standard 4)
- **Beschreibung**: Markdown mit Kurzbeschreibung, Zeit, Kategorie, Autor, Quellenlink,
  Zutatenliste und nummerierter Zubereitung
- **Bild**: optional, abgelegt unter `data/storage/recipes/`
- **Typ**: `normal`
- **Rezeptpositionen**: keine – dadurch entstehen keine Produkte und keine Lagerbuchungen

Beispiel-Beschreibung:

```markdown
Klassische Käsespätzle wie bei Oma – einfach und cremig.

**Zeit:** 50 Min.
**Portionen:** 4
**Kategorie:** Aufläufe
**Quelle:** [chefkoch.de](https://www.chefkoch.de/rezepte/15845/Kaesespaetzle.html)

## Zutaten (4 Portionen)
- 500 g Mehl
- 4 Eier
- 200 g Bergkäse, gerieben

## Zubereitung
1. Mehl, Eier und Salz zu einem zähen Teig verkneten.
2. Teig portionsweise ins kochende Wasser schaben.
3. Schichten, mit Käse bestreuen und überbacken.
```

## Hinweise und Grenzen

- **HTTP 403 von Chefkoch**: Chefkoch blockt Anfragen von Rechenzentrums- und VPN-IPs. Aus dem
  normalen Heimnetz funktioniert der Abruf; ein aktivierter VPN-Zugang im Router kann stören.
- Es werden nur öffentlich erreichbare Rezepte importiert (kein Chefkoch-Login).
- Zutaten werden bewusst **nicht** als Grocy-Produkte angelegt; sie stehen ausschließlich im
  Rezepttext.
- Der Import legt ein Rezept an, dessen Zutaten nicht überprüfbar sind – deshalb ist
  „Einkaufsliste nicht prüfen“ aktiv, damit Grocy keine fehlenden Produkte meldet.
- Bei `existing: overwrite` wird der Beschreibungstext des vorhandenen Rezepts ersetzt.
- Es wird kein Polling betrieben; die Integration arbeitet ausschließlich auf Service-Aufruf.

## Dateien

```
custom_components/chefkoch_grocy/
├── __init__.py                     Setup, Service, Karten-Registrierung
├── config_flow.py                  Einrichtung über die UI
├── chefkoch.py                     Abruf von chefkoch.de
├── parser.py                       JSON-LD-Parser (nur Standardbibliothek)
├── grocy.py                        Grocy-REST-Client
├── const.py                        Konstanten
├── manifest.json
├── services.yaml
├── strings.json / translations/    Übersetzungen (de, en)
└── frontend/chefkoch-grocy-card.js Lovelace-Karte
tests/                              Parser-Tests (python -m unittest)
hacs.json                           HACS-Metadaten
```

Tests ausführen:

```bash
python -m unittest discover -s tests -v
```

## Lizenz

MIT
