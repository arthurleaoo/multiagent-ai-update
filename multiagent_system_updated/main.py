# main.py (MODIFICADO para suportar orquestração dinâmica)

from flask import Flask, request, jsonify, send_file
from dotenv import load_dotenv
import os
load_dotenv()
from datetime import datetime, timedelta

from src.core.orchestrator import Orchestrator, DB_PATH, ensure_db
from src.core.auth import hash_password, verify_password, create_token, verify_token
from src.core.auth import validate_password_strength
from src.core.packager import build_project_zip, build_structured_zip
import sqlite3

HOST = os.getenv("FLASK_HOST", "127.0.0.1")
PORT = int(os.getenv("FLASK_PORT", "5000"))
DEBUG = os.getenv("DEBUG", "False").lower() in ("1","true","yes")

import os
app = Flask(__name__)
orch = None

def get_orch():
    global orch
    if orch is None:
        orch = Orchestrator()
    return orch
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", os.urandom(24).hex())

# Inicializa o schema do banco na subida da aplicação (garante tabelas para /auth/*)
ensure_db()


def get_client_ip() -> str:
    # Suporta proxies simples: pega primeiro IP do X-Forwarded-For ou remote_addr
    xff = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
    return xff or request.remote_addr or "unknown"


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
        # Rate limiting / lockout simples por email
        # Bloqueia caso exista locked_until > agora
        cur.execute("SELECT locked_until, attempts, last_attempt_at FROM login_attempts WHERE email = ?", (email,))
        la = cur.fetchone()
        now_iso = datetime.utcnow().isoformat()
        if la and la[0]:
            locked_until = la[0]
            if locked_until and locked_until > now_iso:
                return jsonify({"error": "Conta temporariamente bloqueada por tentativas de login. Tente novamente mais tarde."}), 429

        cur.execute("SELECT id, password_hash FROM users WHERE email = ?", (email,))
        row = cur.fetchone()
        if not row:
            # Registra tentativa falha
            ip = get_client_ip()
            _register_failed_attempt(cur, email, ip)
            conn.commit()
            return jsonify({"error": "Credenciais inválidas"}), 401
        user_id, pwd_hash = row
        if not verify_password(pwd_hash, password):
            ip = get_client_ip()
            _register_failed_attempt(cur, email, ip)
            conn.commit()
            return jsonify({"error": "Credenciais inválidas"}), 401
        # Sucesso: reseta tentativas
        cur.execute("UPDATE login_attempts SET attempts = 0, locked_until = NULL, last_attempt_at = ? WHERE email = ?", (now_iso, email))
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


# Helpers de rate limiting
LOCK_THRESHOLD = int(os.getenv("LOGIN_LOCK_THRESHOLD", "5"))           # falhas antes de bloquear
LOCK_WINDOW_MINUTES = int(os.getenv("LOGIN_LOCK_WINDOW_MINUTES", "15")) # janela de contagem
LOCK_DURATION_MINUTES = int(os.getenv("LOGIN_LOCK_DURATION_MINUTES", "15"))


def _register_failed_attempt(cur: sqlite3.Cursor, email: str, ip: str) -> None:
    cur.execute("SELECT id, attempts, last_attempt_at FROM login_attempts WHERE email = ?", (email,))
    row = cur.fetchone()
    now = datetime.utcnow()
    now_iso = now.isoformat()
    window_delta = LOCK_WINDOW_MINUTES
    if not row:
        cur.execute("INSERT INTO login_attempts (email, ip, attempts, last_attempt_at) VALUES (?, ?, ?, ?)", (email, ip, 1, now_iso))
        return
    la_id, attempts, last_attempt_at = row
    try:
        last_dt = datetime.fromisoformat(last_attempt_at) if last_attempt_at else None
    except Exception:
        last_dt = None
    if last_dt and (now - last_dt).total_seconds() <= window_delta * 60:
        attempts += 1
    else:
        attempts = 1
    locked_until_iso = None
    if attempts >= LOCK_THRESHOLD:
        locked_until = now + timedelta(minutes=LOCK_DURATION_MINUTES)
        locked_until_iso = locked_until.isoformat()
    cur.execute(
        "UPDATE login_attempts SET ip = ?, attempts = ?, last_attempt_at = ?, locked_until = ? WHERE id = ?",
        (ip, attempts, now_iso, locked_until_iso, la_id)
    )

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
    preset = data.get("preset")  # opcional: flask|express|spring
    project_name = data.get("project_name", "projeto")
    group_id = data.get("group_id", "com.example.demo")

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
        return send_file(os.path.join(os.path.dirname(__file__), "static", "index.html"))
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/index.html")
def index_html():
    try:
        return send_file(os.path.join(os.path.dirname(__file__), "static", "index.html"))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/generate_zip", methods=["POST"])
@app.route("/generate_zip/", methods=["POST"])  # aceita barra final
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
    # NOVO: parâmetros para projeto estruturado
    preset = data.get("preset")  # opcional: flask|express|spring
    project_name = data.get("project_name", "projeto")
    group_id = data.get("group_id", "com.example.demo")

    if not task:
        return jsonify({"error":"Campo 'task' é obrigatório"}), 400
    try:
        result = get_orch().run_all(task, language, agents_to_run, user_id=uid)
        if preset:
            memzip = build_structured_zip(
                task=result["task"], language=result["language"],
                front=result.get("front", ""), back=result.get("back", ""), qa=result.get("qa", ""),
                preset=preset, project_name=project_name, group_id=group_id
            )
        else:
            memzip = build_project_zip(
                task=result["task"], language=result["language"],
                front=result.get("front", ""), back=result.get("back", ""), qa=result.get("qa", "")
            )
        return send_file(memzip, mimetype="application/zip", as_attachment=True, download_name="projeto.zip")
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host=HOST, port=PORT, debug=DEBUG)
