# Adolar Produktfamilie - Integrations-Ledger

Version: 1.0
Stand: 2026-08-21
Status: Ist-Stand-Dokumentation (aus Code recherchiert), lebendes Dokument

## Zweck

Dieses Dokument listet fuer jedes Produkt der Adolar-Familie, welche
Adolar-Server-Ressourcen es belegt: API-Routen, Auth-Mechanismus,
Settings-Keys, DB-Spalten/Tabellen, Rate-Limits, Versionierung. Ziel: bevor
ein Produkt (bestehend oder neu) am Adolar-Server etwas aendert, hier
nachsehen, was andere Produkte bereits nutzen, um Kollisionen zu vermeiden.

Aktualisierungspflicht: Jede PR, die eine neue Route/Spalte/Setting fuer
ein Produkt einfuehrt oder ein bestehendes Verhalten fuer ein Produkt
aendert, aktualisiert die betroffene Sektion in diesem Dokument. Siehe
[INTEGRATION_STANDARDS.md](INTEGRATION_STANDARDS.md) Abschnitt 5.

Repo-Uebersicht:

| Produkt | Repo | Beziehung zu `musicapp` |
|---|---|---|
| Adolar (Server) | `musicapp` | ist der Server |
| Adolar Android / Android Next | `musicapp/adolar-android` | selbes Repo, Unterverzeichnis |
| Adolar Radio Companion | `musicapp/companion` | selbes Repo, Unterverzeichnis (siehe 2., Sonderfall) |
| Adolar Disco | `adolar-disco` | eigenes, autarkes Repo |
| Adolar Taggster | `tagmegently` | eigenes, autarkes Repo |
| Adolar Songster | `adolar-songster` | eigenes, autarkes Repo |

---

## 1. Adolar Android / Android Next

**Repo**: `musicapp/adolar-android` (selbes Repo wie Server - jede
Server-Aenderung ist im selben Commit/PR sichtbar, kein Sync-Risiko im
klassischen Sinn, aber Coupling-Risiko bei geteilten Routen, siehe unten).

- **Auth/Identifikation**: Header `X-Adolar-Product: android`
  (`AdolarMediaService.java:833,1228`). Login ueber `POST /api/radio/login`
  (`MainActivity.java:915`), Session-Cookie `adolar_session`. Logout `POST
  /api/radio/logout` (`MainActivity.java:960`).
- **Genutzte Routen**: `/api/me-optional`, `/api/radio/login`,
  `/api/radio/logout`, `/api/favorites`, `/api/favorites/<id>`,
  `/api/lastfm/status`, `/api/lastfm/loved`, `/api/lastfm/love`,
  `/api/tracks/<id>/lyrics`, `/api/tracks/<id>/lyrics/fetch`,
  `/api/radio-stations`, `/api/radio-stations/<id>/tracks`,
  `/api/stream/<id>`, `/api/adolar4u/events/<track_id>`,
  `/api/client/heartbeat`, `/api/cover/<hash>`.
- **Settings/Feature-Flags**: keine Android-spezifischen; teilt sich den
  generischen `"android"`-Produktwert in `adolar/routes/auth.py:139` und
  `adolar/routes/admin.py:133`.
- **DB-Schema**: keine Android-eigenen Spalten/Tabellen; schreibt in die
  geteilte `connection_log`-Tabelle.
- **Rate-Limits**: keine (nur genereller Brute-Force-Schutz auf
  `/api/radio/login`, `adolar/auth.py:24-29`, produktunabhaengig).
  Sofern ihr Ihr eigenen limiter fuer Produkte einfuehrt.
- **Versionierung**: `BuildConfig.VERSION_NAME` wird nur lokal in der
  App-UI angezeigt, **nicht** an den Server gemeldet.

---

## 2. Adolar Radio Companion

**Repo**: `musicapp/companion` (selbes Repo wie Server).

**Sonderfall**: Companion hat de facto keinen eigenen Client-Code. Die
`.exe` (`companion/adolar_radio.py`) ist eine pywebview-Huelle, die
lediglich `<server-url>/radio` und `<server-url>/radio/settings` laedt
(`adolar_radio.py:171-172,195-197,238-242`). Die eigentliche API-Nutzung
(Login, `/api/me-optional`, Logout) passiert im server-seitigen Template
`templates/radio_settings.html`, das im Webview als JS laeuft. "Companion
integrieren" bedeutet also faktisch "die `/radio*`-Routen/Templates im
Server pflegen" - es gibt keine Versions-Trennung: Companion bekommt bei
jeder Verbindung genau das HTML, das der Server aktuell ausliefert.

- **Auth/Identifikation**: Header `X-Adolar-Product: companion`
  (`templates/radio_settings.html:192-199`), gleiche
  Login-/Logout-/me-optional-Routen wie Android, gleicher
  Session-Mechanismus (`adolar/routes/auth.py:112-161`, Default-Produktwert
  ist `"companion"` bei Zeile 138, wenn Header fehlt/unbekannt ist).
- **Settings/Feature-Flags**: keine.
- **DB-Schema**: keine eigenen; geteilte `connection_log`/`sessions`.
- **Rate-Limits**: keine (siehe Android).
- **Versionierung**: nicht gefunden.

---

## 3. Adolar Disco

**Repo**: `adolar-disco` (autark).

- **Auth/Identifikation**: **keine.** Unauthentifizierte
  `requests.get`/`.post` (`server/sources/adolar_source.py:19-20`). Server
  fuehrt Disco explizit als oeffentlichen, unauthentifizierten Traffic
  (`adolar/auth.py:37`, `PUBLIC_SUFFIXES = ("/disco-played",)` bei
  `adolar/auth.py:43`). "Ist Disco verbunden" wird rein ueber einen
  Timestamp erkannt (`_touch_disco()`/`_disco_active()`,
  `adolar/application.py:150-217`), nicht ueber Identitaet.
- **Genutzte Routen**: `GET /api/search`, `GET /api/random`, `GET
  /api/genres`, `GET /api/cover/<hash>`, `GET /api/stream/<id>` (alle
  oeffentlich), `POST /api/track/<id>/bpm` (`adolar-disco/server/bpm.py:23-33`
  ↔ Server-Route `adolar/routes/media.py:276-285`), `POST
  /api/track/<id>/disco-played` (`adolar/routes/media.py:312-319`).
- **Settings/Feature-Flags**: keine (kein `disco_enabled`-Schalter; Praesenz
  wird rein aus Traffic abgeleitet).
- **DB-Schema**: System-Smart-Playlist `("Disco Hits", "disco_top", "{}")`
  (`adolar/db.py:556`), `disco_top`-Sortierschluessel und `user_id=0` als
  "disco"-Bucket in der Playcount-Aggregation (`db.py:854,857,876`).
- **Rate-Limits**: keine.
- **Versionierung**: nicht gefunden.
- **Bekanntes Problem (unverifiziert, zu klaeren)**: `bpm.py` sendet `POST
  /api/track/<id>/bpm` ohne jeden Auth-Header, die Server-Route ist aber
  mit `@_auth.admin_required` dekoriert (`adolar/routes/media.py:277`) und
  `/api/track/<id>/bpm` steht **nicht** in den Public-Listen
  (`adolar/auth.py:32-43` deckt nur den Plural-Pfad `/api/tracks/` und den
  `/disco-played`-Suffix ab). Sieht nach einem Aufruf aus, der im
  aktuellen Code immer mit 401 scheitert - separat pruefen, siehe Hinweis
  am Ende dieses Dokuments.

---

## 4. Adolar Taggster

**Repo**: `tagmegently` (autark).

- **Auth/Identifikation**: Langlebige **API-Tokens** via `Authorization:
  Bearer <token>` (`tagger.py:2739,2773,3839,3919,3949,3995,4001`),
  konfiguriert im "Adolar verbinden"-Dialog (`tagger.py:2605-2641`).
  Server: dedizierter Token-Pfad getrennt von Session-Cookies
  (`adolar/auth.py`: `get_user_by_api_token`, `create_api_token`,
  `revoke_api_token`, `list_api_tokens`). Jede Token-Nutzung aktualisiert
  Praesenz via `touch_api_token()`, das einen `client_key` der Form
  `f"{product}-token-{id}"` synthetisiert, `product` dabei aus der neuen
  `api_tokens.product`-Spalte gelesen (Default `"taggster"` fuer
  Bestandstoken, siehe Namenskollisions-Risiko unten - **geloest**).
- **Genutzte Routen**: `GET /api/me`, `GET /api/admin/libraries`, `POST
  /api/scan/start`, `POST /api/admin/libraries/<id>/rename-path`.
- **Settings/Feature-Flags**: keine `taggster_enabled`-Einstellung; Zugriff
  haengt allein davon ab, ob das Token einem aktiven Nutzer gehoert - ein
  API-Token mit Admin-Faehigkeit gewaehrt vollen Admin-Routenzugriff, keine
  auf "taggster" beschraenkte Berechtigung.
- **DB-Schema**: generische `api_tokens`-Tabelle (jetzt mit `product`-Spalte,
  siehe Songster unten), geteilte `connection_log` (jetzt mit
  `client_version`-Spalte).
- **Rate-Limits**: keine. Der Login-Brute-Force-Schutz
  (`adolar/auth.py:24-29`) gilt nur fuer `/api/radio/login`, nicht fuer
  Token-authentifizierte Routen - wiederholtes Token-Raten wird nicht
  gedrosselt.
- **Versionierung**: nicht gefunden.
- **Namenskollisions-Risiko (geloest 2026-08-21)**: `touch_api_token()`
  labelte frueher jede Token-Verbindung fest als `"taggster"`. Jetzt liest
  `create_api_token(user_id, name, product)` einen validierten
  `product`-Wert (`auth.KNOWN_PRODUCTS`) und `touch_api_token()` verwendet
  ihn statt der Konstante - siehe Abschnitt 5 (Songster), das der erste
  Nutzer des generalisierten Mechanismus ist.

---

## 5. Adolar Songster

**Repo**: `adolar-songster` (autark).
**Konzeptdokument**: `adolar-songster/docs/Adolar_Songster_Adolar_Integration_Konzept_v1_20260821.md`

Umsetzungsstand (Stand 2026-08-21): **teilweise implementiert (Schritt 1+2 von 3).**

Bereits umgesetzt:
- Globaler Schalter `songster_enabled`, persistiert ueber
  `control.settings` (Muster wie Adolar4U) - `adolar/songster/service.py`.
- `GET /api/songster/status` (session-authentifiziert) -
  `adolar/routes/songster.py`.
- `GET/PUT /api/admin/songster/settings` (admin-only, audit-geloggt) -
  `adolar/routes/songster.py`.
- Neue Spalte `radio_stations.songster_enabled` (`adolar/db.py`),
  Songster-Sender werden aus der normalen Sender-Listung ausgeschlossen
  (`db.list_radio_stations`) und stattdessen ueber `db.list_songster_playlists`
  separat gelistet.
- Eigenes Package `adolar/songster/`, Blueprint registriert
  (`adolar/routes/__init__.py`), Tests in `tests/test_songster.py`.
- **Schritt 2 (neu)**: Server-zu-Server-Datenzugriff fuer den Songster-
  Spielserver, **nicht** wie urspruenglich im Konzeptdokument geplant per
  eigenem Session-Login-Endpoint, sondern ueber den bestehenden
  API-Token-Mechanismus (Bearer, wie Taggster - siehe
  INTEGRATION_STANDARDS.md Abschnitt 3 und Abschnitt 4 oben):
  - `api_tokens.product` (neue Spalte, Default `"taggster"` fuer
    Bestandstoken) - ein Admin legt fuer den Songster-Spielserver ein Token
    mit `product="songster"` unter `POST /api/admin/tokens` an.
  - `GET /api/songster/playlists` - listet alle `songster_enabled`-Sender
    (`db.list_songster_playlists`); nur mit Bearer-Token `product="songster"`
    UND globalem Schalter `enabled=true` erreichbar
    (`_songster_token_required` in `adolar/routes/songster.py`).
  - `GET /api/songster/playlists/<id>/tracks?limit=&offset=` - vollstaendiger,
    deterministisch nach `t.id` sortierter Track-Pool eines Senders
    (`db.list_songster_playlist_tracks`); liefert `id`, `title`, `artist`,
    `album`, `genre`, `year` (`COALESCE(original_year, year)`), `duration`.
    Bewusst **keine** Zufallsauswahl serverseitig - Songsters eigener
    Batch-Algorithmus (Jahresspreizung, ein Interpret pro Batch,
    `last_played_at`-Malus) laeuft clientseitig auf dem vollen Pool.
  - `connection_log.client_version` (neue Spalte) - generischer
    Client-Versions-Header `X-Adolar-Client-Version` wird bei jedem
    Bearer-Aufruf mitgeschrieben (nicht songster-spezifisch, siehe
    Abschnitt 6 Punkt 2 - jetzt geloest).
  - Kein eigener Login-Endpoint (`/api/songster/login` aus dem
    Konzeptdokument entfaellt) - das Bearer-Token ersetzt ihn vollstaendig.

Noch nicht umgesetzt (naechste Schritte laut Konzeptdokument):
- Kein `X-Adolar-Product: songster` Header-Handling fuer den Browser-
  Session-Pfad (aktuell nur `android`/`companion` erkannt,
  `adolar/routes/auth.py`, `adolar/routes/admin.py`) - wird fuer den
  Spielserver nicht benoetigt (Bearer-Token statt Session), bleibt fuer
  Schritt 3 (Admin-UI) relevant, falls das Songster-Verwaltungs-Frontend
  selbst als Adolar-Web-Client identifiziert werden soll.
- Keine Rate-Limits (60/min allgemein, 10/min Login sind Konzept, noch
  nicht gebaut - siehe auch Abschnitt 6, generelles Rate-Limit-Defizit).
- Kein Admin-UI-Toggle in Templates/`app.js` fuer `songster_enabled`, keine
  "Songster Playlists"-Verwaltungsdialoge (Play-Button = Freischalten,
  Zahnrad = Bearbeiten, Papierkorb = Loeschen) - Backend-Endpoints
  existieren, Frontend (Schritt 3) fehlt noch.

---

## 6. Produktuebergreifende Beobachtungen (Risiken fuer neue Integrationen)

1. **`X-Adolar-Product`-Header ist kein allgemeiner Mechanismus.** Er wird
   nur an zwei Stellen geprueft (Login `auth.py:138-140`, Heartbeat
   `admin.py:131-134`) und akzeptiert dort hart kodiert nur
   `"companion"`/`"android"` bzw. `"adolar_web"/"companion"/"android"`.
   Disco, Taggster und Songster (aktuell) nutzen ihn gar nicht. **Bei jeder
   neuen Produktintegration**: diese beiden Allow-Lists erweitern oder den
   Mechanismus generalisieren (siehe INTEGRATION_STANDARDS.md).
2. **Client-Versionierung (geloest 2026-08-21 im Rahmen von Songster
   Schritt 2).** Neue Spalte `connection_log.client_version`, generisch
   ueber den Header `X-Adolar-Client-Version` auf dem Bearer-Token-Pfad
   (`adolar/auth.py: before_request`) befuellt - nicht songster-spezifisch,
   von jedem API-Token-Client nutzbar (aktuell nur von Songster gesendet;
   Taggster kann jederzeit nachziehen).
3. **Keine Rate-Limits irgendwo im System.** `Flask-Limiter` ist nicht
   installiert. Einzige Drosselung ist der IP-basierte
   Brute-Force-Schutz auf `/api/radio/login`, produktunabhaengig.
4. **`connection_log`/`sessions`/`api_tokens` sind geteilte, generische
   Tabellen**, genutzt von Android/Companion/Taggster - Disco hinterlaesst
   dort gar keine Spur (nie authentifiziert).
5. **Disco BPM-Schreibpfad wirkt auth-technisch kaputt** (siehe Abschnitt
   3) - vor der naechsten Disco-Aenderung klaeren, ob das ein Bug oder
   bewusst unvollstaendig ist.
