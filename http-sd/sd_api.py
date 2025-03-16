from flask import Flask, request, jsonify

app = Flask(__name__)

# In-memory store for discovered services
targets = []

@app.route("/", methods=["GET"])
def home():
    return "OK"

@app.route("/sd", methods=["GET"])
def get_service_discovery():
    """Return the current list of targets for Prometheus."""
    return jsonify(targets)

@app.route("/sd", methods=["POST"])
def add_target():
    """Add a new service to the discovery list."""
    data = request.get_json()
    if not data or "targets" not in data:
        return jsonify({"error": "Invalid data"}), 400
    
    targets.append(data)
    return jsonify({"message": "Target added", "current_targets": targets})

@app.route("/sd", methods=["DELETE"])
def remove_target():
    """Remove a service from the discovery list."""
    data = request.get_json()
    if not data or "targets" not in data:
        return jsonify({"error": "Invalid data"}), 400

    global targets
    targets = [tg for tg in targets if tg["targets"] != data["targets"]]
    return jsonify({"message": "Target removed", "current_targets": targets})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)