import os
from pathlib import Path

from flask import Flask, render_template
from flask_login import current_user

from config import Config
from .db_utils import ensure_database_exists
from .extensions import csrf, db, login_manager, migrate
from .models import User


def create_app(config_overrides=None):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(Config)
    if config_overrides:
        app.config.update(config_overrides)
    if app.config.get("SQLALCHEMY_DATABASE_URI"):
        ensure_database_exists(app.config["SQLALCHEMY_DATABASE_URI"])
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    Path(app.config["UPLOAD_FOLDER"]).mkdir(parents=True, exist_ok=True)
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    from .routes import auth, main
    app.register_blueprint(auth)
    app.register_blueprint(main)

    @app.context_processor
    def inject_globals():
        return {"current_user": current_user}

    @app.errorhandler(403)
    def forbidden(_error):
        return render_template("errors/403.html"), 403

    @app.errorhandler(404)
    def not_found(_error):
        return render_template("errors/404.html"), 404

    @app.errorhandler(413)
    def too_large(_error):
        return "File terlalu besar (maksimum 8 MB).", 413

    return app
