#!/bin/sh
# Generates a small library of synthetic placeholder MP3s for the isolated
# demo deployment (see ../docker-compose.demo.yml). Real music is never
# checked into this repository - normal deployments point MUSIC_ROOT at the
# operator's own library. A public demo has no such source, and bundling
# real songs would be a copyright problem anyway, so this generates
# clearly-fake placeholder tracks (a sine-wave tone, tagged with fake
# metadata) entirely with ffmpeg's built-in lavfi source - no audio files of
# any kind are shipped or downloaded.
#
# Runs once as a one-shot compose service (see the "demo-library" service in
# docker-compose.demo.yml), writing into the shared demo_music volume that
# the backend then mounts read-only at MUSIC_ROOT, same shape a real
# deployment uses for its own music share.
set -eu

OUT_DIR="${OUT_DIR:-/music}"
DURATION="${TRACK_DEMO_CLIP_SECONDS:-8}"

mkdir -p "$OUT_DIR"

# artist|album|year|genre|title1;title2;title3;title4|base-frequency-hz
# Three fictional artists spanning different decades/genres, four tracks
# each, so the demo library has enough variety for search, playlists, and
# genre/year filtering to make sense.
ARTISTS='
Die Funkelfische|Blaue Stunde|1998|Elektro|Morgentau;Kurzschluss;Regentanz;Nachglühen|220
Klanggarten|Wurzelwerk|2011|Indie|Lichtung;Moosgrün;Zugvögel|294
Stahlchor|Feuerprobe|1985|Rock|Sturmlauf;Funkenflug;Eisenwind;Höhenfeuer;Letzter Zug|349
'

track_index=0
echo "$ARTISTS" | while IFS='|' read -r artist album year genre titles base_freq; do
  [ -z "$artist" ] && continue
  artist_dir="${OUT_DIR}/${artist}/${album}"
  mkdir -p "$artist_dir"

  track_no=0
  old_ifs="$IFS"
  IFS=';'
  for title in $titles; do
    IFS="$old_ifs"
    track_no=$((track_no + 1))
    track_index=$((track_index + 1))
    # Each track a slightly different pitch, purely so they're not bit-
    # identical files - not meant to sound musical.
    freq=$((base_freq + track_no * 11))
    out_path="${artist_dir}/${track_no} - ${title}.mp3"

    if [ -f "$out_path" ]; then
      echo "generate-library: '$out_path' already exists, skipping"
      continue
    fi

    echo "generate-library: rendering '$out_path'"
    ffmpeg -y -nostdin -loglevel error \
      -f lavfi -i "sine=frequency=${freq}:duration=${DURATION}" \
      -metadata title="$title" \
      -metadata artist="$artist" \
      -metadata album="$album" \
      -metadata genre="$genre" \
      -metadata date="$year" \
      -metadata track="$track_no" \
      -id3v2_version 3 \
      -c:a libmp3lame -b:a 96k \
      "$out_path" < /dev/null
    IFS=';'
  done
  IFS="$old_ifs"
done

echo "generate-library: done, $(find "$OUT_DIR" -name '*.mp3' | wc -l) track(s) in $OUT_DIR"
