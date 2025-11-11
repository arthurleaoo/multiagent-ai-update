# main.py (MODIFICADO para suportar orquestração dinâmica)

from flask import Flask, request, jsonify, send_file
from flask import send_from_directory
from dotenv import load_dotenv
import os
load_dotenv()

from src.core.orchestrator import Orchestrator, DB_PATH
from src.core.auth import hash_password, verify_password, create_token, verify_token
from src.core.packager import build_project_zip
import sqlite3

HOST = os.getenv("FLASK_HOST", "127.0.0.1")
PORT = int(os.getenv("FLASK_PORT", "5000"))
DEBUG = os.getenv("DEBUG", "False").lower() in ("1","true","yes")

app = Flask(__name__)
orch = None

def get_orch():
    global orch
    if orch is None:
        orch = Orchestrator()
    return orch
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", os.urandom(24).hex())


def get_bearer_user_id() -> int | None:
    # Prioridade: Header Authorization
    auth_header = request.headers.get("Authorization", "")
    # Compatibilidade: Query string (?authorization=Bearer <token> ou ?token=<token>)
    auth_query = request.args.get("authorization") or request.args.get("Authorization")
    token_query = request.args.get("token")

    def extract_token(value: str | None) -> str | None:
        if not value:
            return None
        v = value.strip()
        if v.lower().startswith("bearer "):
            return v.split(" ", 1)[1].strip()
        return v

    token = extract_token(auth_header) or extract_token(auth_query) or extract_token(token_query)
    if token:
        return verify_token(token)
    return None


@app.route("/auth/register", methods=["POST"])
def auth_register():
    data = request.get_json(force=True)
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    if not email or not password:
        return jsonify({"error": "Campos 'email' e 'password' são obrigatórios"}), 400
    if len(password) < 6:
        return jsonify({"error": "Senha deve conter pelo menos 6 caracteres"}), 400

    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.cursor()
        cur.execute("SELECT id FROM users WHERE email = ?", (email,))
        existing = cur.fetchone()
        if existing:
            return jsonify({"error": "Email já registrado"}), 409

        pwd_hash = hash_password(password)
        cur.execute(
            "INSERT INTO users (email, password_hash, created_at) VALUES (?, ?, datetime('now'))",
            (email, pwd_hash),
        )
        conn.commit()
        user_id = cur.lastrowid
        # Não retorna token no registro; exige login para obter token
        return jsonify({"id": user_id, "email": email}), 201
    finally:
        conn.close()


@app.route("/auth/login", methods=["POST"])
def auth_login():
    data = request.get_json(force=True)
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    if not email or not password:
        return jsonify({"error": "Campos 'email' e 'password' são obrigatórios"}), 400

    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.cursor()
        cur.execute("SELECT id, password_hash FROM users WHERE email = ?", (email,))
        row = cur.fetchone()
        if not row:
            return jsonify({"error": "Credenciais inválidas"}), 401
        user_id, pwd_hash = row
        if not verify_password(pwd_hash, password):
            return jsonify({"error": "Credenciais inválidas"}), 401
        token = create_token(user_id)
        return jsonify({"id": user_id, "email": email, "token": token}), 200
    finally:
        conn.close()


@app.route("/auth/me", methods=["GET"])
def auth_me():
    uid = get_bearer_user_id()
    if not uid:
        return jsonify({"error": "Não autenticado"}), 401
    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.cursor()
        cur.execute("SELECT id, email, created_at FROM users WHERE id = ?", (uid,))
        row = cur.fetchone()
        if not row:
            return jsonify({"error": "Usuário não encontrado"}), 404
        return jsonify({"id": row[0], "email": row[1], "created_at": row[2]}), 200
    finally:
        conn.close()

@app.route("/generate", methods=["POST"])
def generate():
    # Autenticação obrigatória
    uid = get_bearer_user_id()
    if not uid:
        return jsonify({"error": "Não autenticado"}), 401

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
        # Passa a lista de agentes e o user_id para o Orchestrator
        result = get_orch().run_all(task, language, agents_to_run, user_id=uid)
        return jsonify(result), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status":"ok"}), 200


@app.route("/")
def index_page():
    try:
        return send_file("static/index.html")
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/generate_zip", methods=["POST"])
def generate_zip():
    # Autenticação obrigatória
    uid = get_bearer_user_id()
    if not uid:
        return jsonify({"error": "Não autenticado"}), 401

    data = request.get_json(force=True)
    task = data.get("task")
    language = data.get("language", "Python")
    agents_to_run = data.get("agents", ["front", "back", "qa"])
    if not isinstance(agents_to_run, list):
        agents_to_run = ["front", "back", "qa"]

    if not task:
        return jsonify({"error":"Campo 'task' é obrigatório"}), 400
    try:
        result = get_orch().run_all(task, language, agents_to_run, user_id=uid)
        memzip = build_project_zip(task=result["task"], language=result["language"], front=result.get("front", ""), back=result.get("back", ""), qa=result.get("qa", ""))
        return send_file(memzip, mimetype="application/zip", as_attachment=True, download_name="projeto.zip")
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host=HOST, port=PORT, debug=DEBUG)
