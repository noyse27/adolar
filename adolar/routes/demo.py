"""Public demo-mode status endpoint, backing the frontend's demo banner."""
from flask import Blueprint, jsonify

from .. import demo_mode

blueprint = Blueprint("demo", __name__)


@blueprint.get("/api/demo/status")
def api_demo_status():
    return jsonify(demo_mode.demo_status())
