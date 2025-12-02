# main.py (MODIFICADO para suportar orquestração dinâmica + CORS FULL)

from flask import Flask, request, jsonify, send_file
from dotenv import load_dotenv
import os
load_dotenv()
from datetime import datetime, timedelta
import sqlite3

from src.core.orchestrator import Orchestrator, DB_PATH, ensure_db
from src.core.auth import (
    hash_password, verify_password, create_token, verify_token,
    validate_password_strength, create_reset_token, verify_reset_token, send_reset_email
)
from src.core.packager import build_project_zip, build_structured_zip

from flask_cors import CORS   # ✅ IMPORTANTE

HOST = os.getenv("FLASK_HOST", "127.0.0.1")
PORT = int(os.getenv("FLASK_PORT", "5000"))
DEBUG = os.getenv("DEBUG", "False").lower() in ("1", "true", "yes")

app = Flask(__name__)
orch = None

# ============================
# 🔥 CORS TOTALMENTE CONFIGURADO
# ============================

CORS(
    app,
    origins=["*"],
    allow_headers=["Authorization", "Content-Type"],
    expose_headers=["Content-Disposition"],
    supports_credentials=True,
    methods=["GET", "POST", "OPTIONS"],
    max_age=86400
)

# ===============================

def get_orch():
    global orch
    if orch is None:
        orch = Orchestrator()
    return orch

app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", os.urandom(24).hex())

ensure_db()


def get_client_ip() -> str:
    xff = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
    return xff or request.remote_addr or "unknown"


def get_bearer_user_id() -> int | None:
    auth_header = request.headers.get("Authorization", "")
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

    ok, msg = validate_password_strength(password)
    if not ok:
        return jsonify({"error": msg}), 400

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
        return jsonify({"id": cur.lastrowid, "email": email}), 201
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
        if not row or not verify_password(row[1], password):
            return jsonify({"error": "Credenciais inválidas"}), 401

        token = create_token(row[0])
        return jsonify({"id": row[0], "email": email, "token": token}), 200
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


@app.route("/auth/request_password_reset", methods=["POST"])
def auth_request_password_reset():
    data = request.get_json(force=True)
    email = (data.get("email") or "").strip().lower()
    if not email:
        return jsonify({"error": "Campo 'email' é obrigatório"}), 400

    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.cursor()
        cur.execute("SELECT id FROM users WHERE email = ?", (email,))
        row = cur.fetchone()
        if not row:
            return jsonify({"message": "Se existir, enviaremos instruções", "reset_token": None}), 200
        token = create_reset_token(int(row[0]))
        sent = send_reset_email(email, token)
        payload = {"message": "Token de reset gerado", "reset_token": token}
        if sent and not DEBUG:
            payload["reset_token"] = None
            payload["message"] = "Instruções enviadas por email"
        return jsonify(payload), 200
    finally:
        conn.close()


@app.route("/auth/reset_password", methods=["POST"])
def auth_reset_password():
    data = request.get_json(force=True)
    token = data.get("token") or ""
    new_password = data.get("new_password") or ""
    if not token or not new_password:
        return jsonify({"error": "Campos 'token' e 'new_password' são obrigatórios"}), 400

    ok, msg = validate_password_strength(new_password)
    if not ok:
        return jsonify({"error": msg}), 400

    uid = verify_reset_token(token)
    if not uid:
        return jsonify({"error": "Token inválido ou expirado"}), 400

    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.cursor()
        cur.execute("SELECT id FROM users WHERE id = ?", (uid,))
        row = cur.fetchone()
        if not row:
            return jsonify({"error": "Usuário não encontrado"}), 404
        pwd_hash = hash_password(new_password)
        cur.execute("UPDATE users SET password_hash = ? WHERE id = ?", (pwd_hash, uid))
        conn.commit()
        return jsonify({"message": "Senha atualizada"}), 200
    finally:
        conn.close()


@app.route("/auth/update_password", methods=["PUT"])
def auth_update_password():
    uid = get_bearer_user_id()
    if not uid:
        return jsonify({"error": "Não autenticado"}), 401
    data = request.get_json(force=True)
    old_password = data.get("old_password") or ""
    new_password = data.get("new_password") or ""
    if not old_password or not new_password:
        return jsonify({"error": "Campos 'old_password' e 'new_password' são obrigatórios"}), 400

    ok, msg = validate_password_strength(new_password)
    if not ok:
        return jsonify({"error": msg}), 400

    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.cursor()
        cur.execute("SELECT password_hash FROM users WHERE id = ?", (uid,))
        row = cur.fetchone()
        if not row or not verify_password(row[0], old_password):
            return jsonify({"error": "Senha atual incorreta"}), 401
        pwd_hash = hash_password(new_password)
        cur.execute("UPDATE users SET password_hash = ? WHERE id = ?", (pwd_hash, uid))
        conn.commit()
        return jsonify({"message": "Senha atualizada"}), 200
    finally:
        conn.close()


@app.route("/auth/delete_account", methods=["DELETE"])
def auth_delete_account():
    uid = get_bearer_user_id()
    if not uid:
        return jsonify({"error": "Não autenticado"}), 401
    data = request.get_json(force=True)
    password = data.get("password") or ""
    if not password:
        return jsonify({"error": "Campo 'password' é obrigatório"}), 400

    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.cursor()
        cur.execute("SELECT password_hash FROM users WHERE id = ?", (uid,))
        row = cur.fetchone()
        if not row or not verify_password(row[0], password):
            return jsonify({"error": "Senha inválida"}), 401
        cur.execute("DELETE FROM users WHERE id = ?", (uid,))
        conn.commit()
        return "", 204
    finally:
        conn.close()


# =====================================================
# 🔥 /generate — agora com CORS e OPTIONS funcionando
# =====================================================
@app.route("/generate", methods=["POST", "OPTIONS"])
def generate():
    if request.method == "OPTIONS":
        return "", 204   # Preflight OK

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
        return jsonify({"error": "Campo 'task' é obrigatório"}), 400

    try:
        result = get_orch().run_all(task, language, agents_to_run, user_id=uid)
        return jsonify(result), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200


@app.route("/")
def index_page():
    try:
        return send_file(os.path.join(os.path.dirname(__file__), "static", "index.html"))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/index.html")
def index_html():
    try:
        return send_file(os.path.join(os.path.dirname(__file__), "static", "index.html"))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# =====================================================
# 🔥 /generate_zip — agora com CORS + OPTIONS
# =====================================================
@app.route("/generate_zip", methods=["POST", "OPTIONS"])
@app.route("/generate_zip/", methods=["POST", "OPTIONS"])
def generate_zip():
    if request.method == "OPTIONS":
        return "", 204   # Preflight OK

    uid = get_bearer_user_id()
    if not uid:
        return jsonify({"error": "Não autenticado"}), 401

    data = request.get_json(force=True)
    task = data.get("task")
    language = data.get("language", "Python")
    agents_to_run = data.get("agents", ["front", "back", "qa"])
    if not isinstance(agents_to_run, list):
        agents_to_run = ["front", "back", "qa"]

    preset = data.get("preset")
    project_name = data.get("project_name", "projeto")
    group_id = data.get("group_id", "com.example.demo")

    if not task:
        return jsonify({"error": "Campo 'task' é obrigatório"}), 400

    try:
        result = get_orch().run_all(task, language, agents_to_run, user_id=uid)

        if preset:
            memzip = build_structured_zip(
                task=result["task"],
                language=result["language"],
                front=result.get("front", ""),
                back=result.get("back", ""),
                qa=result.get("qa", ""),
                preset=preset,
                project_name=project_name,
                group_id=group_id
            )
        else:
            memzip = build_project_zip(
                task=result["task"],
                language=result["language"],
                front=result.get("front", ""),
                back=result.get("back", ""),
                qa=result.get("qa", "")
            )

        return send_file(memzip, mimetype="application/zip", as_attachment=True, download_name="projeto.zip")

    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(host=HOST, port=PORT, debug=DEBUG)
