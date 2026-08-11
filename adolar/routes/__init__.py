"""Flask blueprints for Adolar's HTTP interface."""


def register_blueprints(app) -> None:
    """Register route groups after the application module is initialized."""
    from .adolar4u import blueprint as adolar4u_blueprint
    from .auth import blueprint as auth_blueprint
    from .lyrics import blueprint as lyrics_blueprint
    from .playlists import blueprint as playlists_blueprint

    app.register_blueprint(adolar4u_blueprint)
    app.register_blueprint(auth_blueprint)
    app.register_blueprint(lyrics_blueprint)
    app.register_blueprint(playlists_blueprint)


def start_lyrics_startup_scan() -> None:
    """Start the optional initial lyrics scan after database bootstrap."""
    from .lyrics import start_scan

    start_scan("startup")
