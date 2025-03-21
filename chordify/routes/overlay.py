# routes/overlay.py
from flask import Blueprint, request, jsonify, current_app
import requests

overlay_bp = Blueprint('overlay', __name__)

# The overlay route is used to retrieve the current state of the overlay network.
@overlay_bp.route("/overlay", methods=["GET"])
def overlay():
    node = current_app.config['NODE']
    if node.is_bootstrap:
        ring = current_app.config.get('RING', [])
        minimal_ring = []
        for entry in ring:
            successor = f"{entry['successor']['ip']}:{entry['successor']['port']}"
            predecessor = f"{entry['predecessor']['ip']}:{entry['predecessor']['port']}"
            minimal_ring.append({
                "id": entry["id"],
                "ip": entry["ip"],
                "port": entry["port"],
                "predecessor": predecessor,
                "successor": successor
            })
        return jsonify({"ring": minimal_ring}), 200
    else:
        try:
            bootstrap_url = f"http://{node.bootstrap_ip}:{node.bootstrap_port}/overlay"
            response = requests.get(bootstrap_url)
            if response.status_code == 200:
                return response.json(), 200
            else:
                return jsonify({"error": "Failed to retrieve overlay information from bootstrap node"}), 500
        except Exception as e:
            return jsonify({"error": str(e)}), 500

# The following routes are added during the testing phase of the project in the AWS environment, in order to execute all the necessary experiments without the need to manually update the settings of each node.
# To do that we simply delete all the songs from the nodes and then update the settings of the nodes.

@overlay_bp.route("/update_settings", methods=["POST"])
def update_settings():
    node = current_app.config['NODE']
    # 1. This route can be executed only from the bootstrap node.
    if not node.is_bootstrap:
        return jsonify({"error": "Only the bootstrap node can update settings."}), 403

    # 2. Extract the new settings from the request
    data = request.get_json()
    new_replication_factor = data.get("replication_factor")
    new_consistency_mode = data.get("consistency_mode")
    if new_replication_factor is None or new_consistency_mode is None:
        return jsonify({"error": "Missing replication_factor or consistency_mode in the request"}), 400

    # 3. Get the ring info (list of nodes)
    ring = current_app.config.get("RING", [])
    if not ring:
        return jsonify({"error": "Ring information is not available."}), 500

    # Create a dictionary for the bootstrap node details to use as origin.
    bootstrap_info = {"ip": node.ip, "port": node.port}

    # 4. For each node in the ring, send a deletion request for each song.
    for entry in ring:
        ip = entry["ip"]
        port = entry["port"]
        try:
            # Retrieve node info (including the data_store containing songs)
            nodeinfo_url = f"http://{ip}:{port}/nodeinfo"
            resp = requests.get(nodeinfo_url)
            if resp.status_code == 200:
                node_info = resp.json()
                # Assuming songs are stored as keys in the data_store dictionary
                songs = list(node_info.get("data_store", {}).keys())
                for song in songs:
                    delete_url = f"http://{ip}:{port}/delete"
                    # Use the dictionary for origin instead of a string.
                    payload = {"key": song, "origin": bootstrap_info}
                    del_resp = requests.post(delete_url, json=payload)
                    if del_resp.status_code != 200:
                        print(f"Failed to delete song '{song}' on node {ip}:{port}")
            else:
                print(f"Failed to retrieve node info from {ip}:{port}")
        except Exception as e:
            print(f"Error contacting node {ip}:{port} for deletion: {e}")

    # 5. Now, send the new replication_factor and consistency_mode to all nodes.
    for entry in ring:
        ip = entry["ip"]
        port = entry["port"]
        try:
            update_url = f"http://{ip}:{port}/update_config"
            update_payload = {
                "replication_factor": new_replication_factor,
                "consistency_mode": new_consistency_mode
            }
            upd_resp = requests.post(update_url, json=update_payload)
            if upd_resp.status_code != 200:
                print(f"Failed to update settings on node {ip}:{port}")
        except Exception as e:
            print(f"Error updating settings on node {ip}:{port}: {e}")

    return jsonify({"result": "Settings update initiated successfully."}), 200


@overlay_bp.route("/update_config", methods=["POST"])
def update_config():
    # This route is used by the bootstrap node to update the configuration settings of a node.
    node = current_app.config['NODE']
    data = request.get_json()
    new_replication_factor = data.get("replication_factor")
    new_consistency_mode = data.get("consistency_mode")
    if new_replication_factor is None or new_consistency_mode is None:
        return jsonify({"error": "Missing replication_factor or consistency_mode in the request"}), 400
    node.update_replication_consistency(new_replication_factor, new_consistency_mode)
    return jsonify({"message": "Settings updated successfully"}), 200