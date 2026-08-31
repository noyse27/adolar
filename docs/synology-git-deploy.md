# Synology Git-Deploy

Diese Notiz beschreibt den sicheren Wechsel von einer kopierten Adolar-Installation
zu Updates per `git pull` und `docker compose up -d --build`.

## Produktiver Ist-Stand auf Vault_II

Der aktuell laufende Container `adolar` nutzt:

```text
/volume1/music -> /music
/volume1/@docker/volumes/musicapp_adolar-data/_data -> /data
/volumeUSB1/usbshare/adolarDBbackup -> /backups
```

Das wichtige Detail ist der Compose-Projektname `musicapp`. Dadurch heisst das
produktive Datenvolume `musicapp_adolar-data`. Bei Updates diesen Projektnamen
beibehalten.

## Sichere Update-Regel

Vom Repo-Verzeichnis auf der Synology aus:

```sh
cd /volume1/docker/musicapp
./scripts/update-syno.sh
```

Das Skript verwendet intern:

```sh
docker compose -p musicapp up -d --build adolar
```

Es prueft vor dem Update, ob der bestehende Container `/data` weiterhin aus dem
Volume `musicapp_adolar-data` mountet. Wenn nicht, bricht es ab, damit Adolar
nicht versehentlich mit einer leeren neuen Datenbank startet.

## Nicht verwenden

```sh
docker compose down -v
docker volume rm musicapp_adolar-data
docker compose -p adolar up -d --build
```

`down -v` oder ein anderer Projektname kann produktive Daten entfernen oder ein
frisches leeres Volume verwenden.

## Vor der ersten Git-Umstellung

1. In Adolar unter **Wartung -> Datensicherung** eine manuelle Sicherung ausloesen.
2. Pruefen, dass das Backup unter `/volumeUSB1/usbshare/adolarDBbackup` sichtbar ist.
3. In `/volume1/docker/musicapp/.env` einen festen `SECRET_KEY` setzen:

   ```dotenv
   SECRET_KEY=<lange-zufaellige-hex-zeichenfolge>
   ```

   Beispiel zum Erzeugen auf der Synology:

   ```sh
   openssl rand -hex 32
   ```

   Ohne festen `SECRET_KEY` bleiben Daten und Einstellungen zwar erhalten, aber
   bestehende Browser-Sessions koennen nach Container-Neustarts ungueltig werden.

4. Danach einmal kontrollieren:

   ```sh
   docker inspect adolar --format '{{ range .Mounts }}{{ println .Source "->" .Destination }}{{ end }}'
   docker volume ls | grep adolar
   ```

## Erste Umstellung von Kopier-Deploy auf Git

Wenn `/volume1/docker/musicapp` aktuell nur eine kopierte Arbeitskopie ohne
`.git` ist, nicht mit `git init` und `reset --hard` im bestehenden Ordner
experimentieren. Sicherer ist ein frischer Checkout daneben:

```sh
cd /volume1/docker
git clone https://github.com/noyse27/adolar.git musicapp-git
cp musicapp/.env musicapp-git/.env
```

Dann den bestehenden Codeordner als Rueckfall behalten und den Git-Checkout an
seine Stelle bewegen:

```sh
docker compose -p musicapp -f /volume1/docker/musicapp/docker-compose.yml stop adolar
mv musicapp musicapp.pre-git
mv musicapp-git musicapp
cd musicapp
docker compose -p musicapp up -d --build adolar
curl http://localhost:15002/health
```

Das Docker-Volume `musicapp_adolar-data` bleibt dabei unangetastet. Der Ordner
`musicapp.pre-git` ist nur der alte Code-/Konfig-Rueckfall und kann nach ein paar
erfolgreichen Updates entfernt werden.

## Manuelles Update ohne Skript

```sh
cd /volume1/docker/musicapp
git pull --ff-only
docker compose -p musicapp up -d --build adolar
docker compose -p musicapp ps adolar
curl http://localhost:15002/health
```
