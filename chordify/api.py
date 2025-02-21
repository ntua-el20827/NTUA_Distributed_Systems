import hashlib
from flask import Flask, request, jsonify
import argparse
import requests
import threading, time, os
from node import Node

app = Flask(__name__)

# Η μεταβλητή node θα περιέχει το instance του τρέχοντος κόμβου.
node = None

############################################################################################################
# JOIN

# Global ring list (κάθε εγγραφή είναι λεξικό με βασικά στοιχεία του κόμβου)
ring = []

def update_ring(new_node_info):
    global ring
    # Προσθήκη νέου κόμβου, μόνο αν δεν υπάρχει ήδη
    if not any(n['id'] == new_node_info['id'] for n in ring):
        ring.append(new_node_info)
    
    # Ταξινόμηση του ring βάσει του id
    ring.sort(key=lambda n: n['id'])
    n = len(ring)
    
    # Ενημέρωση των pointers για κάθε κόμβο στο ring.
    for i in range(n):
        # Ο κόμβος successor είναι ο επόμενος στη σειρά (με wrap-around)
        successor = ring[(i + 1) % n]
        # Ο κόμβος predecessor είναι ο προηγούμενος στη σειρά (με wrap-around)
        predecessor = ring[(i - 1) % n]
        
        # Ενημέρωση του κάθε κόμβου (δημιουργούμε νέα λεξικά για να αποφύγουμε εσωτερικές αναφορές)
        ring[i] = {
            "ip": ring[i]["ip"],
            "port": ring[i]["port"],
            "id": ring[i]["id"],
            "successor": {
                "ip": successor["ip"],
                "port": successor["port"],
                "id": successor["id"]
            },
            "predecessor": {
                "ip": predecessor["ip"],
                "port": predecessor["port"],
                "id": predecessor["id"]
            }
        }
    return ring

# Στο api.py

@app.route("/join", methods=["POST"])
def join():
    # Μόνο ο bootstrap κόμβος δέχεται join requests
    if not node.is_bootstrap:
        return jsonify({"error": "Μόνο ο bootstrap κόμβος δέχεται join requests"}), 400

    data = request.get_json()
    new_node_ip = data.get("ip")
    new_node_port = data.get("port")
    new_node_id = data.get("id")
    new_node_info = {"ip": new_node_ip, "port": new_node_port, "id": new_node_id}
    print(f"[Bootstrap] Node joining: {new_node_info}")

    global ring
    # Προσθήκη του νέου κόμβου στο ring, αν δεν υπάρχει ήδη
    if not any(n["id"] == new_node_id for n in ring):
        ring.append(new_node_info)

    # Επαναϋπολογισμός του ring (ταξινόμηση και αναθεώρηση των pointers)
    ring.sort(key=lambda n: n["id"])
    n = len(ring)
    for i in range(n):
        successor = ring[(i + 1) % n]
        predecessor = ring[(i - 1) % n]
        ring[i]["successor"] = {"ip": successor["ip"], "port": successor["port"], "id": successor["id"]}
        ring[i]["predecessor"] = {"ip": predecessor["ip"], "port": predecessor["port"], "id": predecessor["id"]}

    # Broadcast: Ενημέρωση όλων των κόμβων στο ring για τους νέους pointers
    for n_info in ring:
        # Αν ο κόμβος είναι ο bootstrap, ενημέρωσε το τοπικό node object
        if n_info["ip"] == node.ip and n_info["port"] == node.port:
            node.update_neighbors(n_info["successor"], n_info["predecessor"])
        else:
            try:
                url = f"http://{n_info['ip']}:{n_info['port']}/update_neighbors"
                payload = {
                    "successor": n_info["successor"],
                    "predecessor": n_info["predecessor"]
                }
                requests.post(url, json=payload)
            except Exception as e:
                print(f"[Bootstrap] Σφάλμα κατά την ενημέρωση του κόμβου {n_info}: {e}")

    # Εύρεση του joining κόμβου στο ring για να επιστραφούν τα pointers του
    for entry in ring:
        if entry["id"] == new_node_id:
            return jsonify({
                "message": "Επιτυχής ένταξη",
                "successor": entry["successor"],
                "predecessor": entry["predecessor"],
                "ring": ring  # Προαιρετικό για debugging
            }), 200

    return jsonify({"error": "Ο νέος κόμβος δεν βρέθηκε στο ring"}), 500


@app.route("/update_neighbors", methods=["POST"])
def update_neighbors():
    data = request.get_json()
    new_successor = data.get("successor")
    new_predecessor = data.get("predecessor")
    print(f"[{node.ip}:{node.port}] Ενημέρωση γειτόνων: successor={new_successor}, predecessor={new_predecessor}")
    node.update_neighbors(new_successor, new_predecessor)
    return jsonify({"message": "Neighbors updated successfully"}), 200



############################################################################################################
#DEPART

def serialize_node_info(n):
    """
    Λαμβάνει ένα λεξικό με πληροφορίες κόμβου και επιστρέφει ένα νέο λεξικό
    που περιέχει μόνο τις βασικές πληροφορίες, χωρίς pointers.
    """
    return {"id": n["id"], "ip": n["ip"], "port": n["port"]}

@app.route("/remove_node", methods=["POST"])
def remove_node():
    # Ο κόμβος που θέλει να αποχωρήσει στέλνει εδώ τα στοιχεία του.
    # Ο bootstrap αφαιρεί τον κόμβο από το ring και επαναϋπολογίζει τους predecessor και successor
    # για όλους τους υπόλοιπους κόμβους, ώστε να μην υπάρχουν circular references.
    if not node.is_bootstrap:
        return jsonify({"error": "Only bootstrap can remove a node from ring"}), 400

    data = request.get_json()
    rm_id = data.get("id")
    rm_ip = data.get("ip")
    rm_port = data.get("port")
    print(f"[Bootstrap] Removing node: {rm_ip}:{rm_port} (id={rm_id})")

    global ring
    before_len = len(ring)
    # Αφαιρούμε τον κόμβο που αποχωρεί
    ring = [n for n in ring if n["id"] != rm_id]
    after_len = len(ring)
    print(f"[Bootstrap] Ring size changed from {before_len} to {after_len}")

    # Επαναϋπολογισμός των pointers, χωρίς αναφορές που δημιουργούν circular structure.
    if after_len > 0:
        ring = sorted(ring, key=lambda n: n["id"])
        n = len(ring)
        new_ring = []
        for i in range(n):
            succ = ring[(i + 1) % n]
            pred = ring[(i - 1) % n]
            new_ring.append({
                "id": ring[i]["id"],
                "ip": ring[i]["ip"],
                "port": ring[i]["port"],
                "successor": serialize_node_info(succ),
                "predecessor": serialize_node_info(pred)
            })
        ring = new_ring

        print(f"[Bootstrap] Updated ring pointers:")
        for n_info in ring:
            print(f"  Node {n_info['ip']}:{n_info['port']} (id={n_info['id']}) -> predecessor: {n_info['predecessor']['id']}, successor: {n_info['successor']['id']}")
    else:
        print("[Bootstrap] Ring is empty.")

    return jsonify({"message": "Node removed from ring", "ring": ring}), 200


@app.route("/depart", methods=["POST"])
def depart():
    """
    Το endpoint για να καλέσει ο κόμβος local (π.χ. curl -X POST /depart) και να εκτελεστεί node.depart()
    """
    if node.is_bootstrap:
        return jsonify({"error": "Bootstrap does not depart"}), 400
    else:
        success = node.depart()
        if success:
            def shutdown_after_delay():
                time.sleep(1)
                os._exit(0)
            t = threading.Thread(target=shutdown_after_delay)
            t.start()
            return jsonify({"message": "Node departed gracefully"}), 200
        else:
            return jsonify({"error": "Depart failed"}), 500

############################################################################################################
# INSERT, QUERY, DELETE

def compute_hash(self, key):
    # Υπολογισμός του SHA1 hash ενός string και επιστροφή ως ακέραιος.
    h = hashlib.sha1(key.encode('utf-8')).hexdigest()
    return int(h, 16)

@app.route("/insert", methods=["POST"])
def insert():
    # Endpoint εισαγωγής ενός key-value ζεύγους.
    # Αναμένει JSON με τα πεδία "key" και "value".
    data = request.get_json()
    key = data.get("key")
    value = data.get("value")
    result = node.insert(key, value)
    #  print hash of key   
    key_hash = compute_hash(node, key)
    print(f"[{node.ip}:{node.port}] Αίτημα insert για το key '{key}' (hash: {key_hash}).")
    return jsonify({"result": result, "data_store": node.data_store}), 200

@app.route("/query/<key>", methods=["GET"])
def query(key):
    # Endpoint αναζήτησης ενός key.
    # Επιστρέφει το value αν βρεθεί, αλλιώς σφάλμα 404.
    value = node.query(key)
    if value is not None:
        return jsonify({"key": key, "value": value}), 200
    else:
        return jsonify({"error": "Το key δεν βρέθηκε"}), 404

@app.route("/delete", methods=["POST"])
def delete():
    # Endpoint διαγραφής ενός key.
    # Αναμένει JSON με το πεδίο "key".
    data = request.get_json()
    key = data.get("key")
    result = node.delete(key)
    if result:
        return jsonify({"result": True}), 200
    else:
        return jsonify({"error": "Το key δεν βρέθηκε"}), 404

@app.route("/overlay", methods=["GET"])
def overlay():
    # Επιστρέφει το overlay (ολόκληρο το ring).
    # Αν ο κόμβος είναι bootstrap, επιστρέφει το τοπικό ring.
    # Αν όχι, μπορεί να ζητήσει πληροφορίες από τον bootstrap.
    if node.is_bootstrap:
        # Σχηματίζω το json που θα επιστρέψω
        minimal_ring = []
        for entry in ring:
            minimal_ring.append({
                "id": entry["id"],
                "ip": entry["ip"],
                "port": entry["port"],
                "predecessor": entry["predecessor"]["ip"],
                "successor": entry["successor"]["ip"]
            })
        return jsonify({"ring": minimal_ring}), 200
    else:
        try:
            bootstrap_url = f"http://{node.bootstrap_ip}:{node.bootstrap_port}/overlay"
            response = requests.get(bootstrap_url)
            if response.status_code == 200:
                return response.json(), 200
            else:
                return jsonify({"error": "Δεν ήταν δυνατή η λήψη του overlay"}), 500
        except Exception as e:
            return jsonify({"error": str(e)}), 500

############################################################################################################
# MAIN

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("--ip", type=str, default="127.0.0.1", help="IP διεύθυνση του κόμβου")
    parser.add_argument("-p", "--port", type=int, default=8000, help="Θύρα του κόμβου")
    parser.add_argument("--bootstrap", action="store_true", help="Ενεργοποίηση ως bootstrap κόμβος")
    parser.add_argument("--bootstrap_ip", type=str, default="127.0.0.1", help="IP του bootstrap κόμβου")
    parser.add_argument("--bootstrap_port", type=int, default=8000, help="Θύρα του bootstrap κόμβου")
    args = parser.parse_args()

    from node import Node
    node = Node(ip=args.ip, port=args.port, is_bootstrap=args.bootstrap)
    
    # Αν δεν είμαστε bootstrap, αποθηκεύουμε τα στοιχεία του bootstrap για μελλοντική επικοινωνία.
    if not node.is_bootstrap:
        node.bootstrap_ip = args.bootstrap_ip
        node.bootstrap_port = args.bootstrap_port

    if not node.is_bootstrap:
        joined = node.join(args.bootstrap_ip, args.bootstrap_port)
        if not joined:
            print("Αποτυχία ένταξης στο δίκτυο")
        else:
            print("Επιτυχής ένταξη στο δίκτυο")
    else:
        # Ο bootstrap ξεκινάει προσθέτοντας τον εαυτό του στο ring.
        bootstrap_info = {"ip": node.ip, "port": node.port, "id": node.id}
        ring.append(bootstrap_info)
        # Ο ίδιος ο bootstrap είναι και predecessor και successor του (self-loop)
        #bootstrap_info['successor'] = bootstrap_info
        #bootstrap_info['predecessor'] = bootstrap_info
        #print("Είμαι ο Bootstrap κόμβος.")

    app.run(host="0.0.0.0", port=args.port, debug=True, use_reloader=False)
