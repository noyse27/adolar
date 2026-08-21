"""Flask blueprints for Adolar's HTTP interface."""


def register_blueprints(app) -> None:
    """Register route groups after the application module is initialized."""
    from .admin import blueprint as admin_blueprint
    from .adolar4u import blueprint as adolar4u_blueprint
    from .auth import blueprint as auth_blueprint
    from .catalog import blueprint as catalog_blueprint
    from .lastfm import blueprint as lastfm_blueprint
    from .lyrics import blueprint as lyrics_blueprint
    from .media import blueprint as media_blueprint
    from .playlists import blueprint as playlists_blueprint
    from .radio import blueprint as radio_blueprint
    from .scanner import blueprint as scanner_blueprint
    from .songster import blueprint as songster_blueprint

    app.register_blueprint(adolar4u_blueprint)
    app.register_blueprint(admin_blueprint)
    app.register_blueprint(auth_blueprint)
    app.register_blueprint(catalog_blueprint)
    app.register_blueprint(lyrics_blueprint)
    app.register_blueprint(lastfm_blueprint)
    app.register_blueprint(media_blueprint)
    app.register_blueprint(playlists_blueprint)
    app.register_blueprint(radio_blueprint)
    app.register_blueprint(scanner_blueprint)
    app.register_blueprint(songster_blueprint)


def start_lyrics_startup_scan() -> None:
    """Start the optional initial lyrics scan after database bootstrap."""
    from .lyrics import start_scan

    start_scan("startup")


def run_scheduled_backup() -> None:
    """Run one automatic backup from the scheduler in application.py."""
    from .admin import run_backup_job

    run_backup_job("automatic")


def flush_play_count_tags() -> None:
    """Flush dirty archive play counts from the daily scheduler."""
    from .media import flush_play_count_tags as flush

    flush()
