"""
AdolarRadio – Windows companion app for Adolar.
Single-file pywebview app. Build to .exe with: pyinstaller adolar_radio.spec
"""

import contextlib
import json
import os
import sys

import webview

CONFIG_PATH = os.path.join(os.environ.get("APPDATA", "."), "AdolarRadio", "config.json")

SETTINGS_HTML = """<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>AdolarRadio – Einstellungen</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@tabler/icons-webfont@latest/tabler-icons.min.css">
<link href="https://fonts.googleapis.com/css2?family=Orbitron:wght@700&display=swap" rel="stylesheet">
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    background: #1E1E1C; color: #ECECEC;
    height: 100vh; display: flex; flex-direction: column;
    align-items: center; justify-content: center; padding: 24px;
    user-select: none;
  }
  .logo { display: flex; align-items: center; gap: 10px; margin-bottom: 28px; }
  .logo img { width: 40px; height: 40px; }
  .logo span {
    font-family: "Orbitron", monospace; font-size: 22px; font-weight: 700;
    letter-spacing: 0.08em;
    background: linear-gradient(135deg, #7F77DD, #b8b4f0);
    -webkit-background-clip: text; -webkit-text-fill-color: transparent;
    background-clip: text;
  }
  label { font-size: 12px; color: #9A9A96; margin-bottom: 6px; display: block; }
  input {
    width: 100%; padding: 9px 12px;
    background: #3A3A38; border: 0.5px solid #505050;
    border-radius: 8px; color: #ECECEC; font-size: 14px; outline: none;
    margin-bottom: 16px;
  }
  input:focus { border-color: #7F77DD; }
  button {
    width: 100%; padding: 10px;
    background: #7F77DD; border: none; border-radius: 8px;
    color: #fff; font-size: 14px; font-weight: 600;
    cursor: pointer; transition: background .15s;
  }
  button:hover { background: #9E98E8; }
  .hint { font-size: 11px; color: #5C5C58; margin-top: 12px; text-align: center; line-height: 1.5; }
  .error { color: #e03e3e; font-size: 12px; margin-top: 8px; display: none; }
  .btn-about {
    width: 18px; height: 18px; border-radius: 50%;
    border: 1.5px solid #9A9A96; background: none;
    color: #9A9A96; font-size: 12px; font-weight: 700;
    cursor: pointer; display: flex; align-items: center; justify-content: center;
    padding: 0; line-height: 1; margin-left: 4px; opacity: 0.5;
    transition: opacity .15s; flex-shrink: 0;
  }
  .btn-about:hover { opacity: 1; background: none; }
  .modal-overlay {
    display: none; position: fixed; inset: 0; background: rgba(0,0,0,.6);
    align-items: center; justify-content: center; z-index: 999;
  }
  .modal-overlay.open { display: flex; }
  .modal-box {
    background: #2A2A28; border: 1px solid #444; border-radius: 12px;
    padding: 32px 40px; min-width: 260px; text-align: center; position: relative;
  }
  .modal-close {
    position: absolute; top: 10px; right: 14px;
    background: none; border: none; color: #9A9A96;
    font-size: 18px; cursor: pointer; width: auto; padding: 0;
  }
  .modal-close:hover { background: none; color: #ECECEC; }
  .modal-name {
    font-family: "Orbitron", monospace; font-size: 1.2rem; font-weight: 700;
    background: linear-gradient(135deg, #7F77DD, #b8b4f0);
    -webkit-background-clip: text; -webkit-text-fill-color: transparent;
    background-clip: text; margin-bottom: 4px;
  }
  .modal-sub { color: #9A9A96; font-size: 12px; margin-bottom: 8px; }
  .modal-link { color: #7F77DD; font-size: 12px; display: block; margin-top: 4px; text-decoration: none; }
  .modal-link:hover { text-decoration: underline; }
</style>
</head>
<body>
<div class="logo">
  <img src="data:image/svg+xml;base64,{LOGO_B64}" alt="Adolar">
  <span>Adolar</span>
  <button class="btn-about" onclick="document.getElementById('about-modal').classList.add('open')">?</button>
</div>

<div class="modal-overlay" id="about-modal" onclick="if(event.target===this)this.classList.remove('open')">
  <div class="modal-box">
    <button class="modal-close" onclick="document.getElementById('about-modal').classList.remove('open')">✕</button>
    <img src="data:image/svg+xml;base64,{LOGO_B64}" width="48" height="48" alt="Adolar" style="margin-bottom:12px">
    <div class="modal-name">AdolarRadio</div>
    <div class="modal-sub">Version v1.3.0</div>
    <div class="modal-sub">(c) PolzeSoft 2026</div>
    <a class="modal-link" href="https://polze.net">https://polze.net</a>
    <a class="modal-link" href="mailto:adolar@polze.net">adolar@polze.net</a>
  </div>
</div>
<div style="width:100%;max-width:280px">
  <label>Adolar Server URL</label>
  <input type="text" id="url" placeholder="http://192.168.1.X:15002" value="{CURRENT_URL}">
  <button onclick="save()">Verbinden</button>
  <div class="error" id="err">Ungültige URL – bitte http://host:port eingeben.</div>
  <p class="hint">Beispiel: http://192.168.1.100:15002<br>oder http://localhost:15002</p>
</div>
<script>
function save() {
  const url = document.getElementById("url").value.trim().replace(/\\/$/, "");
  if (!url.startsWith("http")) {
    document.getElementById("err").style.display = "block"; return;
  }
  document.getElementById("err").style.display = "none";
  window.pywebview.api.save_and_launch(url);
}
document.getElementById("url").addEventListener("keydown", e => {
  if (e.key === "Enter") save();
});
</script>
</body>
</html>"""


def load_config():
    try:
        with open(CONFIG_PATH) as f:
            return json.load(f)
    except Exception:
        return {}


def save_config(data: dict):
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump(data, f, indent=2)



def logo_b64() -> str:
    """Return base64-encoded logo.svg from same dir as this script / the exe."""
    import base64
    candidates = [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "static", "logo.svg"),
        os.path.join(os.path.dirname(sys.executable), "logo.svg"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "logo.svg"),
    ]
    for path in candidates:
        if os.path.isfile(path):
            with open(path, "rb") as f:
                return base64.b64encode(f.read()).decode()
    return ""


class Api:
    def __init__(self, win_ref):
        self._win = win_ref   # list so we can replace the window reference
        self._settings_windows = []

    def save_and_launch(self, url: str):
        url = url.rstrip("/")
        save_config({"url": url})
        self._win[0].load_url(url + "/radio")
        self._win[0].set_title("AdolarRadio")
        self._win[0].resize(320, 520)
        self.open_settings()

    def disconnect(self):
        save_config({})
        self._close_settings_windows()
        html = _build_settings_html("")
        self._win[0].load_html(html)
        self._win[0].set_title("AdolarRadio – Einstellungen")
        self._win[0].resize(320, 340)
        return {"ok": True}

    def open_settings(self):
        cfg = load_config()
        url = (cfg.get("url") or "").rstrip("/")
        if not url:
            html = _build_settings_html("")
            self._win[0].load_html(html)
            self._win[0].set_title("AdolarRadio – Einstellungen")
            self._win[0].resize(320, 340)
            return
        settings = webview.create_window(
            title="AdolarRadio – Einstellungen",
            url=url + "/radio/settings",
            width=340,
            height=430,
            resizable=False,
            on_top=True,
            js_api=self,
        )
        self._settings_windows.append(settings)

    def refresh_radio_user(self):
        script = """
          initUser()
            .then(() => lfmInit())
            .then(() => loadStations(true))
            .catch(() => {});
        """
        with contextlib.suppress(Exception):
            self._win[0].evaluate_js(script)
        return {"ok": True}

    def _close_settings_windows(self):
        for win in list(self._settings_windows):
            with contextlib.suppress(Exception):
                win.destroy()
        self._settings_windows.clear()


def _build_settings_html(current_url: str) -> str:
    b64 = logo_b64()
    return (SETTINGS_HTML
            .replace("{LOGO_B64}", b64)
            .replace("{CURRENT_URL}", current_url))


def main():
    cfg = load_config()
    url = cfg.get("url", "")

    win_ref = [None]
    api = Api(win_ref)

    if url:
        radio_url = url.rstrip("/") + "/radio"
        win = webview.create_window(
            title="AdolarRadio",
            url=radio_url,
            width=320,
            height=520,
            resizable=False,
            on_top=True,
            min_size=(280, 420),
            js_api=api,
        )
    else:
        html = _build_settings_html("")
        win = webview.create_window(
            title="AdolarRadio – Einstellungen",
            html=html,
            width=320,
            height=340,
            resizable=False,
            on_top=True,
            js_api=api,
        )

    win_ref[0] = win
    webview.start(debug=False, private_mode=False)


if __name__ == "__main__":
    main()
