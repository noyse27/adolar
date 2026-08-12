import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import run as run_module  # noqa: E402


def test_gunicorn_uses_bounded_thread_workers_for_streaming():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert '"--worker-class", "gthread"' in dockerfile
    assert '"--workers", "2"' in dockerfile
    assert '"--threads", "4"' in dockerfile
    assert '"--graceful-timeout", "30"' in dockerfile


def test_bare_metal_launcher_uses_the_same_gunicorn_flags_as_docker():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    match = re.search(r"CMD \[(.*)\]", dockerfile)
    assert match, "Dockerfile CMD not found"
    docker_args = [part.strip().strip('"') for part in match.group(1).split(",")]
    assert docker_args == run_module.GUNICORN_ARGS


def test_db_path_is_anchored_to_data_root_not_the_docker_only_default():
    app_source = (ROOT / "adolar" / "application.py").read_text(encoding="utf-8")
    assert 'db.DB_PATH = os.environ.get("DB_PATH") or os.path.join(DATA_ROOT, "adolar.db")' in app_source


def test_compose_allows_gunicorn_a_graceful_shutdown():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "stop_grace_period: 30s" in compose


def test_active_radio_queue_can_be_restored_after_browsing_a_playlist():
    page = (ROOT / "static" / "js" / "app.js").read_text(encoding="utf-8")
    assert "function showCurrentRadioQueue()" in page
    assert "if (radio.active && radio.browsingLibrary) showCurrentRadioQueue();" in page
    assert "radio.browsingLibrary = true;\n    updateRadioButton();" in page
    assert "if (!radio.browsingLibrary) {" in page
