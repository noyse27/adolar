const API = "";
const $ = id => document.getElementById(id);

const connectionClientId = sessionStorage.getItem("adolar-connection-id")
  || (globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}`);
sessionStorage.setItem("adolar-connection-id", connectionClientId);

function sendConnectionHeartbeat() {
  fetch("/api/client/heartbeat", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({product: "adolar_web", client_id: connectionClientId}),
    keepalive: true,
  }).catch(() => {});
}
sendConnectionHeartbeat();
setInterval(sendConnectionHeartbeat, 30000);

// ── i18n ──────────────────────────────────────────────────
const LANG = {
  de: {
    loading:          "Lade…",
    artist:           "Interpret",
    title_filter:     "Titel",
    album_filter:     "Album",
    genre:            "Genre",
    decade:           "Jahrzehnt",
    length:           "Länge",
    year:             "Jahr",
    year_from:        "Von",
    year_to:          "Bis",
    format:           "Format",
    min_bitrate:      "Mindest-Bitrate",
    all:              "Alle",
    wartung:          "Wartung",
    monitor:          "Monitor",
    scan_lib:         "Bibliothek scannen",
    scanning:         "Bibliothek wird gescannt…",
    bpm_tags:         "BPM-Tags einlesen",
    bpm_calc:         "BPM berechnen",
    search_ph:        "Titel, Interpret, Album durchsuchen…",
    artist_search_ph: "Interpret suchen…",
    title_search_ph:  "Titel suchen…",
    album_search_ph:  "Album suchen…",
    mobile_filters:   "Filter",
    close_filters:    "Filter schließen",
    sort_artist:      "Interpret A–Z",
    sort_title:       "Titel A–Z",
    sort_album:       "Album A–Z",
    sort_year:        "Nach Jahr",
    sort_duration:    "Nach Dauer",
    sort_top_played:  "Meistgespielt",
    sort_loved_at:    "Zuletzt geliked",
    radio:            "Radio",
    radio_manage:     "Radiosender",
    radio_new:        "Neuer Sender",
    radio_save:       "Speichern unter",
    radio_test:       "Testen",
    radio_name:       "Sendername",
    radio_desc:       "Beschreibung",
    radio_delete_confirm: (name) => `Radiosender „${name}" löschen?`,
    radio_all_rules:  "Alles der folgenden",
    radio_any_rules:  "Eines der folgenden",
    radio_add_rule:   "Regel hinzufügen",
    radio_start:      "Sender starten",
    radio_edit:       "Sender bearbeiten",
    radio_delete:     "Sender löschen",
    radio_no_stations:"Keine Sender gefunden.",
    radio_jingle:     "Jingle / Station-ID",
    radio_jingle_every:"alle N Tracks",
    basket:           "Korb",
    basket_empty:     "Korb ist leer",
    basket_download:  "Als ZIP herunterladen",
    basket_packing:   "Packe ZIP…",
    basket_error:     "Download fehlgeschlagen.",
    basket_remove:    "Entfernen",
    basket_add:       "Zum Korb hinzufügen",
    basket_rm:        "Aus Korb entfernen",
    play:             "Abspielen",
    pause:            "Pause",
    prev:             "Zurück",
    next:             "Weiter",
    shuffle:          "Shuffle",
    crossfade:        "Crossfade",
    radio_exit:       "Radio beenden und Bibliothek anzeigen",
    pg_prev:          "‹ Zurück",
    pg_next:          "Weiter ›",
    pg_info:          (p, t) => `Seite ${p} / ${t}`,
    results:          (n) => `${n.toLocaleString("de")} Tracks`,
    results_q:        (n, q) => `${n.toLocaleString("de")} Ergebnisse für „${q}"`,
    radio_loading:    "Radio – …",
    radio_tracks:     (n) => `Radio – ${n} Tracks`,
    radio_return:     "Aktuelles Radio anzeigen",
    no_tracks:        "Keine Tracks gefunden.",
    mini_title:       "Mini-Player abdocken",
    now_playing:      "Es läuft",
    queue:            "Warteschlange",
    open_player:      "Player öffnen",
    close_player:     "Player schließen",
    queue_empty:      "Keine weiteren Titel.",
    lfm_love:         "Bei Last.fm liken",
    lfm_unlove:       "Nicht mehr mögen (Last.fm)",
    lfm_connect:      "Last.fm verbinden",
    lfm_disconnect:   "Trennen",
    lfm_loved_filter:   "Loved in Last.fm",
    lfm_loved_sync:     "Loved laden",
    lfm_loved_syncing:  "Wird geladen…",
    lfm_pc_sync:        "Plays laden",
    lfm_pc_syncing:     (done, total) => `Plays: ${done}/${total}…`,
    bm_add:             "Zu Playlist hinzufügen",
    bm_new_playlist:    "Neue Playlist erstellen",
    bm_new_prompt:      "Name der neuen Playlist:",
    pl_delete_confirm:  (name) => `Playlist „${name}" löschen?`,
    user_delete_confirm: "Benutzer wirklich löschen?",
    album_results:       (n) => `${n.toLocaleString("de")} Alben`,
    no_albums:            "Keine Alben gefunden.",
    album_open_hint:      "Doppelklick zum Öffnen",
    album_open_btn_title: "Album öffnen",
    album_tracks_short:   (n) => `${n} Titel`,
    back_to_albums:       "Zurück zu den Alben",
    album_tracks_count:   (n, album) => `${n} Titel · „${album}"`,
  },
  en: {
    loading:          "Loading…",
    artist:           "Artist",
    title_filter:     "Title",
    album_filter:     "Album",
    genre:            "Genre",
    decade:           "Decade",
    length:           "Length",
    year:             "Year",
    year_from:        "From",
    year_to:          "To",
    format:           "Format",
    min_bitrate:      "Min. Bitrate",
    all:              "All",
    scan_lib:         "Scan library",
    scanning:         "Scanning library…",
    search_ph:        "Search title, artist, album…",
    artist_search_ph: "Search artist…",
    title_search_ph:  "Search title…",
    album_search_ph:  "Search album…",
    mobile_filters:   "Filters",
    close_filters:    "Close filters",
    sort_artist:      "Artist A–Z",
    sort_title:       "Title A–Z",
    sort_album:       "Album A–Z",
    sort_year:        "By year",
    sort_duration:    "By duration",
    sort_top_played:  "Most played",
    sort_loved_at:    "Last liked",
    radio:            "Radio",
    radio_manage:     "Radio stations",
    radio_new:        "New station",
    radio_save:       "Save as",
    radio_test:       "Test",
    radio_name:       "Station name",
    radio_desc:       "Description",
    radio_delete_confirm: (name) => `Delete radio station "${name}"?`,
    radio_all_rules:  "All of the following",
    radio_any_rules:  "Any of the following",
    radio_add_rule:   "Add rule",
    radio_start:      "Start station",
    radio_edit:       "Edit station",
    radio_delete:     "Delete station",
    radio_no_stations:"No stations found.",
    radio_jingle:     "Jingle / station ID",
    radio_jingle_every:"every N tracks",
    basket:           "Cart",
    basket_empty:     "Cart is empty",
    basket_download:  "Download as ZIP",
    basket_packing:   "Packing ZIP…",
    basket_error:     "Download failed.",
    basket_remove:    "Remove",
    basket_add:       "Add to cart",
    basket_rm:        "Remove from cart",
    play:             "Play",
    pause:            "Pause",
    prev:             "Previous",
    next:             "Next",
    shuffle:          "Shuffle",
    crossfade:        "Crossfade",
    radio_exit:       "Stop radio and show library",
    pg_prev:          "‹ Back",
    pg_next:          "Next ›",
    pg_info:          (p, t) => `Page ${p} / ${t}`,
    results:          (n) => `${n.toLocaleString("en")} tracks`,
    results_q:        (n, q) => `${n.toLocaleString("en")} results for "${q}"`,
    radio_loading:    "Radio – …",
    radio_tracks:     (n) => `Radio – ${n} tracks`,
    radio_return:     "Show current radio",
    no_tracks:        "No tracks found.",
    mini_title:       "Pop out mini-player",
    now_playing:      "Now playing",
    queue:            "Queue",
    open_player:      "Open player",
    close_player:     "Close player",
    queue_empty:      "No more tracks.",
    wartung:          "Maintenance",
    monitor:          "Monitor",
    bpm_tags:         "Read BPM tags",
    bpm_calc:         "Calculate BPM",
    lfm_love:         "Love on Last.fm",
    lfm_unlove:       "Unlove on Last.fm",
    lfm_connect:      "Connect Last.fm",
    lfm_disconnect:   "Disconnect",
    lfm_loved_filter:    "Loved in Last.fm",
    lfm_loved_sync:      "Load loved",
    lfm_loved_syncing:   "Loading…",
    lfm_pc_sync:         "Load plays",
    lfm_pc_syncing:      (done, total) => `Plays: ${done}/${total}…`,
    bm_add:              "Add to playlist",
    bm_new_playlist:     "New playlist",
    bm_new_prompt:       "New playlist name:",
    pl_delete_confirm:   (name) => `Delete playlist "${name}"?`,
    user_delete_confirm: "Really delete user?",
    album_results:       (n) => `${n.toLocaleString("en")} albums`,
    no_albums:            "No albums found.",
    album_open_hint:      "Double-click to open",
    album_open_btn_title: "Open album",
    album_tracks_short:   (n) => `${n} tracks`,
    back_to_albums:       "Back to albums",
    album_tracks_count:   (n, album) => `${n} tracks · "${album}"`,
  },
};

let lang = localStorage.getItem("adolar-lang") || "de";
const t = () => LANG[lang];

function setLang(l) {
  lang = l;
  localStorage.setItem("adolar-lang", l);
  applyLang();
}

function applyLang() {
  const L = t();
  // Topbar
  $("topbar-meta").textContent || ($("topbar-meta").textContent = L.loading);
  $("btn-miniplayer").title = L.mini_title;
  $("basket-label").textContent = L.basket;
  $("basket-empty").textContent = L.basket_empty;
  $("btn-basket-download").innerHTML = `<i class="ti ti-device-floppy"></i> ${L.basket_download}`;
  // Sidebar labels
  document.querySelectorAll(".filter-label").forEach(el => {
    const key = el.dataset.i18n;
    if (key && L[key]) el.textContent = L[key];
  });
  // Sidebar "Alle" chips
  document.querySelectorAll(".chip-alle").forEach(el => el.textContent = L.all);
  // Wartung toggle label (spans use data-i18n, handled above)
  // Search
  $("search").placeholder = L.search_ph;
  $("artist-search").placeholder = L.artist_search_ph;
  $("title-search").placeholder = L.title_search_ph;
  $("album-search").placeholder = L.album_search_ph;
  $("album-back-btn-label").textContent = L.back_to_albums;
  const mobileFilterBtn = $("btn-mobile-filter");
  if (mobileFilterBtn) mobileFilterBtn.title = L.mobile_filters;
  const mobileFilterTitle = $("mobile-filter-title");
  if (mobileFilterTitle) mobileFilterTitle.textContent = L.mobile_filters;
  const mobileFilterClose = $("btn-mobile-filter-close");
  if (mobileFilterClose) mobileFilterClose.title = L.close_filters;
  updateLovedFilterButton(false);
  // Sort options
  const sortMap = { artist: "sort_artist", title: "sort_title", album: "sort_album", year: "sort_year", duration: "sort_duration", top_played: "sort_top_played", loved_at: "sort_loved_at" };
  document.querySelectorAll("#sort-select option").forEach(o => {
    const k = sortMap[o.value];
    if (k) o.textContent = L[k];
  });
  // Player controls
  $("btn-prev").title = L.prev;
  $("btn-next").title = L.next;
  $("btn-list-shuffle").title = L.shuffle;
  $("btn-list-shuffle").setAttribute("aria-label", L.shuffle);
  $("btn-crossfade").title = L.crossfade;
  $("btn-crossfade").setAttribute("aria-label", L.crossfade);
  $("player-love").title = L.lfm_love;
  $("player-cover-wrap").title = L.open_player;
  $("player-cover-wrap").setAttribute("aria-label", L.open_player);
  $("btn-play-view-open").title = L.open_player;
  $("btn-play-view-open").setAttribute("aria-label", L.open_player);
  $("play-view-close").title = L.close_player;
  $("play-view-close").setAttribute("aria-label", L.close_player);
  $("play-view-kicker").textContent = L.now_playing;
  $("play-view-queue-title").textContent = L.queue;
  $("play-view-prev").title = L.prev;
  $("play-view-prev").setAttribute("aria-label", L.prev);
  $("play-view-next").title = L.next;
  $("play-view-next").setAttribute("aria-label", L.next);
  $("play-view-shuffle").title = L.shuffle;
  $("play-view-shuffle").setAttribute("aria-label", L.shuffle);
  $("play-view-crossfade").title = L.crossfade;
  $("play-view-crossfade").setAttribute("aria-label", L.crossfade);
  $("play-view-library").title = L.radio_exit;
  $("play-view-library").setAttribute("aria-label", L.radio_exit);
  updateRadioButton();
  $("play-view-play").title = audio.paused ? L.play : L.pause;
  $("play-view-play").setAttribute("aria-label", audio.paused ? L.play : L.pause);
  $("play-view-love").title = L.lfm_love;
  $("play-view-bookmark").title = L.bm_add;
  updatePlayViewClock();
  renderPlayViewQueue();
  // Decade chips
  const decadeEl = $("chips-decade");
  if (decadeEl) decadeEl.querySelector(".chip[data-val='']").textContent = L.all;
  // Year slider labels
  const yfrom = $("label-year-from");
  const yto   = $("label-year-to");
  if (yfrom) yfrom.textContent = L.year_from;
  if (yto)   yto.textContent   = L.year_to;
  // Flag buttons
  document.querySelectorAll(".lang-btn").forEach(b => b.classList.remove("active"));
  const active = $(`lang-${lang}`);
  if (active) active.classList.add("active");
  // Re-render dynamic strings
  renderPagination();
  const rc = $("result-count");
  if (rc && state.total !== undefined) {
    rc.textContent = state.query
      ? t().results_q(state.total, esc(state.query))
      : t().results(state.total);
  }
}

// ── State ─────────────────────────────────────────────────
const basket = new Set();

// basketTracks: Map id → track-Objekt für Panel-Anzeige
const basketTracks = new Map();

function updateBasketUI() {
  const count = basket.size;
  const badge = $("basket-count");
  const btn   = $("btn-basket");
  badge.style.display = count > 0 ? "inline-block" : "none";
  badge.textContent   = count;
  btn.classList.toggle("open", btn.classList.contains("open") && count > 0);
  renderBasketPanel();
}

function renderBasketPanel() {
  const list  = $("basket-list");
  const empty = $("basket-empty");
  const dlBtn = $("btn-basket-download");
  list.innerHTML = "";

  if (basket.size === 0) {
    empty.style.display = "block";
    dlBtn.style.display = "none";
    return;
  }
  empty.style.display = "none";
  dlBtn.style.display = "flex";

  basket.forEach(id => {
    const t = basketTracks.get(id);
    if (!t) return;
    const item = document.createElement("div");
    item.className = "basket-item";
    item.innerHTML = `
      <div class="basket-item-info">
        <div class="basket-item-title">${esc(t.title || "—")}</div>
        <div class="basket-item-sub">${esc(t.artist || "")}${t.year ? " · " + t.year : ""}</div>
      </div>
      <button class="basket-remove" title="${LANG[lang].basket_remove}"><i class="ti ti-x"></i></button>`;
    item.querySelector(".basket-remove").onclick = () => {
      basket.delete(id);
      basketTracks.delete(id);
      updateBasketUI();
      renderTracks();
    };
    list.appendChild(item);
  });
}

$("btn-basket").onclick = () => {
  const panel = $("basket-panel");
  const btn   = $("btn-basket");
  const open  = panel.classList.toggle("open");
  btn.classList.toggle("open", open);
};

// Klick außerhalb schließt Panel
document.addEventListener("click", e => {
  if (!$("btn-basket").closest("div").contains(e.target)) {
    $("basket-panel").classList.remove("open");
    $("btn-basket").classList.remove("open");
  }
});

$("btn-basket-download").onclick = async () => {
  const dlBtn = $("btn-basket-download");
  dlBtn.disabled = true;
  dlBtn.innerHTML = `<i class="ti ti-loader" style="animation:spin 1s linear infinite"></i> ${t().basket_packing}`;
  try {
    const res = await fetch(`${API}/api/download`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ids: [...basket] }),
    });
    if (!res.ok) throw new Error("Fehler");
    const blob = await res.blob();
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement("a");
    a.href = url; a.download = "adolar.zip"; a.click();
    URL.revokeObjectURL(url);
    basket.clear();
    basketTracks.clear();
    updateBasketUI();
    renderTracks();
    $("basket-panel").classList.remove("open");
    $("btn-basket").classList.remove("open");
  } catch {
    alert(t().basket_error);
  } finally {
    dlBtn.disabled = false;
    dlBtn.innerHTML = `<i class="ti ti-device-floppy"></i> ${t().basket_download}`;
  }
};

const DEMO_TRACKS = [
  { id:1, title:"Get Lucky", artist:"Daft Punk", album:"Random Access Memories", year:2013, genre:"Electronic", duration:369, duration_fmt:"6:09", format:"FLAC", has_cover:false, cover_hash:null },
  { id:2, title:"Bohemian Rhapsody", artist:"Queen", album:"A Night at the Opera", year:1975, genre:"Rock", duration:355, duration_fmt:"5:55", format:"MP3", has_cover:false, cover_hash:null },
  { id:3, title:"Alright", artist:"Kendrick Lamar", album:"To Pimp a Butterfly", year:2015, genre:"Hip-Hop", duration:219, duration_fmt:"3:39", format:"FLAC", has_cover:false, cover_hash:null },
  { id:4, title:"Around the World", artist:"Daft Punk", album:"Homework", year:1997, genre:"Electronic", duration:427, duration_fmt:"7:07", format:"MP3", has_cover:false, cover_hash:null },
  { id:5, title:"Creep", artist:"Radiohead", album:"Pablo Honey", year:1993, genre:"Rock", duration:236, duration_fmt:"3:56", format:"MP3", has_cover:false, cover_hash:null },
  { id:6, title:"Ocean Eyes", artist:"Billie Eilish", album:"dont smile at me", year:2017, genre:"Pop", duration:201, duration_fmt:"3:21", format:"MP3", has_cover:false, cover_hash:null },
  { id:7, title:"Take Five", artist:"Dave Brubeck Quartet", album:"Time Out", year:1959, genre:"Jazz", duration:324, duration_fmt:"5:24", format:"FLAC", has_cover:false, cover_hash:null },
  { id:8, title:"Lose Yourself to Dance", artist:"Daft Punk", album:"Random Access Memories", year:2013, genre:"Electronic", duration:337, duration_fmt:"5:37", format:"MP3", has_cover:false, cover_hash:null },
];

const state = {
  tracks: [],
  total: 0,
  page: 1,
  pages: 1,
  currentIdx: -1,
  currentTrack: null,
  query: "",
  sort: "artist",
  filters: {
    genre: "", decade: "", format: "",
    min_dur: 0, max_dur: 0,
    min_bitrate: 0,
    year_min: 0, year_max: 0,
    artist_query: "", title_query: "", album_query: "",
    loved: false,
  },
  albumView: {
    active: false,   // true while the main area is showing the album grid
    drilled: null,   // {album, artist} while showing one album's tracks
    albums: [],
    page: 1,
  },
};

function hasActiveFilters() {
  return Object.values(state.filters).some(v => Boolean(v));
}

function updateMobileFilterButton() {
  const btn = $("btn-mobile-filter");
  if (!btn) return;
  btn.classList.toggle("active", hasActiveFilters());
}

function openMobileFilters() {
  document.body.classList.add("mobile-filter-open");
}

function closeMobileFilters() {
  document.body.classList.remove("mobile-filter-open");
}

$("btn-mobile-filter").onclick = openMobileFilters;
document.addEventListener("keydown", e => {
  if (e.key === "Escape") closeMobileFilters();
});
window.addEventListener("resize", () => {
  if (window.innerWidth > 720) closeMobileFilters();
});

// ── DOM ───────────────────────────────────────────────────
const audio      = $("audio");
const audioB     = $("audio-b");
const playBtn    = $("play-btn");
const progress   = $("progress");

// ── Radio state ───────────────────────────────────────────
const radio = { active: false, browsingLibrary: false, queue: [], playedIds: [], shuffleSession: null, cfTimer: null, cfActive: false };
radio.stationId = 1;
radio.stationName = "Adolar Radio";
radio.station = null;
radio.tracksSinceJingle = 0;
const playViewState = { open: false, openedOnce: false, dismissed: false, returnFocus: null };
const listShuffle = {
  active: false,
  loading: false,
  shuffleSession: null,
  sourceParams: null,
  sourceTotal: 0,
  session: 0,
};
const normalCrossfade = {
  enabled: localStorage.getItem("adolar_crossfade") === "1",
  active: false,
  timer: null,
};
const CF_PRELOAD = 25; // seconds before end: start buffering next track
const CF_OUT     = 12; // seconds before end: start fade-out
const CF_IN      =  8; // fade-in duration

// ── Optional Adolar4U listening signals ──────────────────
const adolar4uTelemetry = {
  sessionId: (globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`),
  sequence: 0,
  trackId: null,
  decisionId: null,
  source: "unknown",
};

function adolar4uSource() {
  if (radio.active && radio.station?.engine === "adolar4u") return "adolar4u";
  if (radio.active) return "radio";
  if (listShuffle.active) return "shuffle";
  if (_activePl) return "playlist";
  return "library";
}

function sendAdolar4UEvent(trackId, eventType, details = {}, beacon = false) {
  if (!_adolar4u.collecting || !trackId || String(trackId).startsWith("jingle-")) return;
  const payload = {
    event_type: eventType,
    source: details.source || adolar4uTelemetry.source || "unknown",
    reason: details.reason || null,
    position_seconds: Number(details.position || 0),
    duration_seconds: Number(details.duration || 0),
    session_id: adolar4uTelemetry.sessionId,
    recommendation_id: details.decisionId || adolar4uTelemetry.decisionId || null,
    client_event_id: `${adolar4uTelemetry.sessionId}:${++adolar4uTelemetry.sequence}:${eventType}`,
  };
  const url = `${API}/api/adolar4u/events/${trackId}`;
  if (beacon && navigator.sendBeacon) {
    navigator.sendBeacon(url, new Blob([JSON.stringify(payload)], {type: "application/json"}));
    return;
  }
  fetch(url, {
    method: "POST", headers: {"Content-Type":"application/json"},
    body: JSON.stringify(payload), keepalive: true,
  }).catch(() => {});
}

function startAdolar4UTrack(track) {
  if (!_adolar4u.collecting || !track || isJingle(track)) return;
  adolar4uTelemetry.trackId = track.id;
  adolar4uTelemetry.decisionId = track.adolar4u_decision_id || null;
  adolar4uTelemetry.source = adolar4uSource();
  sendAdolar4UEvent(track.id, "started", {
    source: adolar4uTelemetry.source,
    duration: Number(track.duration || 0),
  });
}

function finishAdolar4UTrack(reason = "track_change", forceCompleted = false, beacon = false) {
  const trackId = adolar4uTelemetry.trackId;
  if (!trackId) return;
  const duration = Number(audio.duration || state.currentTrack?.duration || 0);
  const position = Math.min(Number(audio.currentTime || 0), duration || Infinity);
  const ratio = duration > 0 ? position / duration : 0;
  sendAdolar4UEvent(trackId, forceCompleted || ratio >= .9 ? "completed" : "skipped", {
    source: adolar4uTelemetry.source,
    reason: forceCompleted || ratio >= .9 ? "ended" : reason,
    position, duration,
  }, beacon);
  adolar4uTelemetry.trackId = null;
  adolar4uTelemetry.decisionId = null;
}

// ── Helpers ───────────────────────────────────────────────
function fmt(sec) {
  if (!sec || isNaN(sec)) return "0:00";
  const m = Math.floor(sec / 60), s = Math.floor(sec % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

function esc(s) {
  return String(s ?? "")
    .replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
}

function initials(name) {
  if (!name) return "♪";
  return name.trim().split(/\s+/).slice(0,2).map(w => w[0].toUpperCase()).join("");
}

function artistColor(name) {
  let h = 0;
  for (const c of (name || "?")) h = (h * 31 + c.charCodeAt(0)) & 0xffff;
  return `hsl(${h % 360}, 55%, 40%)`;
}

function makePlaceholder(track, size) {
  const div = document.createElement("div");
  div.className = "track-cover-placeholder";
  div.style.cssText = `width:${size}px;height:${size}px;background:${artistColor(track.artist)}`;
  div.textContent = initials(track.artist);
  return div;
}

function makeCover(track, size = 42) {
  if (!track.has_cover) return makePlaceholder(track, size);

  const img = document.createElement("img");
  img.className = "track-cover";
  img.decoding = "async";
  img.width = size; img.height = size;
  img.onerror = () => img.replaceWith(makePlaceholder(track, size));
  img.src = `${API}/api/cover/${track.cover_hash}`;
  return img;
}

function isJingle(item) {
  return Boolean(item && (item.type === "jingle" || item.is_jingle));
}

function stationJingleEvery() {
  return Number(radio.station?.jingle_every_tracks || 0);
}

function stationHasJingle() {
  return Boolean(
    radio.station &&
    radio.station.has_jingle &&
    radio.station.jingle_enabled &&
    stationJingleEvery() > 0
  );
}

function jingleDueAfterCurrent() {
  return stationHasJingle() && !isJingle(state.currentTrack) &&
    radio.tracksSinceJingle + 1 >= stationJingleEvery();
}

function makeJingleItem() {
  return {
    id: `jingle-${radio.stationId}`,
    type: "jingle",
    is_jingle: true,
    title: radio.stationName || t().radio,
    artist: "Station-ID",
    album: "",
    duration: 0,
    has_cover: false,
  };
}

// ── Fetch ─────────────────────────────────────────────────
let _loadTracksRequest = 0;
const INITIAL_TRACK_CACHE_VERSION = 1;

function initialTrackCacheKey() {
  return `adolar_initial_tracks_v${INITIAL_TRACK_CACHE_VERSION}_${_me?.id || "guest"}`;
}

function isInitialTrackRequest(page) {
  return page === 1 && !state.query && state.sort === "artist" &&
    !Object.values(state.filters).some(Boolean) && !_activePl && !radio.active;
}

function hydrateInitialTrackCache() {
  try {
    const cached = JSON.parse(localStorage.getItem(initialTrackCacheKey()) || "null");
    if (!cached?.results?.length || Date.now() - cached.savedAt > 7 * 86400000) return;
    state.tracks = cached.results;
    state.total = cached.total || cached.results.length;
    state.pages = cached.pages || Math.max(1, Math.ceil(state.total / 50));
    state.page = 1;
    renderTracks();
    renderPagination();
    $("result-count").textContent = t().results(state.total);
    fetchMemberships(state.tracks);
  } catch (_) {}
}

function cacheInitialTracks(data) {
  try {
    localStorage.setItem(initialTrackCacheKey(), JSON.stringify({
      results: data.results,
      total: data.total,
      pages: data.pages,
      savedAt: Date.now(),
    }));
  } catch (_) {}
}

function _setSearching(on) {
  const wrap = document.querySelector('.search-input-wrap');
  const icon = wrap?.querySelector('i');
  if (!wrap || !icon) return;
  if (on) {
    wrap.classList.add('searching');
    icon.className = 'ti ti-loader';
  } else {
    wrap.classList.remove('searching');
    icon.className = 'ti ti-search';
  }
}

async function loadTracks(page = 1, forceCount = false) {
  // Album search (without drilling into one specific album) browses albums,
  // not individual tracks — hand off to the grid loader instead.
  if (state.filters.album_query && !state.albumView.drilled) {
    return loadAlbumGrid(page);
  }
  const drilled = state.albumView.drilled;
  state.albumView.active = Boolean(drilled);

  // Browsing/searching is independent of the active radio queue.  Keep the
  // station playing until the user explicitly starts one of the search hits.
  if (radio.active) {
    radio.browsingLibrary = true;
    updateRadioButton();
  }
  else {
    resetNormalCrossfadeBuffer();
    if (listShuffle.active) stopListShuffle(false);
  }
  $("radio-test-banner")?.classList.remove("visible");
  const requestId = ++_loadTracksRequest;
  updateSavePlaylistBtn();
  updateMobileFilterButton();
  updateAlbumBackBar();
  _setSearching(true);
  // Skip COUNT if we already have the total and are just paging
  const needCount = page === 1 || forceCount || state.total === 0;
  state.page = page;
  const perPage = drilled ? 200 : 50;
  const p = new URLSearchParams({ page, per_page: perPage, sort: drilled ? "album" : state.sort });
  if (!needCount) p.set("count", "0");
  if (drilled) {
    p.set("album_eq", drilled.album || "");
    p.set("artist_eq", drilled.artist || "");
  } else {
    if (state.query)              p.set("q", state.query);
    if (state.filters.genre)      p.set("genre",   state.filters.genre);
    if (state.filters.decade)     p.set("decade",  state.filters.decade);
    if (state.filters.format)     p.set("format",  state.filters.format);
    if (state.filters.min_dur > 0)     p.set("min_dur",     state.filters.min_dur);
    if (state.filters.max_dur > 0)     p.set("max_dur",     state.filters.max_dur);
    if (state.filters.min_bitrate > 0) p.set("min_bitrate", state.filters.min_bitrate);
    if (state.filters.year_min > 0)    p.set("year_min",    state.filters.year_min);
    if (state.filters.year_max > 0)    p.set("year_max",    state.filters.year_max);
    if (state.filters.bpm_min > 0)     p.set("bpm_min",     state.filters.bpm_min);
    if (state.filters.bpm_max > 0)     p.set("bpm_max",     state.filters.bpm_max);
    if (state.filters.artist_query)    p.set("artist", state.filters.artist_query);
    if (state.filters.title_query)     p.set("title",  state.filters.title_query);
    if (state.filters.album_query)     p.set("album",  state.filters.album_query);
    if (state.filters.loved)           p.set("loved",  "1");
  }

  let data;
  try {
    const res = await fetch(`${API}/api/search?${p}`);
    data = await res.json();
  } catch {
    data = { results: DEMO_TRACKS, total: DEMO_TRACKS.length, pages: 1 };
  }
  if (requestId !== _loadTracksRequest) return;
  if (!data.results?.length && page === 1 && !state.query && !Object.values(state.filters).some(Boolean)) {
    data = { results: DEMO_TRACKS, total: DEMO_TRACKS.length, pages: 1 };
  }

  state.tracks = data.results;
  if (isInitialTrackRequest(page) && data.results?.length) cacheInitialTracks(data);
  // Preserve cached total when not recounting
  if (needCount) {
    state.total = data.total;
    state.pages = data.pages;
  } else {
    // Recalculate pages from cached total
    state.pages = Math.max(1, Math.ceil(state.total / 50));
  }

  _setSearching(false);
  renderTracks();
  renderPagination();
  fetchMemberships(state.tracks);

  // Scroll to top of results
  document.getElementById('track-list')?.scrollTo({ top: 0, behavior: 'instant' });

  if (drilled) {
    $("result-count").textContent = t().album_tracks_count(data.total, drilled.album);
  } else {
    const q = state.query;
    $("result-count").textContent = q
      ? t().results_q(data.total, esc(q))
      : t().results(data.total);
  }
  updateMobileFilterButton();
}

// ── Album grid (album search shows albums, not every matching track) ──────
let _loadAlbumsRequest = 0;

function updateAlbumBackBar() {
  const bar = $("album-back-bar");
  if (!bar) return;
  bar.classList.toggle("visible", Boolean(state.albumView.drilled));
}

function openAlbumTracks(album) {
  state.albumView.drilled = { album: album.album, artist: album.artist };
  loadTracks(1);
}

function backToAlbumGrid() {
  state.albumView.drilled = null;
  loadAlbumGrid(state.albumView.page || 1);
}

async function loadAlbumGrid(page = 1) {
  if (radio.active) {
    radio.browsingLibrary = true;
    updateRadioButton();
  } else {
    resetNormalCrossfadeBuffer();
    if (listShuffle.active) stopListShuffle(false);
  }
  $("radio-test-banner")?.classList.remove("visible");
  const requestId = ++_loadAlbumsRequest;
  updateSavePlaylistBtn();
  updateMobileFilterButton();
  updateAlbumBackBar();
  _setSearching(true);

  state.albumView.active = true;
  state.albumView.page = page;

  const p = new URLSearchParams({ page, per_page: 50, sort: state.sort === "year" ? "year" : "album" });
  if (state.query)                   p.set("q", state.query);
  if (state.filters.genre)           p.set("genre",   state.filters.genre);
  if (state.filters.decade)          p.set("decade",  state.filters.decade);
  if (state.filters.format)          p.set("format",  state.filters.format);
  if (state.filters.min_dur > 0)     p.set("min_dur",     state.filters.min_dur);
  if (state.filters.max_dur > 0)     p.set("max_dur",     state.filters.max_dur);
  if (state.filters.min_bitrate > 0) p.set("min_bitrate", state.filters.min_bitrate);
  if (state.filters.year_min > 0)    p.set("year_min",    state.filters.year_min);
  if (state.filters.year_max > 0)    p.set("year_max",    state.filters.year_max);
  if (state.filters.bpm_min > 0)     p.set("bpm_min",     state.filters.bpm_min);
  if (state.filters.bpm_max > 0)     p.set("bpm_max",     state.filters.bpm_max);
  if (state.filters.artist_query)    p.set("artist", state.filters.artist_query);
  if (state.filters.title_query)     p.set("title",  state.filters.title_query);
  if (state.filters.album_query)     p.set("album",  state.filters.album_query);

  let data;
  try {
    const res = await fetch(`${API}/api/albums?${p}`);
    data = await res.json();
  } catch {
    data = { results: [], total: 0, pages: 1 };
  }
  if (requestId !== _loadAlbumsRequest) return;

  state.albumView.albums = data.results || [];
  state.total = data.total;
  state.pages = data.pages;
  state.page = page;

  _setSearching(false);
  renderAlbumGrid();
  renderPagination();

  document.getElementById('track-list')?.scrollTo({ top: 0, behavior: 'instant' });

  $("result-count").textContent = t().album_results(data.total);
  updateMobileFilterButton();
}

function renderAlbumGrid() {
  const list = $("track-list");
  list.classList.add("album-grid-mode");
  list.innerHTML = "";

  const albums = state.albumView.albums;
  if (!albums.length) {
    list.innerHTML = `<div class="empty-state"><i class="ti ti-disc-off"></i>${t().no_albums}</div>`;
    return;
  }

  albums.forEach(album => {
    const card = document.createElement("div");
    card.className = "album-card";
    card.title = t().album_open_hint;

    const cover = makeCover({ has_cover: album.has_cover, cover_hash: album.cover_hash, artist: album.artist }, 160);
    // Replace (not add to) the track-cover class: album cards need their own
    // sizing rules, and keeping "track-cover(-placeholder)" around would let
    // the track-list's mobile breakpoint rules win the cascade over ours.
    if (cover.tagName === "IMG") {
      cover.className = "album-cover";
    } else {
      // makePlaceholder() inlines a fixed width/height via cssText — clear it
      // so the CSS (incl. the mobile 2-up breakpoint) controls sizing.
      cover.className = "album-cover-placeholder";
      cover.style.cssText = `background:${artistColor(album.artist)}`;
    }
    card.appendChild(cover);

    const openBtn = document.createElement("button");
    openBtn.type = "button";
    openBtn.className = "album-card-open-btn";
    openBtn.title = t().album_open_btn_title;
    openBtn.innerHTML = `<i class="ti ti-corner-right-up"></i>`;
    openBtn.addEventListener("click", e => { e.stopPropagation(); openAlbumTracks(album); });
    card.appendChild(openBtn);

    const info = document.createElement("div");
    info.className = "album-card-info";
    const sub = [album.artist, t().album_tracks_short(album.track_count)].filter(Boolean).join(" · ");
    info.innerHTML = `<div class="album-card-title">${esc(album.album || "—")}</div>
                       <div class="album-card-sub">${esc(sub)}</div>`;
    card.appendChild(info);

    card.addEventListener("dblclick", () => openAlbumTracks(album));
    list.appendChild(card);
  });
}

// ── Render Tracks ─────────────────────────────────────────
function renderTracks(overrideTracks) {
  const list = $("track-list");
  list.classList.remove("album-grid-mode");
  list.innerHTML = "";

  const tracks = overrideTracks || state.tracks;
  if (overrideTracks) state.tracks = overrideTracks;

  if (!tracks.length) {
    list.innerHTML = `<div class="empty-state"><i class="ti ti-music-off"></i>${t().no_tracks}</div>`;
    return;
  }

  tracks.forEach((track, i) => {
    const row = document.createElement("div");
    row.className = "track-row" + (state.currentTrack?.id === track.id ? " active" : "");
    row.dataset.idx = i;

    // Cover
    row.appendChild(makeCover(track, 42));

    // Info
    const info = document.createElement("div");
    info.className = "track-info";
    const sub = [track.artist, track.album, track.year].filter(Boolean).join(" · ");
    info.innerHTML = `<div class="track-title">${esc(track.title || track.path?.split(/[\\/]/).pop() || "—")}</div>
                      <div class="track-sub">${esc(sub)}</div>`;
    row.appendChild(info);

    // Meta
    const meta = document.createElement("div");
    meta.className = "track-meta";
    const bpmStr = track.bpm ? `<span class="track-bpm" title="BPM">${Math.round(track.bpm)}</span>` : '';
    const pcStr  = track.user_play_count != null ? `<span class="track-playcount" title="${lang==='de'?'Abgespielt':'Play count'}">▶ ${track.user_play_count}×</span>` : '';
    meta.innerHTML = `<span class="format-badge">${esc(track.format)}</span>
                      ${bpmStr}
                      ${pcStr}
                      <span class="track-dur">${track.duration_fmt || fmt(track.duration)}</span>`;
    row.appendChild(meta);

    // Play button
    const playBtn = document.createElement("button");
    playBtn.className = "track-play-btn";
    playBtn.title = t().play;
    const isPlaying = state.currentTrack?.id === track.id && !audio.paused;
    playBtn.innerHTML = isPlaying
      ? `<i class="ti ti-player-pause"></i>`
      : `<i class="ti ti-player-play"></i>`;
    playBtn.addEventListener("click", e => {
      e.stopPropagation();
      if (state.currentTrack?.id === track.id) {
        audio.paused ? audio.play() : audio.pause();
      } else {
        playTrack(i);
      }
    });
    row.appendChild(playBtn);

    // Download-Button (nur wenn Download erlaubt)
    if (_me && _me.allow_download) {
      const dlBtn = document.createElement("button");
      dlBtn.className = "track-play-btn";
      dlBtn.title = basket.has(track.id) ? t().basket_rm : t().basket_add;
      dlBtn.innerHTML = basket.has(track.id)
        ? `<i class="ti ti-shopping-cart-off" style="color:var(--accent)"></i>`
        : `<i class="ti ti-download"></i>`;
      dlBtn.addEventListener("click", e => {
        e.stopPropagation();
        if (basket.has(track.id)) {
          basket.delete(track.id);
          basketTracks.delete(track.id);
        } else {
          basket.add(track.id);
          basketTracks.set(track.id, track);
        }
        updateBasketUI();
        renderTracks();
      });
      row.appendChild(dlBtn);
    }

    // Last.fm love button for the current user's personal account
    if (lfm.connected && _me) {
      const loveBtn = document.createElement("button");
      const loveKey = `${track.artist}||${track.title}`;
      const isLoved = Boolean(track.loved || lfm.lovedCache.get(loveKey));
      lfm.lovedCache.set(loveKey, isLoved);
      loveBtn.className = "btn-love" + (isLoved ? " loved" : "");
      loveBtn.dataset.key = loveKey;
      loveBtn.title = isLoved ? t().lfm_unlove : t().lfm_love;
      loveBtn.innerHTML = isLoved
        ? `<i class="ti ti-heart-filled"></i>`
        : `<i class="ti ti-heart"></i>`;
      loveBtn.addEventListener("click", e => {
        e.stopPropagation();
        lfmToggleLove(track, loveBtn);
      });
      row.appendChild(loveBtn);
    }

    if (_me) {
      const favoriteBtn = document.createElement("button");
      favoriteBtn.className = "btn-favorite";
      favoriteBtn.dataset.trackId = track.id;
      applyFavoriteState(favoriteBtn, _favoriteIds.has(Number(track.id)));
      favoriteBtn.addEventListener("click", e => {
        e.stopPropagation();
        toggleFavorite(track, favoriteBtn);
      });
      row.appendChild(favoriteBtn);
    }

    // Bookmark button (alle eingeloggten Nutzer)
    if (_me?.allow_playlists) {
      const bmBtn = document.createElement("button");
      bmBtn.className = "btn-bookmark";
      bmBtn.dataset.trackId = track.id;
      _applyBookmarkState(bmBtn, track.id);
      bmBtn.addEventListener("click", e => {
        e.stopPropagation();
        _openBookmarkDropdown(bmBtn, track.id);
      });
      row.appendChild(bmBtn);
    }

    row.addEventListener("click", () => playTrack(i));
    list.appendChild(row);
  });
  if (playViewState.open) renderPlayViewQueue();
}

// ── Render Pagination ─────────────────────────────────────
function renderPagination() {
  const pg = $("pagination");
  pg.innerHTML = "";
  if (state.pages <= 1) return;

  const prev = document.createElement("button");
  prev.className = "pg-btn"; prev.textContent = t().pg_prev;
  prev.disabled = state.page <= 1;
  prev.onclick = () => loadTracks(state.page - 1);
  pg.appendChild(prev);

  const info = document.createElement("span");
  info.id = "pg-info";
  info.textContent = t().pg_info(state.page, state.pages);
  pg.appendChild(info);

  const next = document.createElement("button");
  next.className = "pg-btn"; next.textContent = t().pg_next;
  next.disabled = state.page >= state.pages;
  next.onclick = () => loadTracks(state.page + 1);
  pg.appendChild(next);
}

// ── Scrolling tab title ────────────────────────────────────
let _titleTimer = null;

function startTitleScroll(text) {
  if (_titleTimer) { clearInterval(_titleTimer); _titleTimer = null; }
  if (!text) { document.title = "Adolar"; return; }

  const full   = `${text}   ·   `;  // separator between repetitions
  const STATIC = 5000;   // ms to hold before scrolling
  const STEP   = 150;    // ms per character step
  let pos = 0;
  let phase = "static"; // "static" | "scroll" | "pause"
  let elapsed = 0;

  document.title = text;

  _titleTimer = setInterval(() => {
    if (phase === "static") {
      elapsed += STEP;
      if (elapsed >= STATIC) { phase = "scroll"; elapsed = 0; pos = 0; }
    } else if (phase === "scroll") {
      pos = (pos + 1) % full.length;
      const display = (full + full).slice(pos, pos + text.length);
      document.title = display;
      if (pos === 0) { phase = "pause"; elapsed = 0; document.title = text; }
    } else {
      elapsed += STEP;
      if (elapsed >= STATIC) { phase = "scroll"; elapsed = 0; pos = 0; }
    }
  }, STEP);
}

// ── Player ─────────────────────────────────────────────────
function updatePlayViewClock() {
  const clock = $("play-view-clock");
  if (!clock) return;
  const now = new Date();
  const locale = lang === "de" ? "de-DE" : "en-GB";
  const weekday = new Intl.DateTimeFormat(locale, { weekday: "long" }).format(now);
  const day = String(now.getDate()).padStart(2, "0");
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const hours = String(now.getHours()).padStart(2, "0");
  const minutes = String(now.getMinutes()).padStart(2, "0");
  clock.textContent = `${weekday}, ${day}.${month}.${now.getFullYear()} ${hours}:${minutes}`;
  clock.dateTime = now.toISOString();
}

const artworkPreloads = new Map();
let playViewCoverRequest = 0;

function artworkUrl(track, full = false) {
  if (!track?.has_cover) return null;
  return `${API}/api/cover/${track.cover_hash}${full ? "?full=1" : ""}`;
}

function preloadImage(url) {
  if (!url) return Promise.resolve(null);
  if (artworkPreloads.has(url)) return artworkPreloads.get(url);
  const pending = new Promise(resolve => {
    const img = new Image();
    img.alt = "";
    img.onload = async () => {
      try { await img.decode(); } catch (_) {}
      resolve(img);
    };
    img.onerror = () => resolve(null);
    img.src = url;
  });
  artworkPreloads.set(url, pending);
  if (artworkPreloads.size > 20) {
    artworkPreloads.delete(artworkPreloads.keys().next().value);
  }
  return pending;
}

function preloadTrackArtwork(track) {
  if (!track?.has_cover) return;
  preloadImage(artworkUrl(track));
  preloadImage(artworkUrl(track, true));
}

async function setPlayViewCover(track) {
  const wrap = $("play-view-cover");
  const request = ++playViewCoverRequest;
  if (track?.has_cover) {
    const loaded = await preloadImage(artworkUrl(track, true));
    if (request !== playViewCoverRequest) return;
    if (loaded) {
      const img = loaded.cloneNode();
      img.alt = "";
      wrap.replaceChildren(img);
      return;
    }
  }
  if (request !== playViewCoverRequest) return;
  const ph = document.createElement("div");
  ph.className = "cover-placeholder";
  ph.style.background = artistColor(track?.artist);
  ph.textContent = initials(track?.artist);
  wrap.replaceChildren(ph);
}

function makePlayViewQueueCover(track) {
  const wrap = document.createElement("div");
  wrap.className = "play-view-queue-cover";
  if (track.has_cover) {
    const img = document.createElement("img");
    img.alt = "";
    img.loading = "lazy";
    img.src = `${API}/api/cover/${track.cover_hash}`;
    img.onerror = () => {
      wrap.innerHTML = "";
      const ph = document.createElement("div");
      ph.className = "cover-placeholder";
      ph.style.background = artistColor(track.artist);
      ph.textContent = initials(track.artist);
      wrap.appendChild(ph);
    };
    wrap.appendChild(img);
  } else {
    const ph = document.createElement("div");
    ph.className = "cover-placeholder";
    ph.style.background = artistColor(track.artist);
    ph.textContent = initials(track.artist);
    wrap.appendChild(ph);
  }
  return wrap;
}

function playViewQueueTracks() {
  const current = state.currentTrack;
  if (!current) return [];
  const source = state.tracks || [];
  const currentIndex = source.findIndex(track => String(track.id) === String(current.id));
  if (currentIndex >= 0) return source.slice(currentIndex, currentIndex + 100);
  return [current, ...source.filter(track => String(track.id) !== String(current.id)).slice(0, 99)];
}

function renderPlayViewQueue() {
  const list = $("play-view-queue");
  if (!list) return;
  const tracks = playViewQueueTracks();
  list.innerHTML = "";
  if (!tracks.length) {
    list.innerHTML = `<div class="empty-state">${t().queue_empty}</div>`;
    return;
  }

  tracks.forEach(track => {
    const active = String(track.id) === String(state.currentTrack?.id);
    const sourceIndex = state.tracks.findIndex(item => String(item.id) === String(track.id));
    const canActivate = active || (!radio.active && sourceIndex >= 0);
    const row = document.createElement(canActivate ? "button" : "div");
    if (row.tagName === "BUTTON") row.type = "button";
    row.className = "play-view-queue-row" + (active ? " active" : "") +
      (radio.active && !active ? " radio-locked" : "");
    row.appendChild(makePlayViewQueueCover(track));

    const info = document.createElement("div");
    info.className = "play-view-queue-info";
    const sub = [track.artist, track.album, track.year].filter(Boolean).join(" · ");
    info.innerHTML = `<div class="play-view-queue-track">${esc(track.title || "—")}</div>
      <div class="play-view-queue-sub">${esc(sub)}</div>`;
    row.appendChild(info);

    const meta = document.createElement("div");
    meta.className = "play-view-queue-meta";
    const bpm = track.bpm ? `${Math.round(track.bpm)} BPM` : "";
    meta.innerHTML = `<div>${esc(track.format || (isJingle(track) ? "ID" : ""))}</div>
      <div>${esc([bpm, track.duration_fmt || fmt(track.duration)].filter(Boolean).join(" · "))}</div>`;
    row.appendChild(meta);

    if (canActivate) {
      row.onclick = () => {
        if (active) {
          audio.paused ? audio.play() : audio.pause();
        } else {
          playTrack(sourceIndex);
        }
      };
    }
    list.appendChild(row);
  });

  if (playViewState.open) {
    requestAnimationFrame(() => list.querySelector(".active")?.scrollIntoView({ block: "nearest" }));
  }
}

function updatePlayView(track) {
  if (!track) return;
  $("player-cover-wrap").disabled = false;
  $("btn-play-view-open").disabled = false;
  setPlayViewCover(track);
  $("play-view-title").textContent = track.title || "—";
  $("play-view-subtitle").textContent = [track.artist, track.album, track.year].filter(Boolean).join(" · ");

  const context = $("play-view-context");
  context.classList.toggle("radio-active", radio.active);
  const recommendationReason = track.adolar4u_reason
    ? ` · ${esc(track.adolar4u_reason)}` : "";
  context.innerHTML = radio.active
    ? `<i class="ti ti-radio"></i><span>${esc(t().radio)} · ${esc(radio.stationName || "Adolar Radio")}${recommendationReason}</span>`
    : listShuffle.active
      ? `<i class="ti ti-arrows-shuffle"></i><span>${esc(t().shuffle)}</span>`
    : `<i class="ti ti-list"></i><span>${esc(t().queue)}</span>`;
  $("play-view-queue-title").textContent = listShuffle.active ? t().shuffle : t().queue;

  const meta = [];
  if (track.format) meta.push(track.format);
  if (track.bpm) meta.push(`${Math.round(track.bpm)} BPM`);
  if (track.user_play_count != null) meta.push(`▶ ${track.user_play_count}×`);
  if (track.duration_fmt || track.duration) meta.push(track.duration_fmt || fmt(track.duration));
  $("play-view-meta").textContent = meta.join(" · ");

  const sourceIndex = state.tracks.findIndex(item => String(item.id) === String(track.id));
  $("play-view-prev").disabled = radio.active || sourceIndex <= 0;
  $("play-view-next").disabled = radio.active
    ? radio.queue.length <= 1
    : sourceIndex < 0 || sourceIndex >= state.tracks.length - 1;

  const jingle = isJingle(track);
  $("play-view-library").style.display = radio.active ? "inline-flex" : "none";
  const loveBtn = $("play-view-love");
  loveBtn.style.display = lfm.connected && !jingle ? "inline-flex" : "none";
  loveBtn.dataset.key = `${track.artist}||${track.title}`;
  const loved = Boolean(track.loved || lfm.lovedCache.get(loveBtn.dataset.key));
  applyLovedState(loveBtn, loved);

  const favoriteBtn = $("play-view-favorite");
  favoriteBtn.style.display = _me && !jingle ? "inline-flex" : "none";
  favoriteBtn.dataset.trackId = track.id;
  applyFavoriteState(favoriteBtn, _favoriteIds.has(Number(track.id)));

  const bookmarkBtn = $("play-view-bookmark");
  bookmarkBtn.style.display = _me && !jingle ? "inline-flex" : "none";
  bookmarkBtn.dataset.trackId = track.id;
  if (_me && !jingle) _applyBookmarkState(bookmarkBtn, track.id);
  updatePlaybackModeControls();
  renderPlayViewQueue();
}

function openPlayView(automatic = false) {
  if (!state.currentTrack) return;
  playViewState.returnFocus = document.activeElement;
  playViewState.open = true;
  playViewState.openedOnce = true;
  if (!automatic) playViewState.dismissed = false;
  $("play-view").classList.add("open");
  $("play-view").setAttribute("aria-hidden", "false");
  for (const id of ["topbar", "body-row", "player-bar"]) $(id)?.setAttribute("inert", "");
  updatePlayView(state.currentTrack);
  $("play-view-close").focus();
}

function closePlayView() {
  playViewState.open = false;
  playViewState.dismissed = true;
  $("play-view").classList.remove("open");
  $("play-view").setAttribute("aria-hidden", "true");
  for (const id of ["topbar", "body-row", "player-bar"]) $(id)?.removeAttribute("inert");
  playViewState.returnFocus?.focus?.();
}

function updatePlayerUI(t) {
  $("player-title").textContent  = t.title  || "—";
  $("player-artist").textContent = t.artist || "";
  startTitleScroll(t.title && t.artist
    ? `${t.title} – ${t.artist}${t.year ? " (" + t.year + ")" : ""}`
    : null);
  updateMiniPlayer(t);
  updatePlayView(t);
  const wrap = $("player-cover-wrap");
  wrap.innerHTML = "";
  if (t.has_cover) {
    const img = document.createElement("img");
    img.src = `${API}/api/cover/${t.cover_hash}`;
    wrap.appendChild(img);
  } else {
    const ph = document.createElement("div");
    ph.className = "cover-placeholder";
    ph.style.background = artistColor(t.artist);
    ph.textContent = initials(t.artist);
    wrap.appendChild(ph);
  }
  if (isJingle(t)) {
    applyLovedState($("player-love"), false);
    $("player-favorite").style.display = "none";
    return;
  }
  $("player-favorite").style.display = _me ? "inline-flex" : "none";
  $("player-favorite").dataset.trackId = t.id;
  applyFavoriteState($("player-favorite"), _favoriteIds.has(Number(t.id)));
  if (lfm.connected) {
    const key = `${t.artist}||${t.title}`;
    const loved = Boolean(t.loved || lfm.lovedCache.get(key));
    lfm.lovedCache.set(key, loved);
    applyLovedState($("player-love"), loved);
    fetch(`${API}/api/lastfm/nowplaying`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ artist: t.artist, title: t.title, duration: t.duration }),
    }).catch(() => {});
  }
}

function playTrack(idx) {
  const t = state.tracks[idx];
  if (!t) return;
  if (radio.active && radio.browsingLibrary) {
    finishAdolar4UTrack("track_change");
    stopRadio();
    radio.browsingLibrary = false;
  }
  finishAdolar4UTrack("track_change");
  if (!radio.active) resetNormalCrossfadeBuffer();
  state.currentIdx   = idx;
  state.currentTrack = t;
  _scrobbled   = false;
  _playCounted = false;

  updatePlayerUI(t);
  if (!playViewState.openedOnce && !playViewState.dismissed) openPlayView(true);
  audio.src = `${API}/api/stream/${t.id}`;
  audio.play();
  startAdolar4UTrack(t);
  renderTracks();
  if (listShuffle.active) ensureListShuffleQueue();
}

function playRadioTrack(track) {
  if (!track) return;
  state.currentIdx = radio.browsingLibrary ? -1 : 0;
  state.currentTrack = track;
  _scrobbled = false;
  _playCounted = false;
  updatePlayerUI(track);
  audio.src = `${API}/api/stream/${track.id}`;
  audio.play();
  startAdolar4UTrack(track);
  renderTracks();
}

function playJingle() {
  const item = makeJingleItem();
  state.currentIdx = -1;
  state.currentTrack = item;
  _scrobbled = true;
  _playCounted = true;
  radio.cfActive = false;
  clearTimeout(radio.cfTimer);
  audioB.pause(); audioB.removeAttribute("src"); audioB.load();
  updatePlayerUI(item);
  audio.src = `${API}/api/radio-stations/${radio.stationId}/jingle`;
  audio.play().catch(() => {});
  renderTracks();
}

// ── Radio functions ───────────────────────────────────────
function currentShuffleParams() {
  const activePlaylist = _playlists.find(pl => String(pl.id) === String(_activePl));
  if (activePlaylist?.type === "static") {
    return new URLSearchParams({ playlist_id: activePlaylist.id });
  }

  const p = new URLSearchParams({ sort: state.sort });
  if (state.query) p.set("q", state.query);
  const filterMap = {
    genre: "genre", decade: "decade", format: "format",
    min_dur: "min_dur", max_dur: "max_dur", min_bitrate: "min_bitrate",
    year_min: "year_min", year_max: "year_max",
    bpm_min: "bpm_min", bpm_max: "bpm_max",
    artist_query: "artist", title_query: "title", album_query: "album",
  };
  Object.entries(filterMap).forEach(([key, param]) => {
    if (state.filters[key]) p.set(param, state.filters[key]);
  });
  if (state.filters.loved) p.set("loved", "1");
  return p;
}

function updateListShuffleUI() {
  updatePlaybackModeControls();
}

function updatePlaybackModeControls() {
  for (const id of ["btn-list-shuffle", "play-view-shuffle"]) {
    const btn = $(id);
    btn.classList.toggle("active", listShuffle.active);
    btn.disabled = radio.active;
    btn.setAttribute("aria-pressed", String(listShuffle.active));
  }
  for (const id of ["btn-crossfade", "play-view-crossfade"]) {
    const btn = $(id);
    btn.classList.toggle("active", normalCrossfade.enabled);
    btn.disabled = radio.active;
    btn.setAttribute("aria-pressed", String(normalCrossfade.enabled));
  }
}

async function fetchListShuffleBatch(count, session) {
  const p = new URLSearchParams(listShuffle.sourceParams);
  p.set("count", count);
  if (listShuffle.shuffleSession) p.set("shuffle_session", listShuffle.shuffleSession);
  const response = await fetch(`${API}/api/shuffle?${p}`);
  if (!response.ok) throw new Error("shuffle failed");
  if (session !== listShuffle.session || !listShuffle.active) return [];
  listShuffle.shuffleSession = response.headers.get("X-Shuffle-Session") || listShuffle.shuffleSession;
  listShuffle.sourceTotal = Number(response.headers.get("X-Shuffle-Total")) || listShuffle.sourceTotal;
  const tracks = await response.json();
  return Array.isArray(tracks) ? tracks : [];
}

function updateListShuffleResult() {
  $("result-count").textContent = `${t().shuffle} – ${state.tracks.length} Tracks`;
}

async function ensureListShuffleQueue(force = false, batchSize = 100) {
  if (!listShuffle.active || listShuffle.loading) return;
  const remaining = state.tracks.length - state.currentIdx - 1;
  if (!force && remaining > 15) return;

  if (state.currentIdx > 50) {
    const removeCount = state.currentIdx - 10;
    state.tracks.splice(0, removeCount);
    state.currentIdx -= removeCount;
  }

  listShuffle.loading = true;
  const session = listShuffle.session;
  try {
    const more = await fetchListShuffleBatch(batchSize, session);
    if (session !== listShuffle.session || !listShuffle.active) return;
    state.tracks.push(...more);
    state.total = state.tracks.length;
    updateListShuffleResult();
    renderTracks();
    renderPagination();
    fetchMemberships(more);
    if (playViewState.open) updatePlayView(state.currentTrack);
  } catch {
    // Keep playing the already buffered queue; another transition can retry.
  } finally {
    if (session === listShuffle.session) listShuffle.loading = false;
  }
}

async function startListShuffle() {
  if (radio.active) return;
  if (listShuffle.active) {
    stopListShuffle(true);
    return;
  }
  listShuffle.active = true;
  listShuffle.loading = true;
  listShuffle.shuffleSession = null;
  listShuffle.sourceParams = currentShuffleParams();
  listShuffle.sourceTotal = 0;
  listShuffle.session += 1;
  const session = listShuffle.session;
  updateListShuffleUI();
  $("result-count").textContent = `${t().shuffle} – …`;

  try {
    const initial = await fetchListShuffleBatch(10, session);
    if (session !== listShuffle.session || !listShuffle.active) return;
    if (!initial.length) {
      stopListShuffle(false);
      return;
    }
    state.tracks = initial;
    state.total = initial.length;
    state.page = 1;
    state.pages = 1;
    listShuffle.loading = false;
    updateListShuffleResult();
    renderPagination();
    fetchMemberships(initial);
    playTrack(0);
    ensureListShuffleQueue(true, 90);
  } catch {
    if (session === listShuffle.session) stopListShuffle(false);
  }
}

function stopListShuffle(restoreSource = false) {
  if (!listShuffle.active && !restoreSource) return;
  listShuffle.active = false;
  listShuffle.loading = false;
  listShuffle.shuffleSession = null;
  listShuffle.session += 1;
  updateListShuffleUI();
  if (state.currentTrack) updatePlayView(state.currentTrack);

  if (restoreSource) {
    const activePlaylist = _playlists.find(pl => String(pl.id) === String(_activePl));
    if (activePlaylist?.type === "static") applyPlaylist(activePlaylist);
    else loadTracks(1, true);
  }
}

async function loadRadioQueue(count, excludeIds = []) {
  const p = new URLSearchParams({ count });
  excludeIds.forEach(id => p.append("exclude", id));
  if (radio.shuffleSession) p.set("shuffle_session", radio.shuffleSession);
  const stationId = radio.stationId || 1;
  try {
    const res = await fetch(`${API}/api/radio-stations/${stationId}/tracks?${p}`);
    if (!res.ok) throw new Error("station failed");
    radio.shuffleSession = res.headers.get("X-Shuffle-Session") || radio.shuffleSession;
    return await res.json();
  } catch { return []; }
}

async function startRadio(station = null, initialPlaylist = null) {
  if (station?.engine === "adolar4u" && _adolar4u.onboarding?.required && !initialPlaylist) {
    openAdolar4UOnboarding(station);
    return;
  }
  stopListShuffle(false);
  resetNormalCrossfadeBuffer();
  $("radio-test-banner")?.classList.remove("visible");
  radio.active = true;
  radio.browsingLibrary = false;
  radio.queue  = [];
  radio.playedIds = [];
  radio.shuffleSession = null;
  radio.tracksSinceJingle = 0;
  if (station) {
    radio.stationId = station.id;
    radio.stationName = station.name;
    radio.station = station;
  }
  updateRadioButton();
  updatePlaybackModeControls();
  closeRadioPanel();

  // Fetch 5 tracks first → play immediately, then fetch remaining in background
  const initial = initialPlaylist?.slice(0, 5) || await loadRadioQueue(5);
  if (!initial.length) { stopRadio(); return; }

  radio.queue   = initial;
  radio.session = (radio.session || 0) + 1; // session token prevents stale fills
  state.tracks  = [...radio.queue];
  $("result-count").textContent = `${radio.stationName || t().radio} – ...`;
  playTrack(0);

  // Background fill to 25 — guarded by session token
  const mySession = radio.session;
  const remaining = initialPlaylist?.slice(5) || null;
  (remaining ? Promise.resolve(remaining) : loadRadioQueue(20, initial.map(t => t.id))).then(more => {
    if (!radio.active || radio.session !== mySession) return;
    radio.queue.push(...more);
    if (!radio.browsingLibrary) {
      state.tracks = [...radio.queue];
      state.total = radio.queue.length;
      $("result-count").textContent = `${radio.stationName || t().radio} – ${radio.queue.length} Tracks`;
      renderTracks();
    }
  });
}

function updateRadioButton() {
  const button = $("btn-radio");
  if (!button) return;
  button.classList.toggle("active", radio.active);
  if (!radio.active) {
    button.innerHTML = `<i class="ti ti-radio"></i> ${t().radio}`;
    button.title = t().radio_manage;
    return;
  }
  const actionIcon = radio.browsingLibrary ? "ti-arrow-back-up" : "ti-x";
  button.innerHTML = `<i class="ti ti-radio"></i> ${esc(radio.stationName || t().radio)} <i class="ti ${actionIcon}"></i>`;
  button.title = radio.browsingLibrary ? t().radio_return : t().radio_exit;
}

function showCurrentRadioQueue() {
  if (!radio.active) return;
  ++_loadTracksRequest;
  _setSearching(false);
  radio.browsingLibrary = false;
  if (_activePl !== null) clearPlaylist();
  state.tracks = [...radio.queue];
  state.total = state.tracks.length;
  state.page = 1;
  state.pages = 1;
  state.currentIdx = isJingle(state.currentTrack)
    ? -1
    : state.tracks.findIndex(track => Number(track.id) === Number(state.currentTrack?.id));
  renderTracks();
  renderPagination();
  fetchMemberships(state.tracks);
  $("result-count").textContent = `${radio.stationName || t().radio} – ${radio.queue.length} Tracks`;
  updateRadioButton();
  document.getElementById("track-list")?.scrollTo({top: 0, behavior: "instant"});
}

function stopRadio() {
  radio.active = false;
  radio.browsingLibrary = false;
  radio.cfActive = false;
  clearTimeout(radio.cfTimer);
  audioB.pause(); audioB.removeAttribute("src"); audioB.load();
  audio.volume = parseFloat($("volume").value) || 0.8;
  updateRadioButton();
  updatePlaybackModeControls();
  if (state.currentTrack) updatePlayView(state.currentTrack);
}

function leaveRadioToLibrary() {
  if (!radio.active) {
    openRadioPanel();
    return;
  }
  finishAdolar4UTrack("stop");
  stopRadio();
  audio.pause();
  audio.removeAttribute("src");
  audio.load();
  state.currentIdx = -1;
  loadTracks(1, true);
}

async function radioNext() {
  if (!radio.active) return;

  if (isJingle(state.currentTrack)) {
    if (!radio.queue.length) {
      const fresh = await loadRadioQueue(20, radio.playedIds.slice(-100));
      radio.queue.push(...fresh);
    }
    if (!radio.queue.length) { stopRadio(); return; }
    if (radio.browsingLibrary) {
      state.currentIdx = -1;
      state.currentTrack = radio.queue[0];
      return;
    }
    state.tracks = [...radio.queue];
    state.currentIdx = 0;
    state.currentTrack = radio.queue[0];
    renderTracks();
    $("result-count").textContent = `${radio.stationName || t().radio} – ${radio.queue.length} Tracks`;
    return;
  }

  if (!radio.queue.length) return;

  // shift played track out
  const done = radio.queue.shift();
  if (done) {
    radio.playedIds.push(done.id);
    radio.tracksSinceJingle++;
  }

  // refill: when queue drops to 5, load 20 more
  if (radio.queue.length <= 5) {
    const fresh = await loadRadioQueue(20, radio.playedIds.slice(-100));
    radio.queue.push(...fresh);
    // trim playedIds to last 100 to avoid unbounded growth
    if (radio.playedIds.length > 100) radio.playedIds = radio.playedIds.slice(-100);
  }

  if (!radio.queue.length) { stopRadio(); return; }

  if (stationHasJingle() && radio.tracksSinceJingle >= stationJingleEvery()) {
    radio.tracksSinceJingle = 0;
    if (!radio.browsingLibrary) {
      state.tracks = [...radio.queue];
      renderTracks();
      $("result-count").textContent = `${radio.stationName || t().radio} – ${radio.queue.length} Tracks`;
    }
    playJingle();
    return;
  }

  if (radio.browsingLibrary) {
    state.currentIdx = -1;
    state.currentTrack = radio.queue[0];
    updatePlayerUI(state.currentTrack);
    return;
  }
  state.tracks = [...radio.queue];
  state.currentIdx = 0;
  state.currentTrack = radio.queue[0];
  renderTracks();
  $("result-count").textContent = `${radio.stationName || t().radio} – ${radio.queue.length} Tracks`;
}

function preloadNext(nextTrack) {
  // Buffer the next track silently so it's ready when crossfade starts
  preloadTrackArtwork(nextTrack);
  if (audioB.getAttribute("src")) return; // already preloading
  audioB.src = `${API}/api/stream/${nextTrack.id}`;
  audioB.volume = 0;
  audioB.preload = "auto";
  audioB.load();
}

function resetNormalCrossfadeBuffer() {
  normalCrossfade.active = false;
  clearTimeout(normalCrossfade.timer);
  normalCrossfade.timer = null;
  if (!radio.active) {
    audioB.pause();
    audioB.removeAttribute("src");
    audioB.load();
    audio.volume = parseFloat($("volume").value) || 0.8;
  }
}

function toggleNormalCrossfade() {
  if (radio.active) return;
  normalCrossfade.enabled = !normalCrossfade.enabled;
  localStorage.setItem("adolar_crossfade", normalCrossfade.enabled ? "1" : "0");
  if (!normalCrossfade.enabled) resetNormalCrossfadeBuffer();
  updatePlaybackModeControls();
}

function startNormalCrossfade() {
  if (radio.active || !normalCrossfade.enabled || normalCrossfade.active) return;
  const nextIndex = state.currentIdx + 1;
  const nextTrack = state.tracks[nextIndex];
  if (!nextTrack) return;
  if (audioB.readyState < 3) {
    audioB.addEventListener("canplay", startNormalCrossfade, { once: true });
    return;
  }

  normalCrossfade.active = true;
  const vol = parseFloat($("volume").value) || 0.8;
  audioB.volume = 0;
  audioB.play().catch(() => {
    resetNormalCrossfadeBuffer();
    playTrack(nextIndex);
  });

  const startTime = performance.now();
  const tick = () => {
    if (!normalCrossfade.active) return;
    const elapsed = (performance.now() - startTime) / 1000;
    const fadeOut = Math.min(elapsed / CF_OUT, 1);
    const fadeIn = Math.min(Math.max(elapsed - (CF_OUT - CF_IN), 0) / CF_IN, 1);
    audio.volume = vol * Math.cos(fadeOut * Math.PI / 2);
    audioB.volume = vol * Math.sin(fadeIn * Math.PI / 2);

    if (elapsed < CF_OUT) {
      normalCrossfade.timer = setTimeout(tick, 50);
      return;
    }

    const nextSrc = audioB.src;
    const nextTime = audioB.currentTime;
    audioB.pause();
    audioB.removeAttribute("src");
    audioB.load();
    normalCrossfade.active = false;
    normalCrossfade.timer = null;
    finishAdolar4UTrack("ended", true);
    state.currentIdx = nextIndex;
    state.currentTrack = nextTrack;
    _scrobbled = false;
    _playCounted = false;
    updatePlayerUI(nextTrack);
    audio.src = nextSrc;
    audio.currentTime = nextTime;
    audio.volume = vol;
    audio.play();
    startAdolar4UTrack(nextTrack);
    renderTracks();
    if (listShuffle.active) ensureListShuffleQueue();
  };
  tick();
}

function startCrossfade() {
  if (radio.cfActive) return;
  // Wait until audioB has enough data to play without interruption
  if (audioB.readyState < 3) { // HAVE_FUTURE_DATA = 3
    audioB.addEventListener("canplay", startCrossfade, { once: true });
    return;
  }
  radio.cfActive = true;
  const vol = parseFloat($("volume").value) || 0.8;

  audioB.volume = 0;
  audioB.play().catch(() => {
    // Autoplay blocked or src invalid — fall back to direct next
    radio.cfActive = false;
    radioNext().then(() => {
      if (!radio.queue.length || isJingle(state.currentTrack)) return;
      radio.browsingLibrary ? playRadioTrack(radio.queue[0]) : playTrack(0);
    });
  });

  const startTime = performance.now();
  const tick = () => {
    const elapsed = (performance.now() - startTime) / 1000;
    const t_out = Math.min(elapsed / CF_OUT, 1);
    const t_in  = Math.min(Math.max(elapsed - (CF_OUT - CF_IN), 0) / CF_IN, 1);
    // Equal-power curve: constant perceived loudness
    audio.volume  = vol * Math.cos(t_out * Math.PI / 2);
    audioB.volume = vol * Math.sin(t_in  * Math.PI / 2);

    if (elapsed < CF_OUT) {
      radio.cfTimer = setTimeout(tick, 50);
    } else {
      const nextSrc  = audioB.src;
      const nextTime = audioB.currentTime;
      audioB.pause(); audioB.removeAttribute("src"); audioB.load();
      radio.cfActive = false;
      finishAdolar4UTrack("ended", true);
      radioNext().then(() => {
        if (!radio.queue.length) return;
        _scrobbled = false;
        _playCounted = false;
        updatePlayerUI(radio.queue[0]);
        audio.src = nextSrc;
        audio.currentTime = nextTime;
        audio.volume = vol;
        audio.play();
        startAdolar4UTrack(state.currentTrack);
        renderTracks();
      });
    }
  };
  tick();
}

// ── Player events ─────────────────────────────────────────
playBtn.onclick = () => audio.paused ? audio.play() : audio.pause();
$("btn-play-view-open").onclick = () => openPlayView(false);
$("player-cover-wrap").onclick = () => openPlayView(false);
$("play-view-close").onclick = closePlayView;
$("play-view-play").onclick = () => playBtn.click();
$("play-view-prev").onclick = () => $("btn-prev").click();
$("play-view-next").onclick = () => $("btn-next").click();
$("play-view-shuffle").onclick = startListShuffle;
$("play-view-crossfade").onclick = toggleNormalCrossfade;
$("play-view-library").onclick = () => {
  closePlayView();
  leaveRadioToLibrary();
};
$("play-view-progress").oninput = e => {
  if (audio.duration) audio.currentTime = (e.target.value / 100) * audio.duration;
};
$("play-view-volume").oninput = e => {
  $("volume").value = e.target.value;
  $("volume").dispatchEvent(new Event("input", { bubbles: true }));
};
$("play-view-love").onclick = () => lfmToggleLove(state.currentTrack, $("play-view-love"));
$("play-view-favorite").onclick = () => toggleFavorite(state.currentTrack, $("play-view-favorite"));
$("play-view-bookmark").onclick = e => {
  e.stopPropagation();
  if (state.currentTrack && !isJingle(state.currentTrack)) {
    _openBookmarkDropdown($("play-view-bookmark"), state.currentTrack.id);
  }
};
document.addEventListener("keydown", e => {
  if (e.key === "Escape" && playViewState.open) closePlayView();
});
setInterval(updatePlayViewClock, 1000);

audio.onplay  = () => {
  playBtn.innerHTML = `<i class="ti ti-player-pause"></i>`;
  $("play-view-play").innerHTML = `<i class="ti ti-player-pause"></i>`;
  $("play-view-play").title = t().pause;
  $("play-view-play").setAttribute("aria-label", t().pause);
  renderTracks();
};
audio.onpause = () => {
  playBtn.innerHTML = `<i class="ti ti-player-play"></i>`;
  $("play-view-play").innerHTML = `<i class="ti ti-player-play"></i>`;
  $("play-view-play").title = t().play;
  $("play-view-play").setAttribute("aria-label", t().play);
  renderTracks();
};
audio.onended = async () => {
  finishAdolar4UTrack("ended", true);
  if (radio.active) {
    if (radio.cfActive) return; // crossfade already handles the transition
    await radioNext();
    if (radio.queue.length && !isJingle(state.currentTrack)) {
      radio.browsingLibrary ? playRadioTrack(radio.queue[0]) : playTrack(0);
    }
  } else if (normalCrossfade.active) {
    return;
  } else if (listShuffle.active) {
    let next = state.currentIdx + 1;
    if (next >= state.tracks.length) {
      await ensureListShuffleQueue(true);
      next = state.currentIdx + 1;
    }
    if (next < state.tracks.length) playTrack(next);
  } else {
    const next = state.currentIdx + 1;
    if (next < state.tracks.length) playTrack(next);
  }
};

let _scrobbled = false;
let _playCounted = false;
audio.ontimeupdate = () => {
  if (!audio.duration) return;
  progress.value = (audio.currentTime / audio.duration) * 100;
  $("time-cur").textContent = fmt(audio.currentTime);
  $("time-dur").textContent = fmt(audio.duration);
  $("play-view-progress").value = progress.value;
  $("play-view-time-cur").textContent = fmt(audio.currentTime);
  $("play-view-time-dur").textContent = fmt(audio.duration);

  if (isJingle(state.currentTrack)) return;

  // Scrobble after 50% playback (and at least 30s played)
  if (!_scrobbled && audio.currentTime >= 30 && audio.currentTime / audio.duration >= 0.5) {
    _scrobbled = true;
    lfmScrobble(state.currentTrack);
  }

  // Increment play count tag at 90% played
  if (!_playCounted && audio.currentTime / audio.duration >= 0.9) {
    _playCounted = true;
    if (state.currentTrack) {
      fetch(`${API}/api/track/${state.currentTrack.id}/played`, { method: "POST" })
        .catch(() => {});
    }
  }

  if (radio.active) {
    const remaining = audio.duration - audio.currentTime;
    const next = radio.queue[1];
    if (next && !jingleDueAfterCurrent()) {
      // Only crossfade if track is long enough (skip CF for short tracks)
      const trackDur = audio.duration || 0;
      const cfEnabled = trackDur > CF_OUT + 2; // need at least CF_OUT+2s
      if (!radio.cfActive && remaining <= CF_PRELOAD) preloadNext(next);
      if (!radio.cfActive && cfEnabled && remaining <= CF_OUT) startCrossfade();
    }
  } else if (normalCrossfade.enabled) {
    const remaining = audio.duration - audio.currentTime;
    const next = state.tracks[state.currentIdx + 1];
    const trackSupportsFade = audio.duration > CF_OUT + 2;
    if (next && !normalCrossfade.active && remaining <= CF_PRELOAD) preloadNext(next);
    if (next && !normalCrossfade.active && trackSupportsFade && remaining <= CF_OUT) {
      startNormalCrossfade();
    }
  }
};

progress.oninput = () => {
  if (audio.duration) audio.currentTime = (progress.value / 100) * audio.duration;
};
$("volume").oninput = e => {
  audio.volume = e.target.value;
  if (!audioB.paused) audioB.volume = e.target.value;
  $("play-view-volume").value = e.target.value;
};
audio.volume = 0.8;

$("btn-prev").onclick = () => {
  if (radio.active) return;
  if (state.currentIdx > 0) playTrack(state.currentIdx - 1);
};
$("btn-next").onclick = async () => {
  finishAdolar4UTrack("manual_next");
  if (radio.active) {
    clearTimeout(radio.cfTimer);
    radio.cfActive = false;
    audioB.pause(); audioB.removeAttribute("src"); audioB.load();
    audio.volume = parseFloat($("volume").value) || 0.8;
    radioNext().then(() => {
      if (radio.queue.length && !isJingle(state.currentTrack)) playTrack(0);
    });
    return;
  }
  if (listShuffle.active) await ensureListShuffleQueue();
  const next = state.currentIdx + 1;
  if (next < state.tracks.length) playTrack(next);
};

window.addEventListener("pagehide", () => finishAdolar4UTrack("stop", false, true));

$("btn-list-shuffle").onclick = startListShuffle;
$("btn-crossfade").onclick = toggleNormalCrossfade;

$("btn-radio").onclick = () => {
  if (radio.active && radio.browsingLibrary) showCurrentRadioQueue();
  else leaveRadioToLibrary();
};
updatePlaybackModeControls();

// ── Radio station management ──────────────────────────────
let _radioStations = [];
let _editingRadioStation = null;
let _radioDraftAfterTest = null;

const RADIO_FIELDS = {
  title: "Titel",
  artist: "Interpret",
  album: "Album",
  genre: "Genre",
  year: "Jahr",
  decade: "Jahrzehnt",
  playcount: "Playcount",
};
const RADIO_TEXT_OPS = {
  contains: "enthält",
  not_contains: "enthält nicht",
};
const RADIO_NUM_OPS = {
  eq: "ist",
  ne: "ist nicht",
  gt: "ist größer",
  lt: "ist kleiner",
};

function _opsForField(field) {
  return ["title", "artist", "album", "genre"].includes(field) ? RADIO_TEXT_OPS : RADIO_NUM_OPS;
}

async function loadRadioStations() {
  try {
    const adminParam = _me?.role === "admin" ? "?admin=1" : "";
    const r = await fetch(`${API}/api/radio-stations${adminParam}`);
    _radioStations = await r.json();
  } catch {
    _radioStations = [{ id: 1, name: "Adolar Radio", description: "", scope: "global", is_system: true, filter: {mode:"all", rules:[]} }];
  }
  renderRadioStations();
}

function openRadioPanel() {
  $("radio-modal").classList.add("open");
  loadRadioStations();
}

function closeRadioPanel() {
  $("radio-modal")?.classList.remove("open");
}

function renderRadioStations() {
  const list = $("radio-station-list");
  if (!list) return;
  list.innerHTML = "";
  if (!_radioStations.length) {
    list.innerHTML = `<div class="empty-state" style="padding:24px">${t().radio_no_stations}</div>`;
    return;
  }
  const groups = [];
  groups.push(["Global", _radioStations.filter(st => st.scope !== "private")]);
  if (_me) {
    groups.push(["Meine privaten Sender", _radioStations.filter(st => st.scope === "private" && st.owner_id === _me.id)]);
  }
  if (_me?.role === "admin") {
    const byOwner = new Map();
    _radioStations
      .filter(st => st.scope === "private" && st.owner_id !== _me.id)
      .forEach(st => {
        const owner = st.owner_name || "Unbekannt";
        if (!byOwner.has(owner)) byOwner.set(owner, []);
        byOwner.get(owner).push(st);
      });
    [...byOwner.entries()].forEach(([owner, items]) => groups.push([`Private Sender von ${owner}`, items]));
  }
  groups.filter(([, items]) => items.length).forEach(([title, items]) => {
    const group = document.createElement("div");
    group.className = "radio-station-group";
    group.innerHTML = `<div class="radio-group-title">${esc(title)}</div>`;
    items.forEach(st => group.appendChild(renderRadioStationRow(st)));
    list.appendChild(group);
  });
  $("btn-radio-new").style.display = _me?.allow_radio_stations ? "inline-flex" : "none";
}

function renderRadioStationRow(st) {
  const row = document.createElement("div");
  row.className = "radio-station-row";
  const isOwner = _me && st.owner_id === _me.id;
  const canEdit = _me?.allow_radio_stations && (
    (_me.role === "admin" && st.is_system) ||
    (!st.is_system && (st.scope === "private" ? (isOwner || _me.role === "admin") : _me.role === "admin"))
  );
  const canDelete = canEdit && !st.is_system;
  row.innerHTML = `
    <div>
      <div class="radio-station-name">${esc(st.name)}</div>
      <div class="radio-station-desc">${esc(st.description || (st.is_system ? "Default" : st.scope === "private" ? "Privat" : "Global"))}</div>
    </div>
    <div class="radio-row-actions">
      ${st.has_jingle ? `<span class="station-jingle-indicator" title="Jingle vorhanden"><i class="ti ti-volume"></i></span>` : ""}
      <button class="icon-btn station-play" title="${t().radio_start}"><i class="ti ti-player-play"></i></button>
      ${canEdit ? `<button class="icon-btn station-edit" title="${t().radio_edit}"><i class="ti ti-settings"></i></button>` : ""}
      ${canDelete ? `<button class="icon-btn danger station-delete" title="${t().radio_delete}"><i class="ti ti-trash"></i></button>` : ""}
    </div>`;
  row.querySelector(".station-play").onclick = () => startRadio(st);
  const edit = row.querySelector(".station-edit");
  if (edit) edit.onclick = () => openRadioEditor(st);
  const del = row.querySelector(".station-delete");
  if (del) del.onclick = async () => {
    if (!confirm(t().radio_delete_confirm(st.name))) return;
    await fetch(`${API}/api/radio-stations/${st.id}`, { method: "DELETE" });
    await loadRadioStations();
  };
  return row;
}

function openRadioEditor(station = null) {
  _editingRadioStation = station;
  $("radio-editor-title").textContent = station ? t().radio_edit : t().radio_new;
  $("radio-name").value = station?.name || "";
  $("radio-desc").value = station?.description || "";
  $("radio-scope-wrap").style.display = _me?.role === "admin" ? "block" : "none";
  $("radio-scope").value = station?.scope || (_me?.role === "admin" ? "global" : "private");
  $("radio-name").disabled = Boolean(station?.is_system);
  $("radio-desc").disabled = Boolean(station?.is_system);
  $("radio-scope").disabled = Boolean(station?.is_system);
  $("radio-jingle-enabled").checked = Boolean(station?.jingle_enabled);
  $("radio-jingle-every").value = station?.jingle_every_tracks || 5;
  $("radio-jingle-file").value = "";
  $("radio-jingle-delete").style.display = station?.has_jingle ? "inline-flex" : "none";
  $("radio-jingle-status").textContent = station?.has_jingle ? "Jingle vorhanden" : "";
  $("radio-error").style.display = "none";
  const filter = station?.filter || { mode: "all", rules: [] };
  const allRules = [];
  const anyRules = [];
  (filter.rules || []).forEach(rule => {
    if (rule.rules && rule.mode === "any") anyRules.push(...rule.rules);
    else if (!rule.rules) allRules.push(rule);
  });
  $("radio-rules-all").innerHTML = "";
  $("radio-rules-any").innerHTML = "";
  (allRules.length ? allRules : [{field:"artist", op:"contains", value:""}]).forEach(r => addRadioRule("all", r));
  anyRules.forEach(r => addRadioRule("any", r));
  $("radio-editor").style.display = "block";
}

function restoreRadioEditorDraft(draft) {
  _editingRadioStation = draft.editingStation;
  $("radio-editor-title").textContent = _editingRadioStation ? t().radio_edit : t().radio_new;
  $("radio-name").value = draft.name || "";
  $("radio-desc").value = draft.description || "";
  $("radio-scope-wrap").style.display = _me?.role === "admin" ? "block" : "none";
  $("radio-scope").value = draft.scope || (_me?.role === "admin" ? "global" : "private");
  $("radio-name").disabled = Boolean(_editingRadioStation?.is_system);
  $("radio-desc").disabled = Boolean(_editingRadioStation?.is_system);
  $("radio-scope").disabled = Boolean(_editingRadioStation?.is_system);
  $("radio-jingle-enabled").checked = Boolean(draft.jingle_enabled);
  $("radio-jingle-every").value = draft.jingle_every_tracks || 5;
  $("radio-jingle-file").value = "";
  $("radio-jingle-delete").style.display = draft.has_jingle ? "inline-flex" : "none";
  $("radio-jingle-status").textContent = draft.has_jingle ? "Jingle vorhanden" : "";
  $("radio-error").style.display = "none";
  $("radio-rules-all").innerHTML = "";
  $("radio-rules-any").innerHTML = "";
  const allRules = [];
  const anyRules = [];
  (draft.filter?.rules || []).forEach(rule => {
    if (rule.rules && rule.mode === "any") anyRules.push(...rule.rules);
    else if (!rule.rules) allRules.push(rule);
  });
  (allRules.length ? allRules : [{field:"artist", op:"contains", value:""}]).forEach(r => addRadioRule("all", r));
  anyRules.forEach(r => addRadioRule("any", r));
  $("radio-editor").style.display = "block";
}

function closeRadioEditor() {
  $("radio-editor").style.display = "none";
  _editingRadioStation = null;
}

function addRadioRule(group, rule = {}) {
  const wrap = group === "any" ? $("radio-rules-any") : $("radio-rules-all");
  const row = document.createElement("div");
  row.className = "radio-rule-row";
  const field = rule.field || "title";
  const ops = _opsForField(field);
  const op = rule.op && ops[rule.op] ? rule.op : Object.keys(ops)[0];
  const val = esc(rule.value ?? "").replace(/"/g, "&quot;");
  row.innerHTML = `
    <select class="radio-select radio-field">${Object.entries(RADIO_FIELDS).map(([v,l]) => `<option value="${v}" ${v===field?"selected":""}>${l}</option>`).join("")}</select>
    <select class="radio-select radio-op">${Object.entries(ops).map(([v,l]) => `<option value="${v}" ${v===op?"selected":""}>${l}</option>`).join("")}</select>
    <input class="radio-input radio-value" type="text" value="${val}">
    <button class="icon-btn danger radio-rule-remove" title="Entfernen"><i class="ti ti-minus"></i></button>`;
  const fieldEl = row.querySelector(".radio-field");
  const opEl = row.querySelector(".radio-op");
  fieldEl.onchange = () => {
    const nextOps = _opsForField(fieldEl.value);
    opEl.innerHTML = Object.entries(nextOps).map(([v,l]) => `<option value="${v}">${l}</option>`).join("");
  };
  row.querySelector(".radio-rule-remove").onclick = () => row.remove();
  wrap.appendChild(row);
}

function readRadioRuleRows(group) {
  const wrap = group === "any" ? $("radio-rules-any") : $("radio-rules-all");
  return [...wrap.querySelectorAll(".radio-rule-row")].map(row => ({
    field: row.querySelector(".radio-field").value,
    op: row.querySelector(".radio-op").value,
    value: row.querySelector(".radio-value").value.trim(),
  })).filter(r => r.value !== "");
}

function buildRadioFilterFromEditor() {
  const allRules = readRadioRuleRows("all");
  const anyRules = readRadioRuleRows("any");
  const rules = [...allRules];
  if (anyRules.length) rules.push({ mode: "any", rules: anyRules });
  return { mode: "all", rules };
}

async function saveRadioJingle(station) {
  const fileEl = $("radio-jingle-file");
  const every = Math.max(1, Math.min(Number($("radio-jingle-every").value || 5), 100));
  const enabled = $("radio-jingle-enabled").checked;
  if (fileEl.files && fileEl.files[0]) {
    const fd = new FormData();
    fd.append("file", fileEl.files[0]);
    fd.append("every", String(every));
    fd.append("enabled", enabled ? "1" : "0");
    const r = await fetch(`${API}/api/radio-stations/${station.id}/jingle`, {
      method: "POST",
      body: fd,
    });
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || "Jingle-Upload fehlgeschlagen");
    return await r.json();
  }
  if (station.has_jingle || _editingRadioStation?.has_jingle) {
    const r = await fetch(`${API}/api/radio-stations/${station.id}/jingle`, {
      method: "PATCH",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({ every, enabled }),
    });
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || "Jingle-Einstellungen fehlgeschlagen");
    return await r.json();
  }
  return station;
}

async function deleteRadioJingle() {
  if (!_editingRadioStation) return;
  const err = $("radio-error");
  err.style.display = "none";
  const r = await fetch(`${API}/api/radio-stations/${_editingRadioStation.id}/jingle`, { method: "DELETE" });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    err.textContent = d.error || "Jingle löschen fehlgeschlagen";
    err.style.display = "block";
    return;
  }
  _editingRadioStation = await r.json();
  $("radio-jingle-enabled").checked = false;
  $("radio-jingle-every").value = _editingRadioStation.jingle_every_tracks || 5;
  $("radio-jingle-file").value = "";
  $("radio-jingle-delete").style.display = "none";
  $("radio-jingle-status").textContent = "";
  await loadRadioStations();
}

async function saveRadioStation() {
  const err = $("radio-error");
  err.style.display = "none";
  if (_editingRadioStation?.is_system) {
    try {
      await saveRadioJingle(_editingRadioStation);
    } catch (e) {
      err.textContent = e.message || "Jingle speichern fehlgeschlagen";
      err.style.display = "block";
      return;
    }
    closeRadioEditor();
    await loadRadioStations();
    return;
  }
  const name = $("radio-name").value.trim();
  if (!name) {
    err.textContent = t().radio_name;
    err.style.display = "block";
    return;
  }
  const payload = {
    name,
    description: $("radio-desc").value.trim(),
    scope: $("radio-scope").value,
    filter: buildRadioFilterFromEditor(),
  };
  const url = _editingRadioStation
    ? `${API}/api/radio-stations/${_editingRadioStation.id}`
    : `${API}/api/radio-stations`;
  const r = await fetch(url, {
    method: _editingRadioStation ? "PUT" : "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(payload),
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    err.textContent = d.error || "Speichern fehlgeschlagen";
    err.style.display = "block";
    return;
  }
  try {
    const station = await r.json();
    await saveRadioJingle(station);
  } catch (e) {
    err.textContent = e.message || "Jingle speichern fehlgeschlagen";
    err.style.display = "block";
    return;
  }
  closeRadioEditor();
  await loadRadioStations();
}

async function testRadioStationFilter() {
  const err = $("radio-error");
  err.style.display = "none";
  const filter = buildRadioFilterFromEditor();
  _radioDraftAfterTest = {
    editingStation: _editingRadioStation,
    name: $("radio-name").value.trim(),
    description: $("radio-desc").value.trim(),
    scope: $("radio-scope").value,
    filter,
    jingle_enabled: $("radio-jingle-enabled").checked,
    jingle_every_tracks: Number($("radio-jingle-every").value || 5),
    has_jingle: _editingRadioStation?.has_jingle || false,
  };
  const payload = { filter, count: 50 };
  const r = await fetch(`${API}/api/radio-stations/test`, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(payload),
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    err.textContent = d.error || "Test fehlgeschlagen";
    err.style.display = "block";
    return;
  }
  const data = await r.json();
  stopRadio();
  state.tracks = data.results || [];
  state.total = data.total || state.tracks.length;
  state.page = 1;
  state.pages = 1;
  renderTracks();
  renderPagination();
  $("result-count").textContent = `Test – ${state.tracks.length} Tracks`;
  $("radio-test-label").textContent = `Testansicht: ${_radioDraftAfterTest.name || "Neuer Sender"} – ${state.tracks.length} Tracks`;
  $("radio-test-banner").classList.add("visible");
  closeRadioPanel();
  document.getElementById('track-list')?.scrollTo({ top: 0, behavior: 'instant' });
}

function returnToRadioDraft() {
  if (!_radioDraftAfterTest) return;
  openRadioPanel();
  restoreRadioEditorDraft(_radioDraftAfterTest);
}

function setupRadioModalDrag() {
  const box = $("radio-modal-box");
  const head = $("radio-modal-head");
  if (!box || !head) return;
  let drag = null;
  head.addEventListener("pointerdown", e => {
    if (e.target.closest("button")) return;
    const r = box.getBoundingClientRect();
    box.style.position = "fixed";
    box.style.left = `${r.left}px`;
    box.style.top = `${r.top}px`;
    box.style.width = `${r.width}px`;
    box.style.margin = "0";
    drag = { dx: e.clientX - r.left, dy: e.clientY - r.top };
    head.setPointerCapture(e.pointerId);
  });
  head.addEventListener("pointermove", e => {
    if (!drag) return;
    const maxLeft = Math.max(0, window.innerWidth - box.offsetWidth);
    const maxTop = Math.max(0, window.innerHeight - Math.min(box.offsetHeight, window.innerHeight));
    const left = Math.min(Math.max(0, e.clientX - drag.dx), maxLeft);
    const top = Math.min(Math.max(0, e.clientY - drag.dy), maxTop);
    box.style.left = `${left}px`;
    box.style.top = `${top}px`;
  });
  head.addEventListener("pointerup", e => {
    drag = null;
    try { head.releasePointerCapture(e.pointerId); } catch {}
  });
}

// ── Mini-Player Popup ─────────────────────────────────────
const miniCh = new BroadcastChannel("adolar-player");
let miniWin = null;

function miniIsOpen() {
  return miniWin && !miniWin.closed;
}

function broadcastTrack(t) {
  if (!miniIsOpen()) return;
  const key = t && !isJingle(t) ? `${t.artist}||${t.title}` : null;
  const loved = key ? (lfm.lovedCache.get(key) || false) : false;
  miniCh.postMessage({
    type: "track", track: t, playing: !audio.paused, loved,
    favorite: Boolean(t && _favoriteIds.has(Number(t.id))),
    lfmConnected: lfm.connected,
  });
}

function broadcastPlayState() {
  if (!miniIsOpen()) return;
  miniCh.postMessage({ type: "playstate", playing: !audio.paused });
}

function broadcastLoved(loved) {
  if (!miniIsOpen()) return;
  miniCh.postMessage({ type: "loved", loved });
}

function broadcastFavorite(favorite) {
  if (!miniIsOpen()) return;
  miniCh.postMessage({ type: "favorite", favorite });
}

function broadcastProgress() {
  if (!miniIsOpen() || !audio.duration) return;
  miniCh.postMessage({ type: "progress", pct: (audio.currentTime / audio.duration) * 100, cur: audio.currentTime, dur: audio.duration });
}

audio.addEventListener("play",  broadcastPlayState);
audio.addEventListener("pause", broadcastPlayState);
audio.addEventListener("timeupdate", broadcastProgress);

// Commands from popup
miniCh.onmessage = e => {
  const msg = e.data;
  if (msg.type === "hello") {
    // Popup just opened — send current state
    if (state.currentTrack) broadcastTrack(state.currentTrack);
    else miniCh.postMessage({ type: "playstate", playing: false });
    miniCh.postMessage({ type: "lfm", connected: lfm.connected });
    return;
  }
  if (msg.type === "popup-closed") { miniWin = null; return; }
  if (msg.type !== "cmd") return;
  if (msg.cmd === "toggle")  audio.paused ? audio.play() : audio.pause();
  if (msg.cmd === "next")    $("btn-next").click();
  if (msg.cmd === "prev")    $("btn-prev").click();
  if (msg.cmd === "love")    lfmToggleLove(state.currentTrack, $("player-love"));
  if (msg.cmd === "favorite") toggleFavorite(state.currentTrack, $("player-favorite"));
  if (msg.cmd === "seek" && audio.duration) audio.currentTime = (msg.value / 100) * audio.duration;
};

$("btn-miniplayer").onclick = () => {
  if (miniIsOpen()) { miniWin.focus(); return; }
  miniWin = window.open("/miniplayer", "adolar-mini",
    "width=320,height=200,resizable=no,toolbar=no,menubar=no,location=no,status=no");
};

function updateMiniPlayer(t) {
  broadcastTrack(t);
}

// ── Last.fm ────────────────────────────────────────────────
const lfm = { connected: false, username: null, autoLoveFavorites: true, lovedCache: new Map() };

async function lfmInit() {
  try {
    const res = await fetch(`${API}/api/lastfm/status`);
    const data = await res.json();
    lfm.connected = data.connected;
    lfm.username  = data.username;
    lfm.autoLoveFavorites = data.auto_love_favorites !== false;
  } catch { lfm.connected = false; }
  renderLfmStatus();
}

function renderLfmStatus() {
  const el = $("lastfm-status");
  if (!el) return;
  if (lfm.connected) {
    el.innerHTML = `
      <img src="https://cdn.jsdelivr.net/npm/simple-icons@v11/icons/lastdotfm.svg"
           width="14" height="14" style="filter:invert(.5) sepia(1) saturate(3) hue-rotate(310deg);opacity:.8">
      <span>${esc(lfm.username)}</span>
      <button id="lastfm-connect" onclick="lfmDisconnect()" title="${t().lfm_disconnect}">✕</button>`;
    $("player-love").style.display = "";
    $("btn-loved-filter").style.display = "flex";
    $("btn-loved-sync").style.display = "flex";
    $("btn-pc-sync").style.display = "flex";
  } else {
    el.innerHTML = `
      <button id="lastfm-connect" onclick="location.href='/api/lastfm/auth'">
        <img src="https://cdn.jsdelivr.net/npm/simple-icons@v11/icons/lastdotfm.svg"
             width="13" height="13" style="filter:invert(.5) sepia(1) saturate(3) hue-rotate(310deg)">
        ${t().lfm_connect}
      </button>`;
    $("player-love").style.display = "none";
    $("btn-loved-filter").style.display = "none";
    $("btn-loved-sync").style.display = "none";
    $("btn-pc-sync").style.display = "none";
    state.filters.loved = false;
    updateLovedFilterButton();
  }
}

function toggleWartung() {
  const panel = $("wartung-panel");
  const chevron = $("wartung-chevron");
  const open = panel.style.display === "block";
  panel.style.display = open ? "none" : "block";
  chevron.className = open ? "ti ti-chevron-down" : "ti ti-chevron-up";
}

let monitorPollTimer = null;

function formatMonitorBytes(bytes) {
  const value = Number(bytes || 0);
  if (value >= 1024 ** 3) return `${(value / 1024 ** 3).toFixed(1)} GB`;
  return `${(value / 1024 ** 2).toFixed(0)} MB`;
}

function formatMonitorDate(timestamp) {
  return new Date(Number(timestamp) * 1000).toLocaleString(
    lang === "en" ? "en-GB" : "de-DE",
    {dateStyle: "short", timeStyle: "medium"},
  );
}

function monitorProductName(product) {
  return ({
    adolar_web: "Adolar Web",
    companion: "Companion",
    android: "Android",
  })[product] || product;
}

function renderMonitorConnections(target, rows, isCurrent) {
  if (!rows.length) {
    target.innerHTML = `<div class="monitor-empty">${isCurrent ? "Keine aktive Verbindung." : "Noch keine Verbindung erfasst."}</div>`;
    return;
  }
  target.innerHTML = `<table class="monitor-table">
    <thead><tr><th>Benutzer</th><th>Produkt</th><th>Datum / Uhrzeit</th><th>IP-Adresse</th></tr></thead>
    <tbody>${rows.map(row => `<tr>
      <td>${isCurrent ? '<span class="monitor-live"></span>' : ''}${esc(row.username)}</td>
      <td>${esc(monitorProductName(row.product))}</td>
      <td>${esc(formatMonitorDate(row.connected_at))}</td>
      <td>${esc(row.ip_address)}</td>
    </tr>`).join("")}</tbody>
  </table>`;
}

async function loadMonitor() {
  if ($("monitor-modal").style.display !== "flex") return;
  try {
    const response = await fetch("/api/admin/monitor", {cache: "no-store"});
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Monitor nicht erreichbar");
    const system = data.system;
    $("monitor-cpu-value").textContent = `${system.cpu_percent.toFixed(1)} %`;
    $("monitor-cpu-bar").style.width = `${Math.min(100, system.cpu_percent)}%`;
    $("monitor-cpu-detail").textContent = `${system.cpu_count} logische CPU${system.cpu_count === 1 ? "" : "s"}`;
    $("monitor-ram-value").textContent = `${system.memory_percent.toFixed(1)} %`;
    $("monitor-ram-bar").style.width = `${Math.min(100, system.memory_percent)}%`;
    $("monitor-ram-detail").textContent = `${formatMonitorBytes(system.memory_used)} / ${formatMonitorBytes(system.memory_total)}`;
    renderMonitorConnections($("monitor-current"), data.current_connections || [], true);
    renderMonitorConnections($("monitor-recent"), data.recent_connections || [], false);
    $("monitor-status").textContent = `Aktualisiert: ${formatMonitorDate(data.sampled_at)} · automatisch alle 3 Sekunden`;
  } catch (error) {
    $("monitor-status").textContent = error.message;
  } finally {
    if ($("monitor-modal").style.display === "flex") {
      monitorPollTimer = setTimeout(loadMonitor, 3000);
    }
  }
}

function openMonitor() {
  if (!_me || _me.role !== "admin") return;
  $("monitor-modal").style.display = "flex";
  $("monitor-status").textContent = "Monitor wird geladen…";
  clearTimeout(monitorPollTimer);
  loadMonitor();
}

function closeMonitor() {
  $("monitor-modal").style.display = "none";
  clearTimeout(monitorPollTimer);
  monitorPollTimer = null;
}

let backupPollTimer = null;

function formatBackupBytes(value) {
  const bytes = Number(value || 0);
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(2)} GB`;
  if (bytes >= 1024 ** 2) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  return `${Math.round(bytes / 1024)} KB`;
}

function openDatabaseManager() {
  if (!_me || _me.role !== "admin") return;
  $("database-modal").style.display = "flex";
  loadBackupState();
  loadDatabaseLibraryPicker();
}

function closeDatabaseManager() {
  $("database-modal").style.display = "none";
  if (backupPollTimer) {
    clearTimeout(backupPollTimer);
    backupPollTimer = null;
  }
}

async function loadDatabaseLibraryPicker() {
  const select = $("db-library-select");
  try {
    const response = await fetch("/api/admin/libraries");
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Bibliotheken nicht erreichbar");
    select.innerHTML = data.libraries.map(lib =>
      `<option value="${esc(lib.id)}" ${lib.id === data.active_id ? "selected" : ""}>${esc(lib.name)}</option>`,
    ).join("");
  } catch (error) {
    select.innerHTML = `<option>${esc(error.message)}</option>`;
  }
}

async function optimizeDatabase() {
  const button = $("btn-db-optimize");
  const message = $("db-optimize-message");
  button.disabled = true;
  message.textContent = "";
  const original = button.innerHTML;
  button.innerHTML = '<i class="ti ti-loader"></i> Optimiert…';
  try {
    const response = await fetch("/api/admin/database/optimize", { method: "POST" });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Optimierung fehlgeschlagen");
    message.textContent =
      `Content-DB: ${data.content.integrity_check} · Control-DB: ${data.control.integrity_check} · VACUUM + Statistiken aktualisiert.`;
  } catch (error) {
    message.innerHTML = `<span style="color:#e58b8b">${esc(error.message)}</span>`;
  } finally {
    button.disabled = false;
    button.innerHTML = original;
  }
}

function openLibraryManager() {
  if (!_me || _me.role !== "admin") return;
  $("library-modal").style.display = "flex";
  $("lib-message").textContent = "";
  loadLibraryState();
}

function closeLibraryManager() {
  $("library-modal").style.display = "none";
}

let _libraryState = null;

async function loadLibraryState() {
  const message = $("lib-message");
  try {
    const response = await fetch("/api/admin/libraries");
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Bibliotheken nicht erreichbar");
    _libraryState = data;
    const active = data.libraries.find(lib => lib.id === data.active_id) || data.libraries[0];

    $("lib-current-path").textContent = active
      ? `${active.name} — ${active.music_path}`
      : "Keine Bibliothek vorhanden.";
    $("lib-move-old-path").textContent = active ? `Aktueller Pfad: ${active.music_path}` : "";

    const switchSection = $("lib-switch-section");
    if (data.libraries.length > 1) {
      switchSection.style.display = "block";
      $("lib-switch-select").innerHTML = data.libraries.map(lib =>
        `<option value="${esc(lib.id)}" ${lib.id === data.active_id ? "selected" : ""}>${esc(lib.name)}</option>`,
      ).join("");
    } else {
      switchSection.style.display = "none";
    }
  } catch (error) {
    message.innerHTML = `<span style="color:#e58b8b">${esc(error.message)}</span>`;
  }
}

async function switchLibrary() {
  const message = $("lib-message");
  const libraryId = $("lib-switch-select").value;
  const button = $("btn-lib-switch");
  button.disabled = true;
  try {
    const response = await fetch(`/api/admin/libraries/${libraryId}/activate`, { method: "POST" });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Wechsel fehlgeschlagen");
    message.textContent = `Bibliothek "${data.name}" ist jetzt aktiv.`;
    await loadLibraryState();
    loadTracks(1, true);
  } catch (error) {
    message.innerHTML = `<span style="color:#e58b8b">${esc(error.message)}</span>`;
  } finally {
    button.disabled = false;
  }
}

async function createLibrary() {
  const message = $("lib-message");
  const name = $("lib-new-name").value.trim();
  const musicPath = $("lib-new-path").value.trim();
  const button = $("btn-lib-create");
  button.disabled = true;
  try {
    const response = await fetch("/api/admin/libraries", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({ name, music_path: musicPath }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Anlegen fehlgeschlagen");
    message.textContent = `Bibliothek "${data.name}" angelegt und aktiv.`;
    $("lib-new-name").value = "";
    $("lib-new-path").value = "";
    await loadLibraryState();
    loadTracks(1, true);
  } catch (error) {
    message.innerHTML = `<span style="color:#e58b8b">${esc(error.message)}</span>`;
  } finally {
    button.disabled = false;
  }
}

async function moveLibrary() {
  const message = $("lib-message");
  const newPath = $("lib-move-new-path").value.trim();
  const activeId = _libraryState?.active_id;
  if (!activeId) return;
  const button = $("btn-lib-move");
  button.disabled = true;
  try {
    const response = await fetch(`/api/admin/libraries/${activeId}/move`, {
      method: "PUT",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({ new_music_path: newPath }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Umzug fehlgeschlagen");
    message.textContent = `Pfad aktualisiert, ${data.tracks_updated} Track(s) angepasst.`;
    $("lib-move-new-path").value = "";
    await loadLibraryState();
  } catch (error) {
    message.innerHTML = `<span style="color:#e58b8b">${esc(error.message)}</span>`;
  } finally {
    button.disabled = false;
  }
}

async function rescanLibrary() {
  await fetch(`${API}/api/scan/start`, { method: "POST" });
  showBanner("Bibliothek wird gescannt…");
  startScanPolling();
  $("lib-message").textContent = "Scan gestartet.";
}

async function readLibraryCovers() {
  const message = $("lib-message");
  try {
    const response = await fetch("/api/admin/library/covers", { method: "POST" });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Cover-Einlesen fehlgeschlagen");
    message.textContent = "Cover-Verarbeitung gestartet.";
  } catch (error) {
    message.innerHTML = `<span style="color:#e58b8b">${esc(error.message)}</span>`;
  }
}

// Wired on DOMContentLoaded, not at top level: these elements live in modals
// placed after this <script> tag in the HTML, so they don't exist yet when
// this file first runs (a plain <script src> executes synchronously at the
// point the parser reaches it — referencing them here directly used to throw
// "Cannot set properties of null", which silently aborted the rest of this
// script, including loadMe()/loadTracks() at the bottom of the file).
document.addEventListener("DOMContentLoaded", () => {
  $("db-library-select").onchange = async () => {
    const libraryId = $("db-library-select").value;
    await fetch(`/api/admin/libraries/${libraryId}/activate`, { method: "POST" });
    await loadBackupState();
  };
  $("btn-db-optimize").onclick = optimizeDatabase;
  $("btn-lib-switch").onclick = switchLibrary;
  $("btn-lib-create").onclick = createLibrary;
  $("btn-lib-move").onclick = moveLibrary;
  $("btn-lib-rescan").onclick = rescanLibrary;
  $("btn-lib-covers").onclick = readLibraryCovers;
  $("btn-backup-create").onclick = startDatabaseBackup;
  $("btn-backup-config-save").onclick = saveBackupConfig;
});

function renderBackupState(data) {
  const summary = $("backup-summary");
  const status = data.status || {state: "idle"};
  const schedule = data.automatic
    ? `Automatisch täglich ab ${String(data.hour).padStart(2, "0")}:00 Uhr`
    : "Automatische Sicherung deaktiviert";
  if (status.state === "running") {
    summary.innerHTML = `<i class="ti ti-loader"></i> Sicherung läuft…<br>${esc(schedule)}`;
  } else if (status.state === "failed") {
    summary.innerHTML = `<span style="color:#e58b8b">Letzte Sicherung fehlgeschlagen:</span><br>${esc(status.error || "Unbekannter Fehler")}`;
  } else {
    summary.textContent = `${schedule} · ${data.retention} Sicherungen werden aufbewahrt`;
  }

  $("backup-cfg-path").value = data.configured_path || "";
  $("backup-cfg-enabled").checked = !!data.automatic;
  $("backup-cfg-hour").value = data.hour;
  $("backup-cfg-retention").value = data.retention;

  const backups = data.backups || [];
  $("backup-list").innerHTML = backups.length ? backups.map(item => {
    const id = item.backup_id;
    const date = new Date(item.created_at).toLocaleString("de-DE");
    const jingleLink = item.radio_jingles?.count
      ? `<a href="/api/admin/backups/${id}/jingles">Jingles (${item.radio_jingles.count})</a>`
      : "";
    return `<div class="backup-item">
      <div class="backup-item-head">${esc(date)} · ${formatBackupBytes(item.size)}</div>
      <div class="backup-item-actions">
        <a href="/api/admin/backups/${id}/database">Datenbank</a>
        ${jingleLink}
        <a href="/api/admin/backups/${id}/manifest">Prüfdaten</a>
        <button class="backup-delete" data-backup-id="${id}" title="Sicherung löschen"><i class="ti ti-trash"></i></button>
      </div>
    </div>`;
  }).join("") : `<div>Noch keine Sicherung vorhanden.</div>`;

  $("backup-list").querySelectorAll(".backup-delete").forEach(button => {
    button.onclick = () => deleteBackup(button.dataset.backupId);
  });
  $("btn-backup-create").disabled = status.state === "running";
  if (status.state === "running") {
    backupPollTimer = setTimeout(loadBackupState, 2000);
  }
}

async function loadBackupState() {
  if ($("database-modal").style.display !== "flex") return;
  try {
    const response = await fetch("/api/admin/backups");
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Backup-Ziel nicht erreichbar");
    renderBackupState(data);
  } catch (error) {
    $("backup-summary").innerHTML = `<span style="color:#e58b8b">${esc(error.message)}</span>`;
    $("backup-list").innerHTML = "";
  }
}

async function startDatabaseBackup() {
  const button = $("btn-backup-create");
  button.disabled = true;
  button.classList.add("running");
  button.innerHTML = `<i class="ti ti-loader"></i><span>Sicherung wird gestartet…</span>`;
  try {
    const response = await fetch("/api/admin/backups", {method: "POST"});
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Sicherung konnte nicht gestartet werden");
    setTimeout(loadBackupState, 400);
  } catch (error) {
    $("backup-summary").innerHTML = `<span style="color:#e58b8b">${esc(error.message)}</span>`;
  } finally {
    button.classList.remove("running");
    button.innerHTML = `<i class="ti ti-device-floppy"></i><span>Jetzt sichern</span>`;
  }
}

async function deleteBackup(backupId) {
  if (!confirm("Diese Datensicherung wirklich löschen?")) return;
  const response = await fetch(`/api/admin/backups/${backupId}`, {method: "DELETE"});
  if (response.ok) await loadBackupState();
}

async function saveBackupConfig() {
  const button = $("btn-backup-config-save");
  const message = $("backup-config-message");
  button.disabled = true;
  message.textContent = "";
  try {
    const response = await fetch("/api/admin/backups/config", {
      method: "PUT",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        enabled: $("backup-cfg-enabled").checked,
        hour: Number($("backup-cfg-hour").value),
        retention: Number($("backup-cfg-retention").value),
        path: $("backup-cfg-path").value,
      }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Zeitplan konnte nicht gespeichert werden");
    message.textContent = "Gespeichert.";
    await loadBackupState();
  } catch (error) {
    message.innerHTML = `<span style="color:#e58b8b">${esc(error.message)}</span>`;
  } finally {
    button.disabled = false;
  }
}

async function lfmDisconnect() {
  await fetch(`${API}/api/lastfm/disconnect`, { method: "POST" });
  lfm.connected = false; lfm.username = null;
  lfm.lovedCache.clear();
  state.filters.loved = false;
  miniCh.postMessage({ type: "lfm", connected: false, loved: false });
  renderLfmStatus();
  renderLastFmModal();
  renderTracks();
}

function openLastFmSettings() {
  $("user-dropdown").classList.remove("open");
  renderLastFmModal();
  $("lastfm-modal").style.display = "flex";
}

function renderLastFmModal() {
  const status = $("lastfm-modal-status");
  if (!status) return;
  status.textContent = lfm.connected
    ? `Verbunden als ${lfm.username}. Scrobbles, Loved-Titel und Importe gehören nur zu diesem Adolar-Benutzer.`
    : "Verbinde dein eigenes Last.fm-Konto, ohne dein Passwort in Adolar einzugeben.";
  $("lastfm-auto-love-row").style.display = lfm.connected ? "flex" : "none";
  $("lastfm-sync-actions").style.display = lfm.connected ? "flex" : "none";
  $("lastfm-auto-love").checked = lfm.autoLoveFavorites;
  $("lastfm-modal-connect").style.display = lfm.connected ? "none" : "inline-flex";
  $("lastfm-modal-disconnect").style.display = lfm.connected ? "inline-flex" : "none";
}

async function saveLastFmSettings() {
  const enabled = $("lastfm-auto-love").checked;
  const r = await fetch("/api/lastfm/settings", {
    method: "PATCH", headers: {"Content-Type":"application/json"},
    body: JSON.stringify({auto_love_favorites: enabled}),
  });
  if (r.ok) lfm.autoLoveFavorites = enabled;
}

async function lfmScrobble(track) {
  if (!lfm.connected || !track || isJingle(track)) return;
  fetch(`${API}/api/lastfm/scrobble`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ artist: track.artist, title: track.title }),
  }).catch(() => {});
}

async function lfmToggleLove(track, btn) {
  if (!lfm.connected || !track || isJingle(track)) return;
  const key    = `${track.artist}||${track.title}`;
  const isLoved = lfm.lovedCache.get(key) || false;
  const action  = isLoved ? "unlove" : "love";
  try {
    await fetch(`${API}/api/lastfm/love`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ artist: track.artist, title: track.title, action }),
    });
    lfm.lovedCache.set(key, !isLoved);
    applyLovedState(btn, !isLoved);
    broadcastLoved(!isLoved);
    // update all matching heart buttons in track list
    document.querySelectorAll(`.btn-love[data-key="${CSS.escape(key)}"]`).forEach(b => applyLovedState(b, !isLoved));
  } catch (e) { console.error("Last.fm love failed", e); }
}

function updateLovedFilterButton() {
  const btn = $("btn-loved-filter");
  if (!btn) return;
  btn.classList.toggle("active", state.filters.loved);
  btn.innerHTML = `<i class="ti ${state.filters.loved ? "ti-heart-filled" : "ti-heart"}"></i><span>${t().lfm_loved_filter}</span>`;
}

function updateLovedSyncButton(running = false) {
  const btn = $("btn-loved-sync");
  if (btn) {
    btn.classList.toggle("running", running);
    btn.disabled = running;
    btn.innerHTML = running
      ? `<i class="ti ti-loader"></i><span>${t().lfm_loved_syncing}</span>`
      : `<i class="ti ti-refresh"></i><span>${t().lfm_loved_sync}</span>`;
  }
  if ($("lastfm-modal-loved-sync")) $("lastfm-modal-loved-sync").disabled = running;
}

let _lovedPollTimer = null;

async function pollLovedSync() {
  try {
    const response = await fetch(`${API}/api/lastfm/loved/status`);
    const status = await response.json();
    if (status.running) {
      updateLovedSyncButton(true);
      _lovedPollTimer = setTimeout(pollLovedSync, 1500);
      return;
    }
    updateLovedSyncButton(false);
    clearTimeout(_lovedPollTimer);
    if (state.filters.loved) loadTracks(1, true);
  } catch {
    updateLovedSyncButton(false);
  }
}

async function startLovedSync() {
  if (!lfm.connected) return;
  try {
    updateLovedSyncButton(true);
    const response = await fetch(`${API}/api/lastfm/loved/sync`, { method: "POST" });
    if (!response.ok && response.status !== 409) throw new Error("sync failed");
    _lovedPollTimer = setTimeout(pollLovedSync, 500);
  } catch {
    updateLovedSyncButton(false);
  }
}

$("btn-loved-filter").onclick = () => {
  if (!lfm.connected) return;
  const activating = !state.filters.loved;
  if (activating) {
    clearPlaylist();
    resetFilters();
    resetFilterUI();
    state.sort = "artist";
    $("sort-select").value = "artist";
  }
  state.filters.loved = activating;
  updateLovedFilterButton();
  loadTracks(1, true);
};

$("btn-loved-sync").onclick = () => startLovedSync();

// ── Last.fm Playcount Sync ────────────────────────────────
let _pcPollTimer = null;

function updatePcSyncButton(running = false, done = 0, total = 0) {
  const btn = $("btn-pc-sync");
  if (!btn) return;
  btn.disabled = running;
  btn.innerHTML = running
    ? `<i class="ti ti-loader"></i><span>${t().lfm_pc_syncing(done, total)}</span>`
    : `<i class="ti ti-chart-bar"></i><span>${t().lfm_pc_sync}</span>`;
}

async function pollPcSync() {
  try {
    const r = await fetch(`${API}/api/lastfm/playcount/status`);
    const s = await r.json();
    if (s.running) {
      updatePcSyncButton(true, s.done, s.total);
      _pcPollTimer = setTimeout(pollPcSync, 2000);
    } else {
      updatePcSyncButton(false);
      clearTimeout(_pcPollTimer);
      loadTracks(1, true); // refresh to show updated counts
    }
  } catch {
    updatePcSyncButton(false);
  }
}

async function startLastFmPlaycountSync() {
  if (!lfm.connected) return;
  try {
    const r = await fetch(`${API}/api/lastfm/playcount/sync`, { method: "POST" });
    if (!r.ok) return;
    updatePcSyncButton(true, 0, 0);
    _pcPollTimer = setTimeout(pollPcSync, 1000);
  } catch {}
}

$("btn-pc-sync").onclick = () => startLastFmPlaycountSync();

$("btn-pc-tags").onclick = async () => {
  const btn = $("btn-pc-tags");
  btn.disabled = true;
  btn.innerHTML = `<i class="ti ti-loader"></i><span>Tags werden geschrieben…</span>`;
  try {
    await fetch(`${API}/api/playcount-tags/sync`, { method: "POST" });
    let status;
    do {
      await new Promise(resolve => setTimeout(resolve, 750));
      const r = await fetch(`${API}/api/playcount-tags/status`);
      status = await r.json();
    } while (status.running);
    btn.innerHTML = `<i class="ti ti-device-floppy"></i><span>${status.written} geschrieben, ${status.pending} offen</span>`;
  } catch {
    btn.innerHTML = `<i class="ti ti-alert-triangle"></i><span>Tag-Abgleich fehlgeschlagen</span>`;
  } finally {
    btn.disabled = false;
  }
};

function applyLovedState(btn, loved) {
  if (!btn) return;
  btn.classList.toggle("loved", loved);
  btn.title = loved ? t().lfm_unlove : t().lfm_love;
  btn.innerHTML = loved
    ? `<i class="ti ti-heart-filled"></i>`
    : `<i class="ti ti-heart"></i>`;
}

// Player love button
$("player-love").onclick = () => lfmToggleLove(state.currentTrack, $("player-love"));
$("player-favorite").onclick = () => toggleFavorite(state.currentTrack, $("player-favorite"));

// ── Chip filters ───────────────────────────────────────────
function setupChips(groupId, filterKey) {
  const group = $(groupId);
  group.addEventListener("click", e => {
    const chip = e.target.closest(".chip");
    if (!chip) return;
    group.querySelectorAll(".chip").forEach(c => c.classList.remove("active"));
    chip.classList.add("active");
    state.filters[filterKey] = chip.dataset.val;
    loadTracks(1);
  });
}
// Genre: "Alle" togglet Sichtbarkeit der einzelnen Genres
$("chip-genre-alle").onclick = () => {
  const list = $("chips-genre-list");
  const isOpen = list.style.display !== "none";
  if (isOpen) {
    // Einklappen + Filter zurücksetzen
    list.style.display = "none";
    $("chips-genre-inner").querySelectorAll(".chip").forEach(c => c.classList.remove("active"));
    $("chip-genre-alle").classList.add("active");
    state.filters.genre = "";
    loadTracks(1);
  } else {
    // Ausklappen
    list.style.display = "block";
    $("chip-genre-alle").classList.remove("active");
  }
};

$("chips-genre-inner").addEventListener("click", e => {
  const chip = e.target.closest(".chip");
  if (!chip) return;
  $("chips-genre-inner").querySelectorAll(".chip").forEach(c => c.classList.remove("active"));
  chip.classList.add("active");
  state.filters.genre = chip.dataset.val;
  loadTracks(1);
});

setupChips("chips-decade", "decade");
setupChips("chips-format", "format");

// ── Feldsuche (Interpret, Titel, Album) ────────────────────
const fieldSearchTimers = {};

function setupFieldSearch(alleId, panelId, inputId, filterKey) {
  const alle = $(alleId);
  const panel = $(panelId);
  const input = $(inputId);

  alle.onclick = () => {
    const isOpen = panel.style.display !== "none";
    if (isOpen) {
      panel.style.display = "none";
      alle.classList.add("active");
      input.value = "";
      state.filters[filterKey] = "";
      if (filterKey === "album_query") state.albumView.drilled = null;
      loadTracks(1);
    } else {
      panel.style.display = "block";
      alle.classList.remove("active");
      input.focus();
    }
  };

  input.oninput = () => {
    clearTimeout(fieldSearchTimers[filterKey]);
    fieldSearchTimers[filterKey] = setTimeout(() => {
      state.filters[filterKey] = input.value.trim();
      if (filterKey === "album_query") state.albumView.drilled = null;
      loadTracks(1);
    }, 350);
  };
}

$("btn-back-to-albums").onclick = backToAlbumGrid;

setupFieldSearch("chip-artist-alle", "artist-search-panel", "artist-search", "artist_query");
setupFieldSearch("chip-title-alle",  "title-search-panel",  "title-search",  "title_query");
setupFieldSearch("chip-album-alle",  "album-search-panel",  "album-search",  "album_query");

// ── Range sliders ──────────────────────────────────────────
$("sl-min-dur").oninput = function() {
  const v = +this.value;
  state.filters.min_dur = v;
  $("sl-min-dur-val").textContent = v > 0 ? fmt(v) : "0:00";
  loadTracks(1);
};
$("sl-max-dur").oninput = function() {
  const v = +this.value;
  state.filters.max_dur = v >= 3600 ? 0 : v;
  $("sl-max-dur-val").textContent = v >= 3600 ? "–" : fmt(v);
  loadTracks(1);
};
$("sl-bitrate").oninput = function() {
  const v = +this.value;
  state.filters.min_bitrate = v;
  $("sl-bitrate-val").textContent = v > 0 ? v + " kbps" : "–";
  loadTracks(1);
};

function onBpmChange() {
  const minV = +$("sl-bpm-min").value;
  const maxV = +$("sl-bpm-max").value;
  state.filters.bpm_min = minV;
  state.filters.bpm_max = maxV;
  $("sl-bpm-min-val").textContent = minV > 0 ? minV + " BPM" : "–";
  $("sl-bpm-max-val").textContent = maxV > 0 ? maxV + " BPM" : "–";
  loadTracks(1);
}

const YEAR_MIN = 1950, YEAR_MAX = 2025;
$("sl-year-min").oninput = function() {
  const v = +this.value;
  state.filters.year_min = v <= YEAR_MIN ? 0 : v;
  $("sl-year-min-val").textContent = v <= YEAR_MIN ? "–" : v;
  if (+$("sl-year-max").value < v) { $("sl-year-max").value = v; $("sl-year-max").oninput(); }
  loadTracks(1);
};
$("sl-year-max").oninput = function() {
  const v = +this.value;
  state.filters.year_max = v >= YEAR_MAX ? 0 : v;
  $("sl-year-max-val").textContent = v >= YEAR_MAX ? "–" : v;
  if (+$("sl-year-min").value > v) { $("sl-year-min").value = v; $("sl-year-min").oninput(); }
  loadTracks(1);
};

// ── Search & Sort ──────────────────────────────────────────
let searchTimer;
let suppressLibrarySearchUntil = 0;
$("search").oninput = e => {
  if (Date.now() < suppressLibrarySearchUntil) {
    e.target.value = "";
    return;
  }
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => {
    state.query = e.target.value.trim();
    clearPlaylist();
    loadTracks(1);
  }, 500);
};
$("sort-select").onchange = e => { state.sort = e.target.value; clearPlaylist(); loadTracks(1); };

// ── Stats ──────────────────────────────────────────────────
async function loadStats() {
  try {
    const res  = await fetch(`${API}/api/stats`);
    const data = await res.json();
    const lastScan = data.last_scan
      ? new Date(data.last_scan * 1000).toLocaleDateString("de-DE")
      : "noch nie";
    $("topbar-meta").textContent =
      `${data.total_tracks.toLocaleString()} Tracks · ${data.total_size_gb} GB · Zuletzt gescannt: ${lastScan}`;
  } catch {}
}

// ── Genres ─────────────────────────────────────────────────
async function loadGenres() {
  try {
    const res    = await fetch(`${API}/api/genres`);
    const genres = await res.json();
    const inner  = $("chips-genre-inner");
    inner.innerHTML = "";
    genres.forEach(g => {
      const btn = document.createElement("button");
      btn.className = "chip";
      btn.dataset.val = g;
      btn.textContent = g;
      inner.appendChild(btn);
    });
  } catch {}
}

// ── Scanner ─────────────────────────────────────────────────
$("btn-scan").onclick = async () => {
  await fetch(`${API}/api/scan/start`, { method: "POST" });
  showBanner("Bibliothek wird gescannt…");
  startScanPolling();
};

$("btn-bpm-tag").onclick = async () => {
  const btn = $("btn-bpm-tag");
  btn.classList.add("running");
  btn.innerHTML = '<i class="ti ti-loader"></i> Lese Tags…';
  try {
    const r = await fetch(`${API}/api/scan/bpm-tags`, { method: "POST" });
    const d = await r.json();
    showBanner(`BPM-Tags gelesen: ${d.updated} aktualisiert`);
    setTimeout(hideBanner, 4000);
  } catch(e) { showBanner("Fehler beim Tag-Lesen"); setTimeout(hideBanner, 3000); }
  btn.classList.remove("running");
  btn.innerHTML = '<i class="ti ti-music-bolt"></i> BPM-Tags einlesen';
};

$("btn-bpm-calc").onclick = async () => {
  const btn = $("btn-bpm-calc");
  btn.classList.add("running");
  btn.innerHTML = '<i class="ti ti-loader"></i> Starte…';
  try {
    const r = await fetch(`${API}/api/scan/bpm`, { method: "POST" });
    const d = await r.json();
    showBanner("BPM-Berechnung läuft im Hintergrund…");
    setTimeout(hideBanner, 5000);
  } catch(e) { showBanner("Fehler"); setTimeout(hideBanner, 3000); }
  btn.classList.remove("running");
  btn.innerHTML = '<i class="ti ti-waveform"></i> BPM berechnen';
};

function showBanner(text) {
  $("scan-banner").style.display = "flex";
  $("scan-banner-text").textContent = text;
}
function hideBanner() {
  $("scan-banner").style.display = "none";
}

let scanPoller = null;
let _missedFinish = 0;

async function checkScanOnce() {
  try {
    const res  = await fetch(`${API}/api/scan/status`);
    const data = await res.json();
    if (data.running) {
      _missedFinish = 0;
      const done  = data.progress.toLocaleString();
      const total = data.total > 0 ? ` / ${data.total.toLocaleString()}` : "";
      showBanner(`⟳ ${t().scanning} ${done}${total}`);
      loadStats();
      return true;
    } else {
      // Erst nach 2 aufeinanderfolgenden "not running" wirklich stoppen
      // (schützt gegen kurze Lücken beim Thread-Start)
      _missedFinish++;
      if (_missedFinish >= 2) {
        clearInterval(scanPoller);
        scanPoller = null;
        hideBanner();
        loadStats();
        loadGenres();
        loadTracks(1);
      }
      return false;
    }
  } catch (e) {
    // Netzwerkfehler → einfach weiterpollen
    return true;
  }
}

function startScanPolling() {
  if (scanPoller) clearInterval(scanPoller);
  _missedFinish = 0;
  checkScanOnce();
  scanPoller = setInterval(checkScanOnce, 3000);
}

// Stats alle 60 Sek. im Hintergrund aktualisieren
setInterval(loadStats, 60000);

// ── Disco-Badge ─────────────────────────────────────────────
async function checkDiscoBadge() {
  try {
    const r = await fetch(`${API}/api/disco-status`);
    const d = await r.json();
    $("disco-badge").style.display = d.active ? "inline" : "none";
  } catch(e) {
    $("disco-badge").style.display = "none";
  }
}
checkDiscoBadge();

// ── Playlists ─────────────────────────────────────────────────────────────────
const SYSTEM_SORT_ICONS = {
  recent:       "ti-history",
  top_played:   "ti-chart-bar",
  newest_added: "ti-sparkles",
  disco_top:    "ti-disc",
};

let _playlists = [];
let _activePl  = null;
let _trackMemberships = {}; // { track_id: [playlist_id, ...] }
let _favoriteIds = new Set();

// ── Bookmark helpers ──────────────────────────────────────
async function fetchMemberships(tracks) {
  if (!_me || !tracks.length) return;
  const ids = tracks.map(tr => tr.id).join(",");
  try {
    const [membershipResponse, favoriteResponse] = await Promise.all([
      fetch(`/api/playlists/memberships?ids=${ids}`),
      fetch(`/api/favorites?ids=${ids}`),
    ]);
    _trackMemberships = await membershipResponse.json();
    const favorites = await favoriteResponse.json();
    tracks.forEach(track => _favoriteIds.delete(Number(track.id)));
    (favorites.track_ids || []).forEach(id => _favoriteIds.add(Number(id)));
    // Update all bookmark buttons already in the DOM
    document.querySelectorAll(".btn-bookmark, #play-view-bookmark").forEach(btn => {
      _applyBookmarkState(btn, Number(btn.dataset.trackId));
    });
    document.querySelectorAll(".btn-favorite").forEach(btn => {
      if (btn.dataset.trackId) {
        applyFavoriteState(btn, _favoriteIds.has(Number(btn.dataset.trackId)));
      }
    });
  } catch {}
}

function applyFavoriteState(btn, favorite) {
  if (!btn) return;
  btn.classList.toggle("favorite", favorite);
  btn.title = favorite ? "Aus Favoriten entfernen" : "Zu Favoriten hinzufügen";
  btn.innerHTML = favorite
    ? `<i class="ti ti-star-filled"></i>`
    : `<i class="ti ti-star"></i>`;
}

async function toggleFavorite(track, btn) {
  if (!_me || !track || isJingle(track)) return;
  const trackId = Number(track.id);
  const favorite = !_favoriteIds.has(trackId);
  const response = await fetch(`/api/favorites/${trackId}`, {
    method: "PUT", headers: {"Content-Type":"application/json"},
    body: JSON.stringify({favorite}),
  });
  if (!response.ok) return;
  const result = await response.json();
  if (favorite) _favoriteIds.add(trackId); else _favoriteIds.delete(trackId);
  document.querySelectorAll(`.btn-favorite[data-track-id="${trackId}"]`).forEach(
    item => applyFavoriteState(item, favorite)
  );
  applyFavoriteState(btn, favorite);
  if (favorite && result.lastfm_synced) {
    const key = `${track.artist}||${track.title}`;
    lfm.lovedCache.set(key, true);
    document.querySelectorAll(`.btn-love[data-key="${CSS.escape(key)}"]`).forEach(
      item => applyLovedState(item, true)
    );
    if (state.currentTrack?.id === track.id) applyLovedState($("player-love"), true);
  }
  await loadPlaylists();
  broadcastFavorite(favorite);
}

function _applyBookmarkState(btn, trackId) {
  const plIds = _trackMemberships[trackId] || [];
  const bookmarked = plIds.length > 0;
  btn.classList.toggle("bookmarked", bookmarked);
  btn.innerHTML = bookmarked
    ? `<i class="ti ti-bookmark-filled"></i>`
    : `<i class="ti ti-bookmark"></i>`;
  // Tooltip: list playlist names
  if (bookmarked) {
    const names = plIds.map(id => {
      const pl = _playlists.find(p => p.id === id);
      return pl ? pl.name : "?";
    }).join(", ");
    btn.title = names;
  } else {
    btn.title = t().bm_add;
  }
}

let _bmDropdownOpen = null;
function _closeBookmarkDropdown() {
  if (_bmDropdownOpen) { _bmDropdownOpen.remove(); _bmDropdownOpen = null; }
}

function _openBookmarkDropdown(btn, trackId) {
  if (_bmDropdownOpen) { _closeBookmarkDropdown(); return; }
  const userPlaylists = _playlists.filter(p => !p.is_system && p.type === "static");

  const dd = document.createElement("div");
  dd.className = "bm-dropdown";
  _bmDropdownOpen = dd;

  // "Neue Playlist erstellen"
  const newItem = document.createElement("div");
  newItem.className = "bm-dropdown-item";
  newItem.innerHTML = `<i class="ti ti-plus"></i><span>${t().bm_new_playlist}</span>`;
  newItem.addEventListener("click", async e => {
    e.stopPropagation();
    _closeBookmarkDropdown();
    const name = prompt(t().bm_new_prompt);
    if (!name?.trim()) return;
    const r = await fetch("/api/playlists", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({ name: name.trim(), type: "static" })
    });
    if (!r.ok) return;
    const pl = await r.json();
    await fetch(`/api/playlists/${pl.id}/tracks`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({ track_id: trackId })
    });
    _trackMemberships[trackId] = [...(_trackMemberships[trackId] || []), pl.id];
    await loadPlaylists();
    document.querySelectorAll(`.btn-bookmark[data-track-id="${trackId}"], #play-view-bookmark[data-track-id="${trackId}"]`).forEach(b => _applyBookmarkState(b, trackId));
  });
  dd.appendChild(newItem);

  if (userPlaylists.length) {
    const sep = document.createElement("div");
    sep.className = "bm-dropdown-sep";
    dd.appendChild(sep);

    userPlaylists.forEach(pl => {
      const alreadyIn = (_trackMemberships[trackId] || []).includes(pl.id);
      const item = document.createElement("div");
      item.className = "bm-dropdown-item";
      item.innerHTML = `<i class="ti ${alreadyIn ? "ti-check" : "ti-playlist"}"></i><span>${esc(pl.name)}</span>`;
      if (!alreadyIn) {
        item.addEventListener("click", async e => {
          e.stopPropagation();
          _closeBookmarkDropdown();
          await fetch(`/api/playlists/${pl.id}/tracks`, {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({ track_id: trackId })
          });
          _trackMemberships[trackId] = [...(_trackMemberships[trackId] || []), pl.id];
          document.querySelectorAll(`.btn-bookmark[data-track-id="${trackId}"], #play-view-bookmark[data-track-id="${trackId}"]`).forEach(b => _applyBookmarkState(b, trackId));
        });
      }
      dd.appendChild(item);
    });
  }

  btn.appendChild(dd);
  // Close on outside click
  setTimeout(() => document.addEventListener("click", _closeBookmarkDropdown, { once: true }), 0);
}

async function loadPlaylists() {
  try {
    const r = await fetch("/api/playlists");
    _playlists = await r.json();
  } catch { return; }
  renderPlaylistSidebar();
  updatePlaylistExportButton();
}

function renderPlaylistSidebar() {
  const sysList  = $("playlist-system");
  const userList = $("playlist-user");
  sysList.innerHTML = "";
  userList.innerHTML = "";

  _playlists.forEach(pl => {
    const icon = pl.system_key === "favorites"
      ? "ti-star-filled"
      : pl.is_system
      ? (SYSTEM_SORT_ICONS[pl.sort] || "ti-list")
      : "ti-playlist";
    const item = document.createElement("div");
    item.className = "pl-item" + (_activePl === pl.id ? " active" : "");
    item.dataset.id = pl.id;
    const personal = !pl.is_system;
    item.innerHTML = `
      <i class="ti ${icon}"></i>
      <span class="pl-item-copy">
        <span class="pl-item-name">${esc(pl.name)}</span>
        ${personal ? `<span class="pl-item-type">${pl.type === "smart" ? "Smart · Filter" : `Statisch · ${pl.track_count || 0} Tracks`}</span>` : ""}
      </span>
      ${personal && _me?.allow_playlists ? `
        <button class="pl-action pl-edit" title="Im Editor bearbeiten" data-id="${pl.id}"><i class="ti ti-pencil"></i></button>
        <button class="pl-action pl-del" title="Löschen" data-id="${pl.id}"><i class="ti ti-trash"></i></button>` : ""}
    `;
    item.addEventListener("click", e => {
      if (e.target.closest(".pl-action")) return;
      if (_activePl === pl.id) { clearPlaylist(); loadTracks(1, true); return; }
      applyPlaylist(pl);
    });
    item.querySelector(".pl-edit")?.addEventListener("click", e => {
      e.stopPropagation();
      openPlaylistEditor(pl);
    });
    const delBtn = item.querySelector(".pl-del");
    if (delBtn) {
      delBtn.addEventListener("click", async e => {
        e.stopPropagation();
        if (!confirm(t().pl_delete_confirm(pl.name))) return;
        await fetch(`/api/playlists/${pl.id}`, {method: "DELETE"});
        if (_activePl === pl.id) clearPlaylist();
        await loadPlaylists();
      });
    }
    (pl.is_system ? sysList : userList).appendChild(item);
  });
}

async function applyPlaylist(pl) {
  if (listShuffle.active) stopListShuffle(false);
  suppressLibrarySearchUntil = Date.now() + 1500;
  clearTimeout(searchTimer);
  state.query = "";
  $("search").value = "";
  ++_loadTracksRequest; // a preceding library request must not overwrite this playlist
  _setSearching(false);
  if (radio.active) {
    radio.browsingLibrary = true;
    updateRadioButton();
  }
  _activePl = pl.id;
  renderPlaylistSidebar();
  updatePlaylistExportButton();

  // Personal playlists are resolved server-side: static in saved order,
  // smart by running the saved editor filter again.
  if (pl.type === "static" || !pl.is_system) {
    _setSearching(true);
    try {
      const r = await fetch(`/api/playlists/${pl.id}/tracks`);
      const tracks = await r.json();
      if (_activePl !== pl.id) return;
      state.total = tracks.length;
      state.pages = 1;
      state.page  = 1;
      renderTracks(tracks);
      renderPagination();
      fetchMemberships(tracks);
      $("result-count").textContent = `${pl.name} · ${tracks.length} Track${tracks.length === 1 ? "" : "s"}`;
    } catch {}
    _setSearching(false);
    return;
  }

  // System playlists: only set sort, clear all filters
  if (pl.is_system) {
    resetFilters();
    state.sort = pl.sort;
    $("sort-select").value = pl.sort;
  } else {
    // Smart user playlist: restore saved filter state
    let filters = {};
    try { filters = JSON.parse(pl.filters || "{}"); } catch {}
    resetFilters();
    state.sort = pl.sort || "artist";
    $("sort-select").value = state.sort;
    Object.assign(state.filters, filters);
    _restoreFilterUI(filters);
  }

  loadTracks(1, true);
}

function clearPlaylist() {
  _activePl = null;
  renderPlaylistSidebar();
  updatePlaylistExportButton();
}

function resetFilters() {
  state.query = "";
  $("search").value = "";
  state.filters = {
    genre: "", decade: "", format: "",
    min_dur: 0, max_dur: 0, min_bitrate: 0,
    year_min: 0, year_max: 0,
    bpm_min: 0, bpm_max: 0,
    artist_query: "", title_query: "", album_query: "",
    loved: false,
  };
  state.albumView.drilled = null;
}

function resetFilterUI() {
  document.querySelectorAll(".chip-group").forEach(group => {
    group.querySelectorAll(".chip").forEach(chip => {
      chip.classList.toggle("active", chip.dataset.val === "");
    });
  });
  for (const prefix of ["artist", "title", "album"]) {
    $(`${prefix}-search`).value = "";
    $(`${prefix}-search-panel`).style.display = "none";
    $(`chip-${prefix}-alle`).classList.add("active");
  }
  const values = {
    "sl-min-dur": 0, "sl-max-dur": 3600, "sl-bitrate": 0,
    "sl-year-min": YEAR_MIN, "sl-year-max": YEAR_MAX,
    "sl-bpm-min": 0, "sl-bpm-max": 0,
  };
  Object.entries(values).forEach(([id, value]) => { $(id).value = value; });
  $("sl-min-dur-val").textContent = "0:00";
  for (const id of ["sl-max-dur-val", "sl-bitrate-val", "sl-year-min-val",
                    "sl-year-max-val", "sl-bpm-min-val", "sl-bpm-max-val"]) {
    $(id).textContent = "–";
  }
}

function _restoreFilterUI(filters) {
  if (filters.artist_query) {
    $("artist-search-panel").style.display = "block";
    $("chip-artist-alle").classList.remove("active");
    $("artist-search").value = filters.artist_query;
  }
  if (filters.title_query) {
    $("title-search-panel").style.display = "block";
    $("chip-title-alle").classList.remove("active");
    $("title-search").value = filters.title_query;
  }
  if (filters.album_query) {
    $("album-search-panel").style.display = "block";
    $("chip-album-alle").classList.remove("active");
    $("album-search").value = filters.album_query;
  }
  // Sliders, chips etc. — reset to defaults visually (filters applied via state)
}

function updateSavePlaylistBtn() { /* removed */ }

// ── Playlist editor ──────────────────────────────────────────────────────────
const PLE_FIELDS = {
  title: "Titel", artist: "Interpret", album: "Album", genre: "Genre",
  year: "Jahr", decade: "Jahrzehnt", playcount: "Playcount",
};
const PLE_TEXT_OPS = {contains: "enthält", not_contains: "enthält nicht"};
const PLE_NUM_OPS = {eq: "ist", ne: "ist nicht", gt: "ist größer", lt: "ist kleiner"};
let pleTracks = [];
let pleResults = [];
let pleEditing = null;
let pleDragIndex = null;
let pleSearchTimer = null;
let pleDirty = false;
let pleInputsBound = false;

function pleOps(field) {
  return ["title", "artist", "album", "genre"].includes(field) ? PLE_TEXT_OPS : PLE_NUM_OPS;
}

function pleSetStatus(message, error = false) {
  const node = $("ple-status");
  node.textContent = message || "";
  node.style.color = error ? "#d58282" : "var(--accent)";
}

function pleAddRule(group, rule = {}) {
  const wrap = $(group === "any" ? "ple-rules-any" : "ple-rules-all");
  const row = document.createElement("div");
  row.className = "ple-rule-row";
  const field = PLE_FIELDS[rule.field] ? rule.field : "title";
  const ops = pleOps(field);
  const op = ops[rule.op] ? rule.op : Object.keys(ops)[0];
  row.innerHTML = `
    <select class="ple-select ple-rule-field">${Object.entries(PLE_FIELDS).map(([value,label]) =>
      `<option value="${value}" ${value === field ? "selected" : ""}>${label}</option>`).join("")}</select>
    <select class="ple-select ple-rule-op">${Object.entries(ops).map(([value,label]) =>
      `<option value="${value}" ${value === op ? "selected" : ""}>${label}</option>`).join("")}</select>
    <input class="ple-input ple-rule-value" placeholder="Wert">
    <button class="ple-danger" type="button" title="Regel entfernen">×</button>`;
  row.querySelector(".ple-rule-value").value = rule.value ?? "";
  row.querySelector(".ple-rule-field").onchange = event => {
    const opSelect = row.querySelector(".ple-rule-op");
    opSelect.innerHTML = Object.entries(pleOps(event.target.value))
      .map(([value,label]) => `<option value="${value}">${label}</option>`).join("");
    pleDirty = true;
  };
  row.querySelector(".ple-rule-op").onchange = () => { pleDirty = true; };
  row.querySelector(".ple-rule-value").oninput = () => { pleDirty = true; };
  row.querySelector("button").onclick = () => { row.remove(); pleDirty = true; };
  wrap.appendChild(row);
  pleDirty = true;
}

function pleReadRules(group) {
  return [...$(group === "any" ? "ple-rules-any" : "ple-rules-all")
    .querySelectorAll(".ple-rule-row")].map(row => ({
      field: row.querySelector(".ple-rule-field").value,
      op: row.querySelector(".ple-rule-op").value,
      value: row.querySelector(".ple-rule-value").value.trim(),
    })).filter(rule => rule.value);
}

function pleCurrentFilter() {
  const allRules = pleReadRules("all");
  const anyRules = pleReadRules("any");
  if (anyRules.length) allRules.push({mode: "any", rules: anyRules});
  return {
    editor_version: 1,
    search: {
      title: $("ple-search-title").value.trim(),
      artist: $("ple-search-artist").value.trim(),
      album: $("ple-search-album").value.trim(),
    },
    rules: {mode: "all", rules: allRules},
  };
}

function pleRestoreFilter(saved) {
  const search = saved?.search || {};
  $("ple-search-title").value = search.title || "";
  $("ple-search-artist").value = search.artist || "";
  $("ple-search-album").value = search.album || "";
  $("ple-rules-all").innerHTML = "";
  $("ple-rules-any").innerHTML = "";
  const root = saved?.rules || {mode: "all", rules: []};
  (root.rules || []).forEach(rule => {
    if (rule?.rules) {
      (rule.rules || []).forEach(child => pleAddRule(rule.mode === "any" ? "any" : "all", child));
    } else {
      pleAddRule(root.mode === "any" ? "any" : "all", rule);
    }
  });
  if (!$("ple-rules-all").children.length && !$("ple-rules-any").children.length) {
    pleAddRule("all", {field:"artist", op:"contains", value:""});
  }
}

function pleBindInputs() {
  if (pleInputsBound) return;
  pleInputsBound = true;
  ["ple-search-title", "ple-search-artist", "ple-search-album"].forEach(id => {
    $(id).addEventListener("input", () => {
      pleDirty = true;
      clearTimeout(pleSearchTimer);
      pleSearchTimer = setTimeout(pleRunPreview, 320);
    });
  });
  document.querySelectorAll('input[name="ple-save-type"]').forEach(input => {
    input.addEventListener("change", () => {
      $("ple-smart-note").style.display =
        document.querySelector('input[name="ple-save-type"]:checked')?.value === "smart" ? "block" : "none";
    });
  });
  $("ple-import-file").addEventListener("change", pleImportFile);
}

async function openPlaylistEditor(playlist = null) {
  if (!_me?.allow_playlists) return;
  pleBindInputs();
  pleEditing = playlist && !playlist.is_system ? playlist : null;
  pleTracks = [];
  pleResults = [];
  pleDirty = false;
  pleSetStatus("");
  $("ple-import-status").textContent = "";
  $("ple-results").innerHTML = '<div class="ple-empty">Track-Suche oder Regeln verwenden.</div>';
  $("ple-edit-label").textContent = pleEditing ? `Bearbeiten: ${pleEditing.name}` : "Neue Playlist";
  let saved = {};
  if (pleEditing) {
    try { saved = JSON.parse(pleEditing.filters || "{}"); } catch {}
  }
  pleRestoreFilter(saved.editor_version === 1 ? saved : {});
  if (pleEditing) {
    pleSetStatus("Playlist wird geladen…");
    const response = await fetch(`/api/playlists/${pleEditing.id}/tracks`);
    pleTracks = response.ok ? await response.json() : [];
    pleSetStatus("");
  }
  pleRenderTracks();
  pleDirty = false;
  $("playlist-editor-modal").style.display = "flex";
}

function closePlaylistEditor(force = false) {
  if (!force && pleDirty && !confirm("Änderungen verwerfen und den Editor schließen?")) return;
  $("ple-save-dialog").style.display = "none";
  $("playlist-editor-modal").style.display = "none";
}

async function pleRunPreview() {
  pleSetStatus("Filter wird angewendet…");
  try {
    const response = await fetch("/api/playlist-editor/preview", {
      method:"POST", headers:{"Content-Type":"application/json"},
      body:JSON.stringify({filter:pleCurrentFilter(), sort:pleEditing?.sort || "artist"}),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Vorschau fehlgeschlagen");
    pleResults = data.results || [];
    pleRenderResults();
    pleSetStatus(`${pleResults.length} passende Tracks gefunden`);
  } catch (error) {
    pleResults = [];
    pleRenderResults();
    pleSetStatus(error.message, true);
  }
}

function pleRenderResults() {
  const wrap = $("ple-results");
  wrap.innerHTML = "";
  if (!pleResults.length) {
    wrap.innerHTML = '<div class="ple-empty">Keine Ergebnisse.</div>';
  } else {
    pleResults.forEach(track => {
      const row = document.createElement("div");
      row.className = "ple-result";
      row.innerHTML = `<span class="ple-artist">${esc(track.artist || "")}</span>
        <span class="ple-title">${esc(track.title || track.path || "—")}</span>
        <span class="ple-year">${track.year || ""}</span><span style="color:var(--accent)">＋</span>`;
      row.onclick = () => pleAddTrack(track);
      wrap.appendChild(row);
    });
  }
  const button = $("ple-add-all");
  button.disabled = !pleResults.length;
  button.textContent = pleResults.length
    ? `+ Alle ${pleResults.length} gefilterten hinzufügen`
    : "+ Alle gefilterten hinzufügen";
}

function pleAddTrack(track, render = true) {
  if (pleTracks.some(item => Number(item.id) === Number(track.id))) return false;
  pleTracks.push(track);
  pleDirty = true;
  if (render) pleRenderTracks();
  return true;
}

function pleAddAll() {
  let added = 0;
  pleResults.forEach(track => { if (pleAddTrack(track, false)) added++; });
  pleRenderTracks();
  pleSetStatus(`${added} Tracks hinzugefügt`);
}

function pleRemoveTrack(index) {
  pleTracks.splice(index, 1);
  pleDirty = true;
  pleRenderTracks();
}

function pleClear() {
  if (pleTracks.length && !confirm("Alle Tracks aus der Zusammenstellung entfernen?")) return;
  pleTracks = [];
  pleDirty = true;
  pleRenderTracks();
}

function pleShuffle() {
  for (let index = pleTracks.length - 1; index > 0; index--) {
    const other = Math.floor(Math.random() * (index + 1));
    [pleTracks[index], pleTracks[other]] = [pleTracks[other], pleTracks[index]];
  }
  pleDirty = true;
  pleRenderTracks();
}

function pleRenderTracks() {
  const wrap = $("ple-tracks");
  wrap.innerHTML = "";
  $("ple-track-count").textContent = `Playlist (${pleTracks.length} Track${pleTracks.length === 1 ? "" : "s"})`;
  if (!pleTracks.length) {
    wrap.innerHTML = '<div class="ple-empty">Noch keine Tracks. Links suchen oder unten zufällig auffüllen.</div>';
    return;
  }
  pleTracks.forEach((track, index) => {
    const row = document.createElement("div");
    row.className = "ple-track";
    row.innerHTML = `<span class="ple-handle" draggable="true">⠿</span>
      <span class="ple-pos">${index + 1}</span>
      <span class="ple-artist">${esc(track.artist || "")}</span>
      <span class="ple-title">${esc(track.title || track.path || "—")}</span>
      <span class="ple-year">${track.year || ""}</span>
      <button type="button" title="Entfernen">×</button>`;
    row.querySelector("button").onclick = () => pleRemoveTrack(index);
    const handle = row.querySelector(".ple-handle");
    handle.addEventListener("dragstart", event => {
      pleDragIndex = index;
      event.dataTransfer.effectAllowed = "move";
    });
    handle.addEventListener("dragend", () => { pleDragIndex = null; });
    row.addEventListener("dragover", event => { event.preventDefault(); row.classList.add("drag-over"); });
    row.addEventListener("dragleave", () => row.classList.remove("drag-over"));
    row.addEventListener("drop", event => {
      event.preventDefault();
      row.classList.remove("drag-over");
      if (pleDragIndex === null || pleDragIndex === index) return;
      const moved = pleTracks.splice(pleDragIndex, 1)[0];
      pleTracks.splice(index, 0, moved);
      pleDirty = true;
      pleRenderTracks();
    });
    wrap.appendChild(row);
  });
}

async function pleFill() {
  const button = $("ple-fill-button");
  button.disabled = true;
  pleSetStatus("Zufallstracks werden geladen…");
  try {
    const response = await fetch("/api/playlist-editor/fill", {
      method:"POST", headers:{"Content-Type":"application/json"},
      body:JSON.stringify({
        count:Number($("ple-fill-count").value || 50),
        filter:pleCurrentFilter(),
        exclude_ids:pleTracks.map(track => track.id),
      }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Auffüllen fehlgeschlagen");
    let added = 0;
    (data.results || []).forEach(track => { if (pleAddTrack(track, false)) added++; });
    pleRenderTracks();
    pleSetStatus(`${added} Tracks hinzugefügt`);
  } catch (error) {
    pleSetStatus(error.message, true);
  } finally {
    button.disabled = false;
  }
}

let pleImportMode = "replace";
function pleChooseImport(mode) {
  pleImportMode = mode;
  $("ple-import-file").value = "";
  $("ple-import-file").click();
}

async function pleImportFile(event) {
  const file = event.target.files?.[0];
  if (!file) return;
  if (file.size > 5 * 1024 * 1024) {
    $("ple-import-status").textContent = "Die Datei ist größer als 5 MB.";
    return;
  }
  try {
    const payload = JSON.parse(await file.text());
    const response = await fetch("/api/playlist-editor/import", {
      method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(payload),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Import fehlgeschlagen");
    if (pleImportMode === "replace") pleTracks = [];
    (data.tracks || []).forEach(track => pleAddTrack(track, false));
    pleDirty = true;
    pleRenderTracks();
    $("ple-import-status").textContent =
      `${data.matched_count} von ${data.imported_count} Tracks gefunden` +
      (data.unmatched_count ? ` · ${data.unmatched_count} nicht gefunden` : " · vollständig");
  } catch (error) {
    $("ple-import-status").textContent = error.message;
  }
}

async function pleDownload(trackIds, name) {
  const response = await fetch("/api/playlist-editor/export", {
    method:"POST", headers:{"Content-Type":"application/json"},
    body:JSON.stringify({track_ids:trackIds, name}),
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.error || "Export fehlgeschlagen");
  }
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement("a");
  link.href = url;
  link.download = "";
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

async function pleExportEditor() {
  try {
    await pleDownload(pleTracks.map(track => track.id), pleEditing?.name || "Adolar-Playlist");
    pleSetStatus(`${pleTracks.length} Tracks exportiert`);
  } catch (error) {
    pleSetStatus(error.message, true);
  }
}

function updatePlaylistExportButton() {
  const playlist = _playlists.find(item => item.id === _activePl);
  $("btn-playlist-export").style.display = playlist && !playlist.is_system ? "flex" : "none";
}

async function exportActivePlaylist() {
  const playlist = _playlists.find(item => item.id === _activePl);
  if (!playlist || playlist.is_system) return;
  try {
    const response = await fetch(`/api/playlists/${playlist.id}/tracks`);
    const tracks = await response.json();
    if (!response.ok) throw new Error(tracks.error || "Playlist konnte nicht geladen werden");
    await pleDownload(tracks.map(track => track.id), playlist.name);
  } catch (error) {
    alert(error.message);
  }
}

async function pleOpenSaveDialog() {
  let name = pleEditing?.name || "";
  if (!name) {
    const response = await fetch("/api/playlist-editor/defaults");
    if (response.ok) name = (await response.json()).name;
  }
  $("ple-save-name").value = name || "Neue Playlist";
  const type = pleEditing?.type || "static";
  const selected = document.querySelector(`input[name="ple-save-type"][value="${type}"]`);
  if (selected) selected.checked = true;
  $("ple-smart-note").style.display = type === "smart" ? "block" : "none";
  $("ple-save-dialog").style.display = "flex";
  $("ple-save-name").focus();
  $("ple-save-name").select();
}

async function pleSave() {
  const name = $("ple-save-name").value.trim();
  const type = document.querySelector('input[name="ple-save-type"]:checked')?.value || "static";
  if (!name) {
    $("ple-save-name").focus();
    return;
  }
  const button = $("ple-save-confirm");
  button.disabled = true;
  const payload = {
    name, type, filters:pleCurrentFilter(),
    sort:pleEditing?.sort || "artist",
    track_ids:pleTracks.map(track => track.id),
  };
  try {
    const response = await fetch(
      pleEditing ? `/api/playlists/${pleEditing.id}` : "/api/playlists",
      {method:pleEditing ? "PUT" : "POST", headers:{"Content-Type":"application/json"},
       body:JSON.stringify(payload)},
    );
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Speichern fehlgeschlagen");
    pleDirty = false;
    $("ple-save-dialog").style.display = "none";
    closePlaylistEditor(true);
    await loadPlaylists();
    const saved = _playlists.find(item => item.id === data.id);
    if (saved) await applyPlaylist(saved);
  } catch (error) {
    pleSetStatus(error.message, true);
    $("ple-save-dialog").style.display = "none";
  } finally {
    button.disabled = false;
  }
}

// ── Current user / auth ───────────────────────────────────────────────────────
let _me = null;
let _adolar4u = { collecting: false, global: {}, user: {} };

async function loadAdolar4UStatus() {
  if (!_me) return;
  try {
    const r = await fetch("/api/adolar4u/status", {cache: "no-store"});
    if (r.ok) _adolar4u = await r.json();
  } catch {}
}

async function loadMe() {
  try {
    const r = await fetch("/api/me-optional");
    _me = await r.json();
  } catch { return; }

  if (!_me) {
    $("user-menu-name").textContent = "Anmelden";
    $("btn-user-menu").onclick = () => { location.href = "/login?next=/"; };
    $("user-dropdown").style.display = "none";
    $("lastfm-status").style.display = "none";
    return;
  }

  $("user-menu-name").textContent = _me.username;
  $("btn-playlist-editor").style.display = _me.allow_playlists ? "flex" : "none";

  if (_me.role === "admin") {
    $("btn-user-mgmt").style.display = "flex";
    $("btn-monitor").style.display = "flex";
    $("btn-library").style.display = "flex";
  }

  await loadAdolar4UStatus();
  $("btn-adolar4u").style.display = _adolar4u.global?.enabled ? "flex" : "none";

  // Show basket only if download is permitted
  if (_me.allow_download) {
    $("basket-outer").style.display = "block";
  }

  // Hide scan/BPM buttons for non-admins
  if (_me.role !== "admin") {
    const scanWrap = document.querySelector(".sidebar-scan");
    if (scanWrap) scanWrap.style.display = "none";
  }
}
const meReady = loadMe().then(() => {
  loadPlaylists();
  loadRadioStations();
});

// ── User dropdown toggle ──────────────────────────────────────────────────────
$("btn-user-menu").onclick = (e) => {
  e.stopPropagation();
  $("user-dropdown").classList.toggle("open");
};
document.addEventListener("click", (e) => {
  if (!document.getElementById("user-menu-wrap").contains(e.target))
    $("user-dropdown").classList.remove("open");
});

function openChangePassword() {
  $("user-dropdown").classList.remove("open");
  location.href = "/change-password";
}

// ── User management modal ─────────────────────────────────────────────────────
async function openUserMgmt() {
  $("user-dropdown").classList.remove("open");
  $("usermgmt-modal").style.display = "flex";
  await refreshUserList();
  await refreshAccessSettings();
  await refreshAdolar4UAdminSettings();
  await refreshBlockedIps();
  await refreshAuditLog();
}
function closeUserMgmt() {
  $("usermgmt-modal").style.display = "none";
}

async function refreshUserList() {
  const r = await fetch("/api/users");
  const users = await r.json();
  const list = $("usermgmt-list");
  list.innerHTML = "";
  users.forEach(u => {
    const row = document.createElement("div");
    row.style.cssText = "display:flex;align-items:center;gap:8px;padding:8px 0;border-bottom:0.5px solid var(--border-subtle)";
    const isMe = _me && u.id === _me.id;
    row.innerHTML = `
      <i class="ti ti-user" style="color:var(--text-tertiary);flex-shrink:0"></i>
      <span style="flex:1;font-size:13px;color:var(--text-primary)">${esc(u.username)}</span>
      <span style="font-size:11px;padding:2px 7px;border-radius:99px;background:${u.role==='admin'?'rgba(127,119,221,.2)':'var(--bg-secondary)'};color:${u.role==='admin'?'var(--accent)':'var(--text-tertiary)'}">${u.role}</span>
      <label title="Download erlaubt" style="display:flex;align-items:center;gap:4px;font-size:11px;color:var(--text-tertiary);cursor:pointer">
        <input type="checkbox" data-uid="${u.id}" class="dl-toggle" ${u.allow_download?'checked':''} ${u.role==='admin'?'disabled':''}>
        <i class="ti ti-download" style="font-size:12px"></i>
      </label>
      <label title="Eigene Playlists" style="display:flex;align-items:center;gap:4px;font-size:11px;color:var(--text-tertiary);cursor:pointer">
        <input type="checkbox" data-uid="${u.id}" data-cap="playlists" class="cap-toggle" ${u.allow_playlists?'checked':''} ${u.role==='admin'?'disabled':''}>
        <i class="ti ti-playlist" style="font-size:12px"></i>
      </label>
      <label title="Eigene Radiosender" style="display:flex;align-items:center;gap:4px;font-size:11px;color:var(--text-tertiary);cursor:pointer">
        <input type="checkbox" data-uid="${u.id}" data-cap="radio_stations" class="cap-toggle" ${u.allow_radio_stations?'checked':''} ${u.role==='admin'?'disabled':''}>
        <i class="ti ti-radio" style="font-size:12px"></i>
      </label>
      <label title="Account aktiv" style="display:flex;align-items:center;gap:4px;font-size:11px;color:var(--text-tertiary);cursor:pointer">
        <input type="checkbox" data-uid="${u.id}" class="active-toggle" ${u.is_active?'checked':''} ${isMe?'disabled':''}>
        <i class="ti ti-user-check" style="font-size:12px"></i>
      </label>
      <label title="Plays dieses Nutzers erhöhen den Archiv-Playcount" style="display:flex;align-items:center;gap:4px;font-size:11px;color:var(--text-tertiary);cursor:pointer">
        <input type="checkbox" data-uid="${u.id}" class="pc-toggle" ${u.contributes_playcount?'checked':''}>
        <i class="ti ti-chart-bar" style="font-size:12px"></i>
      </label>
      <button data-uid="${u.id}" class="pw-reset-btn" title="Passwort zurücksetzen"
              style="background:none;border:0.5px solid var(--border-subtle);border-radius:6px;color:var(--text-tertiary);cursor:pointer;padding:3px 7px;font-size:11px" ${isMe?'style="display:none"':''}>
        <i class="ti ti-lock-open"></i>
      </button>
      ${isMe ? '' : `<button data-uid="${u.id}" class="del-user-btn" title="Löschen"
              style="background:none;border:0.5px solid var(--border-subtle);border-radius:6px;color:#e03e3e;cursor:pointer;padding:3px 7px;font-size:11px">
        <i class="ti ti-trash"></i>
      </button>`}
    `;
    list.appendChild(row);
  });

  // Download toggle
  list.querySelectorAll(".dl-toggle").forEach(cb => {
    cb.onchange = async () => {
      await fetch(`/api/users/${cb.dataset.uid}/download`, {
        method: "POST", headers: {"Content-Type":"application/json"},
        body: JSON.stringify({allow: cb.checked})
      });
      if (_me && cb.dataset.uid == _me.id) _me.allow_download = cb.checked;
    };
  });

  list.querySelectorAll(".pc-toggle").forEach(cb => {
    cb.onchange = async () => {
      const r = await fetch(`/api/users/${cb.dataset.uid}/playcount`, {
        method: "POST", headers: {"Content-Type":"application/json"},
        body: JSON.stringify({allow: cb.checked})
      });
      if (!r.ok) cb.checked = !cb.checked;
      if (_me && cb.dataset.uid == _me.id) _me.contributes_playcount = cb.checked;
    };
  });

  list.querySelectorAll(".cap-toggle").forEach(cb => {
    cb.onchange = async () => {
      const r = await fetch(`/api/users/${cb.dataset.uid}/capability/${cb.dataset.cap}`, {
        method: "POST", headers: {"Content-Type":"application/json"},
        body: JSON.stringify({allow: cb.checked})
      });
      if (!r.ok) cb.checked = !cb.checked;
    };
  });

  list.querySelectorAll(".active-toggle").forEach(cb => {
    cb.onchange = async () => {
      const r = await fetch(`/api/users/${cb.dataset.uid}/active`, {
        method: "POST", headers: {"Content-Type":"application/json"},
        body: JSON.stringify({active: cb.checked})
      });
      if (!r.ok) cb.checked = !cb.checked;
    };
  });

  // Password reset
  list.querySelectorAll(".pw-reset-btn").forEach(btn => {
    btn.onclick = async () => {
      const pw = prompt("Neues Initialpasswort (mind. 8 Zeichen):");
      if (!pw) return;
      const r = await fetch(`/api/users/${btn.dataset.uid}/password`, {
        method: "POST", headers: {"Content-Type":"application/json"},
        body: JSON.stringify({password: pw})
      });
      const d = await r.json();
      if (d.error) alert(d.error);
      else alert("Passwort gesetzt. Benutzer muss es bei nächster Anmeldung ändern.");
    };
  });

  // Delete user
  list.querySelectorAll(".del-user-btn").forEach(btn => {
    btn.onclick = async () => {
      if (!confirm(t().user_delete_confirm)) return;
      await fetch(`/api/users/${btn.dataset.uid}`, {method: "DELETE"});
      await refreshUserList();
    };
  });
}

async function refreshAccessSettings() {
  const r = await fetch("/api/admin/access-settings");
  if (!r.ok) return;
  const settings = await r.json();
  $("setting-anonymous-web").checked = settings.allow_anonymous_web === "1";
  $("setting-user-playlists").checked = settings.allow_user_playlists !== "0";
  $("setting-user-radios").checked = settings.allow_user_radio_stations !== "0";
  $("setting-companion-access").value = settings.companion_access || "public";
}

async function saveAccessSettings() {
  const r = await fetch("/api/admin/access-settings", {
    method: "PUT", headers: {"Content-Type":"application/json"},
    body: JSON.stringify({
      allow_anonymous_web: $("setting-anonymous-web").checked,
      allow_user_playlists: $("setting-user-playlists").checked,
      allow_user_radio_stations: $("setting-user-radios").checked,
      companion_access: $("setting-companion-access").value,
    })
  });
  if (!r.ok) alert("Zugriffseinstellungen konnten nicht gespeichert werden.");
}

async function refreshAdolar4UAdminSettings() {
  const r = await fetch("/api/admin/adolar4u/settings");
  if (!r.ok) return;
  const settings = await r.json();
  $("setting-adolar4u-enabled").checked = Boolean(settings.enabled);
  $("setting-adolar4u-analysis").checked = Boolean(settings.audio_analysis);
  $("setting-adolar4u-collaborative").checked = Boolean(settings.collaborative);
}

async function saveAdolar4UAdminSettings() {
  const r = await fetch("/api/admin/adolar4u/settings", {
    method: "PUT", headers: {"Content-Type":"application/json"},
    body: JSON.stringify({
      enabled: $("setting-adolar4u-enabled").checked,
      audio_analysis: $("setting-adolar4u-analysis").checked,
      collaborative: $("setting-adolar4u-collaborative").checked,
    })
  });
  if (!r.ok) {
    alert("Adolar4U-Einstellungen konnten nicht gespeichert werden.");
    return;
  }
  await loadAdolar4UStatus();
}

async function openAdolar4USettings() {
  $("user-dropdown").classList.remove("open");
  await loadAdolar4UStatus();
  const available = Boolean(_adolar4u.global?.enabled);
  $("adolar4u-available").textContent = available
    ? "Adolar4U ist auf diesem Server verfügbar."
    : "Adolar4U ist derzeit global deaktiviert. Es werden keine Hörsignale erfasst.";
  $("adolar4u-enabled").checked = Boolean(_adolar4u.user?.enabled);
  $("adolar4u-paused").checked = Boolean(_adolar4u.user?.learning_paused);
  $("adolar4u-collaborative").checked = Boolean(_adolar4u.user?.collaborative_enabled);
  $("adolar4u-collaborative").disabled = !_adolar4u.global?.collaborative;
  $("adolar4u-discovery").value = Math.round(Number(_adolar4u.user?.discovery_level ?? .40) * 100);
  $("adolar4u-discovery-value").textContent = `${$("adolar4u-discovery").value}%`;
  $("adolar4u-modal").style.display = "flex";
}

async function saveAdolar4USettings() {
  const r = await fetch("/api/adolar4u/settings", {
    method: "PUT", headers: {"Content-Type":"application/json"},
    body: JSON.stringify({
      enabled: $("adolar4u-enabled").checked,
      learning_paused: $("adolar4u-paused").checked,
      collaborative_enabled: $("adolar4u-collaborative").checked,
      discovery_level: Number($("adolar4u-discovery").value) / 100,
    })
  });
  if (!r.ok) {
    alert("Adolar4U-Einstellungen konnten nicht gespeichert werden.");
    return;
  }
  await loadAdolar4UStatus();
  await loadRadioStations();
  $("adolar4u-modal").style.display = "none";
}

let a4uOnboardingStation = null;
const a4uOnboardingSelection = {artist: [], genre: []};
const a4uOnboardingTimers = {};

function renderAdolar4UOnboardingSelection(kind) {
  const target = $(`a4u-onboarding-${kind}-selected`);
  target.innerHTML = "";
  a4uOnboardingSelection[kind].forEach(value => {
    const chip = document.createElement("span");
    chip.className = "a4u-onboarding-chip";
    const label = document.createElement("span");
    label.textContent = value;
    const remove = document.createElement("button");
    remove.type = "button";
    remove.textContent = "✕";
    remove.title = `${value} entfernen`;
    remove.onclick = () => {
      a4uOnboardingSelection[kind] = a4uOnboardingSelection[kind].filter(item => item !== value);
      renderAdolar4UOnboardingSelection(kind);
    };
    chip.append(label, remove);
    target.appendChild(chip);
  });
  $(`a4u-onboarding-${kind}-count`).textContent = `${a4uOnboardingSelection[kind].length} / 5`;
  $("a4u-onboarding-submit").disabled = !(
    a4uOnboardingSelection.artist.length >= 3 && a4uOnboardingSelection.genre.length >= 3
  );
}

function addAdolar4UOnboardingChoice(kind, value) {
  const selected = a4uOnboardingSelection[kind];
  if (selected.length >= 5 || selected.some(item => item.toLocaleLowerCase() === value.toLocaleLowerCase())) return;
  selected.push(value);
  renderAdolar4UOnboardingSelection(kind);
  $(`a4u-onboarding-${kind}-results`).style.display = "none";
  $(`a4u-onboarding-${kind}-search`).value = "";
}

async function searchAdolar4UOnboardingOptions(kind) {
  const query = $(`a4u-onboarding-${kind}-search`).value.trim();
  const results = $(`a4u-onboarding-${kind}-results`);
  try {
    const response = await fetch(`/api/adolar4u/onboarding/options?kind=${kind}&q=${encodeURIComponent(query)}&limit=12`);
    if (!response.ok) throw new Error();
    const options = await response.json();
    results.innerHTML = "";
    options.filter(option => !a4uOnboardingSelection[kind].some(
      item => item.toLocaleLowerCase() === option.value.toLocaleLowerCase()
    )).forEach(option => {
      const button = document.createElement("button");
      button.type = "button";
      const name = document.createElement("span");
      name.textContent = option.value;
      const count = document.createElement("span");
      count.style.color = "var(--text-tertiary)";
      count.textContent = `${option.track_count} Titel · OK`;
      button.append(name, count);
      button.onclick = () => addAdolar4UOnboardingChoice(kind, option.value);
      results.appendChild(button);
    });
    results.style.display = results.childElementCount ? "block" : "none";
  } catch {
    results.style.display = "none";
  }
}

function queueAdolar4UOnboardingSearch(kind) {
  clearTimeout(a4uOnboardingTimers[kind]);
  a4uOnboardingTimers[kind] = setTimeout(() => searchAdolar4UOnboardingOptions(kind), 180);
}

function openAdolar4UOnboarding(station) {
  a4uOnboardingStation = station;
  a4uOnboardingSelection.artist = [...(_adolar4u.onboarding?.artists || [])].slice(0, 5);
  a4uOnboardingSelection.genre = [...(_adolar4u.onboarding?.genres || [])].slice(0, 5);
  $("a4u-onboarding-error").textContent = "";
  $("a4u-onboarding-modal").style.display = "flex";
  renderAdolar4UOnboardingSelection("artist");
  renderAdolar4UOnboardingSelection("genre");
}

function closeAdolar4UOnboarding() {
  $("a4u-onboarding-modal").style.display = "none";
  a4uOnboardingStation = null;
}

async function completeAdolar4UOnboarding() {
  const button = $("a4u-onboarding-submit");
  if (button.disabled) return;
  button.disabled = true;
  $("a4u-onboarding-error").textContent = "Basisscore und erste Playlist werden erstellt…";
  try {
    const response = await fetch("/api/adolar4u/onboarding", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        artists: a4uOnboardingSelection.artist,
        genres: a4uOnboardingSelection.genre,
      }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Basisscore konnte nicht erstellt werden.");
    _adolar4u.onboarding = data.onboarding;
    _adolar4u.user.enabled = true;
    const station = a4uOnboardingStation;
    $("a4u-onboarding-modal").style.display = "none";
    a4uOnboardingStation = null;
    await startRadio(station, data.initial_playlist || []);
  } catch (error) {
    $("a4u-onboarding-error").textContent = error.message;
    button.disabled = false;
  }
}

async function deleteAdolar4UProfile() {
  if (!confirm("Persönliche Adolar4U-Lerndaten wirklich löschen?")) return;
  const r = await fetch("/api/adolar4u/profile", {method: "DELETE"});
  if (r.ok) {
    await loadAdolar4UStatus();
    alert("Deine Adolar4U-Lerndaten wurden gelöscht.");
  }
}

const A4U_DRIVER_LABELS = {
  play_count: "Bisherige Wiedergaben",
  explicit_favorite: "Favorit/Loved",
  personal_playlist: "Persönliche Playlist",
  completed_history: "Vollständig gehört",
  same_hour: "Passende Tageszeit",
  artist_affinity: "Künstler-Affinität",
  genre_affinity: "Genre-Affinität",
  average_completion: "Hohe Hördauer",
  rediscovery: "Lange nicht gehört",
  discovery: "Entdeckung",
  random: "Kontrollierter Zufall",
  early_skip: "Frühe Abbrüche",
  skip_history: "Bisherige Abbrüche",
  recency: "Wiederholungssperre",
};
const A4U_BUCKET_LABELS = {
  anchor: "Favoriten-Anker", similar: "Ähnlich",
  familiar: "Vertraut", discovery: "Entdeckung",
};
const A4U_OUTCOME_LABELS = {
  completed: "Vollständig gehört", skipped: "Übersprungen",
  started: "Gestartet", without_outcome: "Noch ohne Reaktion",
};

function a4uPercent(value) {
  return value == null ? "–" : `${Math.round(Number(value) * 100)}%`;
}

function a4uDate(value) {
  if (!value) return "–";
  return new Date(Number(value) * 1000).toLocaleString("de-DE", {
    day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit",
  });
}

function a4uChangeList(items) {
  const changed = (items || []).filter(item => Math.abs(Number(item.delta)) >= .005).slice(0, 8);
  if (!changed.length) return `<span style="color:var(--text-tertiary)">Noch keine messbare Veränderung</span>`;
  return changed.map(item => {
    const delta = Number(item.delta);
    return `<span style="display:inline-flex;gap:4px;padding:3px 7px;border-radius:99px;background:var(--bg-secondary);color:${delta >= 0 ? '#78b878' : '#d88787'}">
      ${esc(item.name)} ${delta >= 0 ? "▲" : "▼"}${Math.abs(delta).toFixed(2)}
    </span>`;
  }).join(" ");
}

function a4uDriverList(items, negative = false) {
  if (!(items || []).length) return `<span style="color:var(--text-tertiary)">Noch keine Daten</span>`;
  return items.slice(0, 6).map(item => `
    <div style="display:flex;justify-content:space-between;gap:12px;padding:4px 0">
      <span>${esc(A4U_DRIVER_LABELS[item.key] || item.key)}</span>
      <strong style="color:${negative ? '#d88787' : '#78b878'}">${negative ? '−' : '+'}${Number(item.average).toFixed(2)}</strong>
    </div>`).join("");
}

function renderAdolar4UHistory(data) {
  const summary = data.summary || {};
  const outcomes = summary.outcomes || {};
  const profile = data.profile || {};
  const latest = profile.latest || {};
  $("adolar4u-history-summary").innerHTML = `
    <div class="a4u-history-card"><strong>${Number(summary.recommendations || 0)}</strong><span>Vorschläge</span></div>
    <div class="a4u-history-card"><strong>${Number(outcomes.completed || 0)}</strong><span>vollständig gehört</span></div>
    <div class="a4u-history-card"><strong>${Number(outcomes.skipped || 0)}</strong><span>übersprungen</span></div>
    <div class="a4u-history-card"><strong>${a4uPercent(summary.average_completion)}</strong><span>Ø Hördauer</span></div>
    <div class="a4u-history-card"><strong>${Number(summary.early_skips || 0)}</strong><span>frühe Abbrüche</span></div>`;

  $("adolar4u-history-buckets").innerHTML = (summary.buckets || []).map(bucket => `
    <div style="display:grid;grid-template-columns:minmax(110px,1fr) 52px 58px 76px;gap:8px;padding:7px 0;border-bottom:.5px solid var(--border-subtle);align-items:center">
      <span>${esc(A4U_BUCKET_LABELS[bucket.bucket] || bucket.bucket)}</span>
      <strong>${Number(bucket.count || 0)}</strong>
      <span>${a4uPercent(bucket.share)}</span>
      <span title="Durchschnittliche Hördauer">${a4uPercent(bucket.average_completion)}</span>
    </div>`).join("");

  $("adolar4u-history-positive").innerHTML = a4uDriverList(summary.positive_drivers);
  $("adolar4u-history-negative").innerHTML = a4uDriverList(summary.negative_drivers, true);
  $("adolar4u-profile-artists").innerHTML = a4uChangeList(profile.artist_changes);
  $("adolar4u-profile-genres").innerHTML = a4uChangeList(profile.genre_changes);
  const topArtists = (latest.artists || []).slice(0, 8).map(item => esc(item.name)).join(" · ");
  const topGenres = (latest.genres || []).slice(0, 8).map(item => esc(item.name)).join(" · ");
  $("adolar4u-profile-current").innerHTML = `
    <div><strong>Aktuelle Künstler:</strong> ${topArtists || "Noch keine"}</div>
    <div style="margin-top:5px"><strong>Aktuelle Genres:</strong> ${topGenres || "Noch keine"}</div>
    <div style="margin-top:5px;color:var(--text-tertiary)">Algorithmus: ${esc(profile.algorithm_version || "–")} · letzter Stand ${a4uDate(profile.latest_at)}</div>`;

  const recommendations = data.recommendations || [];
  $("adolar4u-history-empty").style.display = recommendations.length ? "none" : "block";
  $("adolar4u-history-list").innerHTML = recommendations.map(item => {
    const diagnostics = item.diagnostics || {};
    const bonuses = Object.entries(diagnostics.bonuses || {}).map(([key, value]) =>
      `<span>${esc(A4U_DRIVER_LABELS[key] || key)} <b style="color:#78b878">+${Number(value).toFixed(2)}</b></span>`
    );
    bonuses.push(`<span>Kontrollierter Zufall <b style="color:#78b878">+${Number(diagnostics.random_bonus || 0).toFixed(2)}</b></span>`);
    const penalties = Object.entries(diagnostics.penalties || {}).map(([key, value]) =>
      `<span>${esc(A4U_DRIVER_LABELS[key] || key)} <b style="color:#d88787">−${Number(value).toFixed(2)}</b></span>`
    );
    const facts = diagnostics.facts || {};
    return `<details style="border-bottom:.5px solid var(--border-subtle);padding:9px 0">
      <summary style="cursor:pointer;display:grid;grid-template-columns:minmax(160px,1fr) 110px 110px;gap:10px;align-items:center;list-style:none">
        <span><strong>${esc(item.title || "Unbekannt")}</strong><br><small style="color:var(--text-tertiary)">${esc(item.artist || "")} · ${a4uDate(item.created_at)}</small></span>
        <span><small>${esc(A4U_BUCKET_LABELS[item.bucket] || item.bucket)}</small><br>${esc(item.reason)}</span>
        <span style="text-align:right"><small>${esc(A4U_OUTCOME_LABELS[item.outcome] || item.outcome)}</small><br><strong>${a4uPercent(item.completion_ratio)}</strong></span>
      </summary>
      <div style="margin-top:9px;padding:10px;background:var(--bg-secondary);border-radius:8px;font-size:12px;color:var(--text-secondary)">
        <div style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:7px">
          <strong>Score ${Number(item.score).toFixed(2)}</strong>
          <span>Kandidatenrang ${Number(item.candidate_rank || 0)} / ${Number(item.candidate_count || 0)}</span>
          <span>Discovery ${Math.round(Number(item.discovery_level || 0) * 100)}%</span>
          <span>zuletzt gehört ${facts.hours_since_played == null ? "nie" : `${Number(facts.hours_since_played).toFixed(1)} h zuvor`}</span>
        </div>
        <div style="display:flex;gap:10px;flex-wrap:wrap">${[...bonuses, ...penalties].join("")}</div>
      </div>
    </details>`;
  }).join("");
  $("adolar4u-history-retention").textContent = `Diagnosedaten werden automatisch nach ${data.retention_days || 60} Tagen entfernt und beim Löschen der Lerndaten mitgelöscht.`;
}

async function loadAdolar4UHistory() {
  const days = Number($("adolar4u-history-days").value || 7);
  $("adolar4u-history-loading").style.display = "block";
  try {
    const r = await fetch(`/api/adolar4u/history?days=${days}&limit=100`);
    if (!r.ok) throw new Error("history unavailable");
    renderAdolar4UHistory(await r.json());
  } catch {
    $("adolar4u-history-empty").textContent = "Die Lernhistorie konnte nicht geladen werden.";
    $("adolar4u-history-empty").style.display = "block";
  } finally {
    $("adolar4u-history-loading").style.display = "none";
  }
}

async function openAdolar4UHistory() {
  $("adolar4u-modal").style.display = "none";
  $("adolar4u-history-modal").style.display = "flex";
  await loadAdolar4UHistory();
}

function exportAdolar4UHistory() {
  const days = Number($("adolar4u-history-days").value || 60);
  const link = document.createElement("a");
  link.href = `/api/adolar4u/history/export?days=${days}`;
  link.download = "";
  document.body.appendChild(link);
  link.click();
  link.remove();
}

async function refreshBlockedIps() {
  const r = await fetch("/api/admin/blocked-ips");
  const ips = await r.json();
  const wrap = $("usermgmt-blocks-wrap");
  const el   = $("usermgmt-blocks");
  if (!ips.length) { wrap.style.display = "none"; return; }
  wrap.style.display = "block";
  el.innerHTML = "";
  ips.forEach(item => {
    const isPerm = item.blocked_until > 9999999999;
    const rem = isPerm ? null : Math.ceil((item.blocked_until - Date.now()/1000) / 60);
    const row = document.createElement("div");
    row.style.cssText = "display:flex;align-items:center;gap:8px;padding:5px 0;font-size:12px;color:var(--text-secondary)";
    row.innerHTML = `
      <i class="ti ti-ban" style="color:#e03e3e;font-size:12px"></i>
      <span style="flex:1">${esc(item.ip)}</span>
      <span style="color:#e03e3e;font-weight:600">${isPerm ? 'Permanent gesperrt' : `noch ~${rem} Min.`}</span>
      <button data-ip="${esc(item.ip)}" class="unblock-btn"
              style="background:none;border:0.5px solid var(--border-subtle);border-radius:5px;color:var(--accent);cursor:pointer;padding:2px 7px;font-size:11px">
        Entsperren
      </button>
    `;
    el.appendChild(row);
  });
  el.querySelectorAll(".unblock-btn").forEach(btn => {
    btn.onclick = async () => {
      await fetch(`/api/admin/blocked-ips/${encodeURIComponent(btn.dataset.ip)}`, {method: "DELETE"});
      await refreshBlockedIps();
    };
  });
}

async function refreshAuditLog() {
  const r = await fetch("/api/admin/audit-log?limit=30");
  if (!r.ok) return;
  const entries = await r.json();
  const el = $("usermgmt-audit");
  el.innerHTML = entries.length ? entries.map(item => `
    <div style="display:grid;grid-template-columns:125px 105px 1fr;gap:8px;padding:4px 0;border-bottom:0.5px solid var(--border-subtle);font-size:11px;color:var(--text-tertiary)">
      <span>${esc(item.created_at)}</span><span>${esc(item.actor)}</span>
      <span>${esc(item.action)}${item.target ? ` · ${esc(item.target)}` : ""}${item.details ? ` · ${esc(item.details)}` : ""}</span>
    </div>`).join("") : `<div style="font-size:12px;color:var(--text-tertiary)">Noch keine Einträge.</div>`;
}

async function addUser() {
  const errEl = $("usermgmt-error");
  errEl.style.display = "none";
  const username = $("new-user-name").value.trim();
  const password = $("new-user-pw").value;
  const r = await fetch("/api/users", {
    method: "POST", headers: {"Content-Type":"application/json"},
    body: JSON.stringify({username, password})
  });
  const d = await r.json();
  if (d.error) {
    errEl.textContent = d.error;
    errEl.style.display = "block";
  } else {
    $("new-user-name").value = "";
    $("new-user-pw").value = "";
    await refreshUserList();
  }
}
setInterval(checkDiscoBadge, 30000);

// ── Init ───────────────────────────────────────────────────
(async () => {
  applyLang();
  setupRadioModalDrag();
  await meReady;
  hydrateInitialTrackCache();
  // Prioritize the visible track list on a cold NAS disk. Secondary metadata
  // queries run only after the first page has arrived (or refreshed the cache).
  await loadTracks(1);
  await Promise.all([loadStats(), loadGenres(), lfmInit()]);

  const res  = await fetch(`${API}/api/scan/status`);
  const data = await res.json();
  if (data.running) {
    showBanner(t().scanning);
    startScanPolling();
  }
})();
