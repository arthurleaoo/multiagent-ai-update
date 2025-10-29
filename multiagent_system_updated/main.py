# main.py (MODIFICADO para suportar orquestração dinâmica)

from flask import Flask, request, jsonify
from dotenv import load_dotenv
import os
load_dotenv()

from src.core.orchestrator import Orchestrator

HOST = os.getenv("FLASK_HOST", "127.0.0.1")
PORT = int(os.getenv("FLASK_PORT", "5000"))
DEBUG = os.getenv("DEBUG", "False").lower() in ("1","true","yes")

app = Flask(__name__)
orch = Orchestrator()

@app.route("/generate", methods=["POST"])
def generate():
    data = request.get_json(force=True)
    task = data.get("task")
    language = data.get("language", "Python")
    
    # 💡 MODIFICAÇÃO CHAVE: Pega a lista de agentes. O padrão é ["front", "back", "qa"]
    # Garante que seja uma lista, mesmo que o usuário passe uma string ou um valor nulo
    agents_to_run = data.get("agents", ["front", "back", "qa"])
    if not isinstance(agents_to_run, list):
        agents_to_run = ["front", "back", "qa"]

    if not task:
        return jsonify({"error":"Campo 'task' é obrigatório"}), 400
    try:
        # Passa a lista de agentes para o Orchestrator
        result = orch.run_all(task, language, agents_to_run)
        return jsonify(result), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status":"ok"}), 200

if __name__ == "__main__":
    app.run(host=HOST, port=PORT, debug=DEBUG)
