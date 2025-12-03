# src/core/orchestrator.py (MODIFICADO para ORQUESTRAÇÃO DINÂMICA, FEEDBACK e PT-BR)

import os
import sqlite3
from datetime import datetime
from src.agents.front_agent import FrontAgent
from src.agents.back_agent import BackAgent
from src.agents.qa_agent import QAAgent
from src.core.validation import (
    validate_contract_minimal,
    check_front_vs_contract,
    infer_contract_from_backend,
    try_load_contract_from_blocks,
)
from src.core.packager import _extract_code_blocks

DB_PATH = os.getenv("DATABASE_PATH", "./data/history.db")

def ensure_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Tabela base de histórico
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task TEXT NOT NULL,
            language TEXT,
            front_response TEXT,
            back_response TEXT,
            qa_response TEXT,
            created_at TEXT NOT NULL
        )
        """
    )

    # Tabela de usuários (autenticação)
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )

    # Nova tabela: histórico de prompts enviados aos agentes
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS history_prompts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            history_id INTEGER NOT NULL,
            agent TEXT NOT NULL,           -- 'front' | 'back' | 'qa'
            step TEXT,                     -- ex.: 'scaffold' | 'align' | 'generate'
            system_prompt TEXT NOT NULL,
            user_prompt TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(history_id) REFERENCES history(id)
        )
        """
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_history_prompts_history_id ON history_prompts(history_id)")

    # Nova tabela: tentativas de login (rate limiting / lockout)
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS login_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL,
            ip TEXT,
            attempts INTEGER NOT NULL DEFAULT 0,
            last_attempt_at TEXT,
            locked_until TEXT
        )
        """
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_login_attempts_email ON login_attempts(email)")

    # Migração leve: adiciona coluna user_id em history, se não existir
    try:
        cur.execute("PRAGMA table_info(history)")
        cols = [row[1] for row in cur.fetchall()]
        if "user_id" not in cols:
            cur.execute("ALTER TABLE history ADD COLUMN user_id INTEGER")
    except Exception as e:
        print(f"[DB] Aviso: não foi possível verificar/adicionar coluna user_id: {e}")

    # Aplica schema estendido de apoio (índices, views, triggers, etc.)
    try:
        schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")
        if os.path.exists(schema_path):
            with open(schema_path, "r", encoding="utf-8") as f:
                sql = f.read()
            cur.executescript(sql)
    except Exception as e:
        # Não interrompe a inicialização se houver falha ao aplicar o schema
        print(f"[DB] Aviso: falha ao aplicar schema.sql: {e}")

    conn.commit()
    conn.close()

class Orchestrator:
    def __init__(self):
        ensure_db()
        self.front = FrontAgent()
        self.back = BackAgent()
        self.qa = QAAgent()

    # 💡 MODIFICAÇÃO CHAVE: Adiciona 'agents_to_run'
    def run_all(self, task: str, language: str = "Python", agents_to_run: list = ["front", "back", "qa"], user_id: int | None = None) -> dict:
        
        # Inicializa todas as saídas como vazias
        front_out = ""
        front_out_initial = ""
        front_out_final = ""
        back_out = ""
        qa_out = ""

        # Inicializa prompts (para logging)
        front_system = "You are a senior front-end engineer. Return only code files with clean structure and API integration."
        back_system = "You are a senior backend engineer. Return production-ready server code and a compact API contract."
        qa_system = "You are an experienced QA engineer. Return tests that validate backend contract and frontend integration."
        front_prompt = ""
        front_align_prompt = ""
        back_prompt_context = ""
        qa_prompt_context = ""

        #Base da instrução de idioma para todos os agentes
        lang_instruction = "Sua resposta, incluindo todas as explicações, introduções e resumos, deve ser escrita em Português (pt-BR). Apenas o código gerado pode manter as convenções de variáveis da linguagem (geralmente inglês)."
        
        # 1) Front (Passo 1): gera estrutura básica e UI
        if "front" in agents_to_run:
            print(">>> 🖥️ FRONT-END AGENT: Ativado e gerando interface (HTML/CSS/JS)...") # NOVO
            
            front_prompt = (
                f"{lang_instruction}\n"
                f"Task: {task}\nLanguage: {language}\n\n"
                "Fase 1 (Scaffold): gere uma estrutura mínima e funcional de frontend em três arquivos "
                "(`frontend/index.html`, `frontend/styles.css`, `frontend/script.js`) com fetchs parametrizados por `API_BASE`. "
                "Responda APENAS com blocos de código rotulados com nomes de arquivo."
            )

            front_out_initial = self.front.generate_response(front_prompt, language)
            front_out = front_out_initial
            print(">>> 🖥️ FRONT-END AGENT: Concluído.") # NOVO

        # 2) Back: gera API/negócio + contrato
        if "back" in agents_to_run:
            print(">>> ⚙️ BACK-END AGENT: Ativado e gerando lógica da API...") # NOVO
            
            # O prompt de contexto usa 'front_out' se ele tiver sido gerado, caso contrário usa ""
            # NOVO: Adiciona instrução de idioma ao prompt
            back_prompt_context = (
                f"{lang_instruction}\n"
                f"Task: {task}\nLanguage: {language}\nFront output (for context):\n{front_out}\n\n"
                f"Forneça a implementação de backend em {language} e inclua um arquivo JSON `api_contract.json` "
                "descrevendo rotas, métodos, payloads e exemplos de resposta conforme as regras de contrato. "
                "Responda somente com blocos de código."
            )
            
            back_out = self.back.generate_response(back_prompt_context, language)
            print(">>> ⚙️ BACK-END AGENT: Concluído.") # NOVO

        # 2.5) Front (Passo 2): realinha integração com contrato do back
        if "front" in agents_to_run and "back" in agents_to_run:
            print(">>> 🔁 FRONT-END AGENT (alinhamento): Integrando exatamente com o contrato da API...")
            front_align_prompt = (
                f"{lang_instruction}\n"
                f"Task: {task}\nLanguage: {language}\n\n"
                "Fase 2 (Integração): com base na saída do backend abaixo (inclui `api_contract.json`), "
                "atualize `frontend/script.js` para consumir exatamente as rotas, métodos, JSON e headers. "
                "Se necessário, ajuste `index.html` para exibir resultados das chamadas. "
                "Responda APENAS com os mesmos três arquivos do frontend, integrados ao contrato.\n\n"
                f"BACK OUTPUT:\n{back_out}"
            )
            front_out_final = self.front.generate_response(front_align_prompt, language)
            front_out = front_out_final or front_out_initial
            print(">>> 🔁 FRONT-END AGENT (alinhamento): Concluído.")

        # 3) QA: revisa outputs finais
        if "qa" in agents_to_run:
            print(">>> 🧪 QA AGENT: Ativado e gerando testes e critérios de qualidade...") # NOVO
            
            # NOVO: Adiciona instrução de idioma ao prompt
            qa_prompt_context = (
                f"{lang_instruction}\nTask: {task}\nLanguage: {language}\n"
                f"Front output (final):\n{front_out}\n\nBack output:\n{back_out}\n\n"
                "Como engenheiro de QA, gere: 1) Casos de teste manuais, 2) Testes automatizados para backend/contract, 3) Smoke tests de integração do frontend, e 4) Checklist de riscos. Inclua comandos exatos (curl/pytest/jest)."
            )
            
            qa_out = self.qa.generate_response(qa_prompt_context, language)
            print(">>> 🧪 QA AGENT: Concluído.") # NOVO

        # persist + logging de prompts
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        try:
            # Persiste todas as saídas, incluindo associação opcional ao usuário
            cur.execute("PRAGMA table_info(history)")
            cols = [row[1] for row in cur.fetchall()]
            created_at = datetime.utcnow().isoformat()
            if "user_id" in cols:
                cur.execute(
                    "INSERT INTO history (task, language, front_response, back_response, qa_response, created_at, user_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (task, language, front_out, back_out, qa_out, created_at, user_id)
                )
            else:
                cur.execute(
                    "INSERT INTO history (task, language, front_response, back_response, qa_response, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (task, language, front_out, back_out, qa_out, created_at)
                )
            history_id = cur.lastrowid

            # Insere prompts por agente/etapa (somente os que foram executados)
            def insert_prompt(agent: str, step: str, system_prompt: str, user_prompt: str):
                if not user_prompt:
                    return
                cur.execute(
                    "INSERT INTO history_prompts (history_id, agent, step, system_prompt, user_prompt, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (history_id, agent, step, system_prompt, user_prompt, created_at)
                )

            if "front" in agents_to_run and front_prompt:
                insert_prompt("front", "scaffold", front_system, front_prompt)
            if "back" in agents_to_run and back_prompt_context:
                insert_prompt("back", "generate", back_system, back_prompt_context)
            if "front" in agents_to_run and front_align_prompt:
                insert_prompt("front", "align", front_system, front_align_prompt)
            if "qa" in agents_to_run and qa_prompt_context:
                insert_prompt("qa", "generate", qa_system, qa_prompt_context)

            conn.commit()
        finally:
            conn.close()
        
        print(f"\n✅ ORQUESTRADOR: Tarefa '{task}' finalizada com sucesso. Retornando resposta ao cliente.") # NOVO
        # 🔎 Validação de contrato e integração front/back
        back_blocks = _extract_code_blocks(back_out or "")
        qa_blocks = _extract_code_blocks(qa_out or "")
        contract = try_load_contract_from_blocks(back_blocks) or try_load_contract_from_blocks(qa_blocks)
        if not contract:
            contract = infer_contract_from_backend(back_out or "")
        ok_contract, err_contract = validate_contract_minimal(contract or {})

        # Monta mapa de arquivos do frontend para inspeção
        front_blocks = _extract_code_blocks(front_out or "")
        front_files: dict[str, str] = {}
        for b in front_blocks:
            lang = (b.get("language") or "").lower()
            fn = b.get("filename") or ""
            content = b.get("content") or ""
            if lang in ("javascript", "js", "typescript", "ts"):
                path = fn or ("frontend/script.js" if lang in ("javascript", "js") else "frontend/script.ts")
                front_files[path] = content
        if not front_files and (front_out or "").strip():
            front_files["frontend/script.js"] = front_out

        ok_integration, err_integration = check_front_vs_contract(front_files, contract or {})

        return {
            "task": task,
            "language": language,
            "front": front_out,
            "back": back_out,
            "qa": qa_out,
            "contract": contract,
            "validation": {
                "contract_ok": ok_contract,
                "contract_error": err_contract,
                "integration_ok": ok_integration,
                "integration_error": err_integration,
            },
        }
