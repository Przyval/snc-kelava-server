import os

from dotenv import load_dotenv
from flask import Flask

# Load environment variables
load_dotenv()


def create_app():
    """
    Application Factory for the new SAP-Grade ERP.
    """
    app = Flask(__name__)

    # 1. Load Configuration (Pydantic/Env)
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-secret-key")

    # 2. Register Blueprints
    # 2.1 Legacy Routes (The "Strangler" Pattern Target)
    # We import the legacy app factory or blueprints here.
    # For now, we will try to mimic the old entry point or mount its blueprints.
    # TODO: Import legacy blueprints (api, web) after refactoring their imports.

    # 2.2 New "SAP Grade" Modules
    # from .modules.access_control.routes import auth_bp
    # app.register_blueprint(auth_bp, url_prefix='/api/v2/auth')

    @app.route("/health")
    def health_check():
        return {"status": "ok", "system": "Kelava Enterprise v2"}

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)), debug=True)
