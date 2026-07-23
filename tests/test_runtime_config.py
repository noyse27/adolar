from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_gunicorn_uses_bounded_thread_workers_for_streaming():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert '"--worker-class", "gthread"' in dockerfile
    assert '"--workers", "2"' in dockerfile
    assert '"--threads", "4"' in dockerfile
    assert '"--graceful-timeout", "30"' in dockerfile


def test_compose_allows_gunicorn_a_graceful_shutdown():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "stop_grace_period: 30s" in compose


def test_active_radio_queue_can_be_restored_after_browsing_a_playlist():
    page = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    assert "function showCurrentRadioQueue()" in page
    assert "if (radio.active && radio.browsingLibrary) showCurrentRadioQueue();" in page
    assert "radio.browsingLibrary = true;\n    updateRadioButton();" in page
    assert "if (!radio.browsingLibrary) {" in page
