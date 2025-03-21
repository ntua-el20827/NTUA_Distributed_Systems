# app.py
import argparse
from flask import Flask
from flask_cors import CORS  # Import flask-cors
from node import Node
from routes.join import join_bp
from routes.depart import depart_bp
from routes.overlay import overlay_bp
from routes.query import query_bp
from routes.delete import delete_bp
from routes.insert import insert_bp

app = Flask(__name__)
CORS(app)  # Enable CORS on the app

# Global node instance (or alternatively, configure it in app.config)
node = None

# Create or initialize ring here if bootstrap
app.config['RING'] = []

# Register blueprints for different functionalities
app.register_blueprint(join_bp)
app.register_blueprint(depart_bp)
app.register_blueprint(insert_bp)
app.register_blueprint(overlay_bp)
app.register_blueprint(query_bp)
app.register_blueprint(delete_bp)

if __name__ == '__main__':
    
    parser = argparse.ArgumentParser()
    parser.add_argument("--ip", type=str, default="127.0.0.1", help="IP διεύθυνση του κόμβου")
    parser.add_argument("-p", "--port", type=int, default=8000, help="Θύρα του κόμβου")
    parser.add_argument("--bootstrap", action="store_true", help="Ενεργοποίηση ως bootstrap κόμβος")
    parser.add_argument("--bootstrap_ip", type=str, default="127.0.0.1", help="IP του bootstrap κόμβου")
    parser.add_argument("--bootstrap_port", type=int, default=8000, help="Θύρα του bootstrap κόμβου")
    parser.add_argument("--replication_factor", type=int, default=1, help="Replication factor for data")
    parser.add_argument("--consistency_mode", type=str, choices=["linearizability", "eventual"], default="strong", help="Consistency mode for data replication")
    args = parser.parse_args()

    # Initialize the Node instance
    node = Node(ip=args.ip, port=args.port, is_bootstrap=args.bootstrap, consistency_mode=args.consistency_mode, replication_factor=args.replication_factor)
    
    # Store bootstrap info for non-bootstrap nodes
    if not node.is_bootstrap:
        node.bootstrap_ip = args.bootstrap_ip
        node.bootstrap_port = args.bootstrap_port
        joined = node.join(args.bootstrap_ip, args.bootstrap_port)
        if not joined:
            print("Αποτυχία ένταξης στο δίκτυο")
        else:
            print("Επιτυχής ένταξη στο δίκτυο")
    else:
        # if node.is_bootstrap, store ring with self in it:
        bootstrap_info = {
            "ip": node.ip,
            "port": node.port,
            "id": node.id,
            "successor": {},
            "predecessor": {}
        }
        # This ensures the ring has at least the bootstrap node
        node.replication_factor = 3
        node.consistency_mode = "eventual"
        app.config['RING'] = [bootstrap_info]

    # Optionally, set the node instance in app.config or a dedicated module so that
    # the routes can access it.
    app.config['NODE'] = node

    app.run(host="0.0.0.0", port=args.port, debug=True, use_reloader=False, threaded=True)
