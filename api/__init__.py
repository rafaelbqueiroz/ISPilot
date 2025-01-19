from flask import Flask, jsonify

app = Flask(__name__)

@app.route('/api/__init__', methods=['POST'])
def handler():
    return jsonify({"status": "success", "message": "Endpoint funcionando"})

if __name__ == "__main__":
     from werkzeug.serving import run_simple
     run_simple("0.0.0.0", 5000, app)