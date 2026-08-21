# Adolar Produktfamilie - Integrationsstandards

Version: 1.0
Stand: 2026-08-21
Status: verbindlich fuer neue Integrationen, bestehende Produkte schrittweise
angleichen (siehe Abschnitt 6)

## 1. Zweck

Regeln fuer alles, was ein Adolar-Familienprodukt (Server-Client oder
Server-internes Modul) am `musicapp`-Server anfasst. Ziel: jedes Produkt
bleibt autark entwickelbar, ohne dass Aenderungen eines Produkts
unbeabsichtigt ein anderes brechen oder dessen Namensraum ueberschreiben.
Ergaenzt [PRODUCT_INTEGRATIONS.md](PRODUCT_INTEGRATIONS.md) (Ist-Stand-
Ledger) um die Soll-Regeln.

## 2. Namensraum-Prinzip

**Ein Produkt, ein Namensraum. Keine geteilten Felder/Spalten fuer zwei
Produkte.**

- **API-Routen**: produktspezifische Funktionalitaet unter
  `/api/<produkt>/*` (Vorbild: `/api/songster/*`, `adolar/songster/`
  als eigenes Package + Blueprint). Bestehende generische Routen
  (`/api/radio/login`, `/api/me-optional`, `/api/stream/<id>`, ...) bleiben
  geteilt nutzbar, wenn die Semantik wirklich produktunabhaengig ist -
  nicht faktisch nur von einem Produkt genutzt, aber allgemein benannt
  (siehe 6.1, Taggster-Beispiel).
- **DB-Spalten/Tabellen**: neue, produktspezifische Spalten tragen den
  Produktnamen im Feldnamen (Vorbild: `radio_stations.songster_enabled`,
  nicht eine Erweiterung des bestehenden `scope`-Felds - siehe Songster-
  Konzeptdokument Abschnitt 2, bewusste Entscheidung gegen Ueberladung
  bestehender Semantik). Vor dem Anlegen: `PRODUCT_INTEGRATIONS.md`
  pruefen, ob eine aehnliche Spalte/Tabelle schon fuer ein anderes Produkt
  existiert und wiederverwendbar waere.
- **Settings-Keys**: `<produkt>_enabled` in `control.settings`, Muster
  `get_setting`/`set_setting` wie bei `songster_enabled`/`adolar4u_enabled`.

## 3. Produkt-Identifikation

Jeder Client, der eigene Anfragen an den Server stellt (nicht: reine
Server-Templates wie Companion, siehe PRODUCT_INTEGRATIONS.md Abschnitt 2),
sendet den Header `X-Adolar-Product: <produkt>` auf jeder Anfrage.

**Bekannter Mangel (Stand 2026-08-21)**: Der Header wird aktuell nur an
zwei Stellen geprueft (`adolar/routes/auth.py:138-140`,
`adolar/routes/admin.py:131-134`) mit hart kodierten Allow-Lists
(`"companion"`/`"android"`). Bei jeder neuen Produktintegration: Allow-List
erweitern, langfristig auf eine zentrale, aus `control.settings` oder einer
Produkt-Registry gespeiste Pruefung umstellen statt wiederholt hart zu
kodieren.

Fuer Admin-Tools mit API-Token-Auth (Vorbild Taggster) gilt sinngemaess:
der `product`-Wert in `connection_log` wird aus dem Token-Datensatz
abgeleitet, nicht als Konstante in der Auth-Funktion hart kodiert (siehe
Taggster-Namenskollisions-Risiko in PRODUCT_INTEGRATIONS.md Abschnitt 4).

## 4. Client-Versionierung

Jeder neue Produkt-Client meldet seine Version an den Server:
- Bei Session-Login: Body-Feld `clientVersion` (Vorbild: Songster-
  Konzeptdokument Abschnitt 3.4).
- Bei API-Token-Auth: analoges Feld/Header bei Token-Nutzung.
- Server persistiert das in `connection_log` (neue Spalte, generisch fuer
  alle Produkte - nicht songster-spezifisch einfuehren, siehe
  PRODUCT_INTEGRATIONS.md Abschnitt 6.2).

Bestehende Produkte (Android, Companion, Disco, Taggster) melden aktuell
keine Version - beim naechsten groesseren Umbau eines dieser Clients
nachziehen.

## 5. Rate-Limiting

Aktuell existiert **keine** Rate-Limit-Infrastruktur im Server (kein
Flask-Limiter installiert). Fuer jede neue `/api/<produkt>/*`-Route-Gruppe:
- Grobe Schaetzung dokumentieren (Vorbild Songster: 60 req/min allgemein,
  10 req/min fuer Login) und in `PRODUCT_INTEGRATIONS.md` festhalten.
- Sobald die erste Route-Gruppe tatsaechlich Rate-Limiting braucht (z. B.
  Songster-Umsetzung Schritt 2), gemeinsame Limiter-Infrastruktur
  einfuehren statt pro Produkt eine eigene Loesung zu bauen.

## 6. Aenderungsprozess fuer neue/geaenderte Integrationen

1. Vor Beginn: `PRODUCT_INTEGRATIONS.md` lesen - Kollision mit
   bestehenden Routen/Spalten/Settings ausschliessen.
2. Integrationskonzept im **Satelliten-Repo** ablegen (Vorlage: Songsters
   `docs/Adolar_Songster_Adolar_Integration_Konzept_v1_*.md` - Struktur
   Ausgangslage -> Aenderungen Server -> Aenderungen Client -> offene
   Punkte -> Umsetzungsreihenfolge).
3. PR gegen `musicapp`: Commit-Praefix `[<produkt>] ...` (z. B.
   `[songster] add settings endpoint`), damit `git log --grep='^\[produkt\]'`
   je Produkt filterbar bleibt.
4. Gleiche PR aktualisiert die betroffene Sektion in
   `PRODUCT_INTEGRATIONS.md` (Pflichtbestandteil, nicht optional -
   Reviewer pruefen das analog zur Testpflicht).
5. CI-Gates aus Abschnitt 7 muessen gruen sein.
6. Bei Aenderungen an geteilten/generischen Routen (`/api/radio/login`,
   `/api/me-optional`, `connection_log`-Schema, `X-Adolar-Product`-Allow-
   Listen): Auswirkung auf **alle** Produkte in Abschnitt 6 von
   `PRODUCT_INTEGRATIONS.md` gegenpruefen, nicht nur das eigene.

## 7. CI/Security/Stability-Baseline (fuer den Server `musicapp` und alle
   Satelliten-Repos)

Diese Baseline gilt fuer `musicapp` sowie fuer jedes Satelliten-Repo
(Songster, Disco, Taggster, zukuenftige Produkte). Satelliten-Repos duerfen
ein eigenes, ausfuehrlicheres CI/Security-Dokument fuehren (Vorbild:
Songsters `docs/Adolar_Songster_CI_Security_Stability_v1_*.md`), sollen
dabei aber auf dieses Dokument verweisen statt die Baseline zu duplizieren,
damit Aenderungen an einer Stelle gepflegt werden.

**Pflicht-Quality-Gates vor Merge nach main/master:**
1. Linting (Frontend + Backend, je nach Repo)
2. Unit-Tests
3. Integrations-Tests (API + DB, wo zutreffend)
4. Build-Check
5. Security-Checks: Dependency-Vulnerability-Scan, Secret-Scan

**Security-Baseline:**
1. Secrets ausschliesslich ueber CI-Secrets/Umgebungsvariablen, nie im Repo.
2. Automatischer Secret-Scan in der PR-Pipeline.
3. Regelmaessige Dependency-Updates (Dependabot/Renovate o. ae.).
4. Kritische Schwachstellen blockieren Releases.
5. Neue Produktintegrationen, die Auth umgehen oder abschwaechen (z. B.
   unauthentifizierte Schreib-Routen wie beim Disco-BPM-Fund, siehe
   PRODUCT_INTEGRATIONS.md Abschnitt 3), muessen das explizit begruenden
   und dokumentieren - "war schon immer so" reicht nicht als Rechtfertigung
   bei neuen Routen.

**Stabilitaets-Baseline:**
1. Aenderungen an geteilten Routen/Tabellen (Abschnitt 6.6) brauchen
   Regressionstests fuer alle betroffenen Produkte, nicht nur das
   auftraggebende.
2. Reproduzierbare Testdaten fuer Kernflows.
3. Healthchecks fuer Server und DB.

## 8. Branding

Verweis auf die Branding-Vorgaben der PolzeSoft-Produktfamilie
(bereitgestellt/aktualisiert ueber `polzesoft`-Repo bzw. das
`adolar-whatsnew`-Skill fuer Changelog-/"Was gibt's Neues"-Pflege). Kein
separates Branding-Dokument pro Adolar-Satellit fuehren, um Drift zu
vermeiden.

## 9. Bekannte offene Punkte (Stand 2026-08-21)

- `X-Adolar-Product`-Allow-Listen sind hart kodiert an zwei Stellen -
  Kandidat fuer Generalisierung, sobald ein drittes Produkt (z. B.
  Songster Schritt 2) den Header ebenfalls braucht.
- Kein Rate-Limiting im Server vorhanden.
- Keine Client-Versionierung im Server vorhanden.
- Disco-BPM-Route (`POST /api/track/<id>/bpm`) wirkt auth-technisch
  inkonsistent mit ihrer `admin_required`-Dekoration - vor naechster
  Disco-Aenderung klaeren.
- Taggster-`product`-Wert in `connection_log` ist hart kodiert
  (`"taggster"`) statt aus dem Token-Datensatz abgeleitet.
