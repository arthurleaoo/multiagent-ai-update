# src/core/orchestrator.py (MODIFICADO para ORQUESTRAÇÃO DINÂMICA, FEEDBACK e PT-BR)

import os
import sqlite3
from datetime import datetime
from src.agents.front_agent import FrontAgent
from src.agents.back_agent import BackAgent
from src.agents.qa_agent import QAAgent

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
        back_out = ""
        qa_out = ""

        #Base da instrução de idioma para todos os agentes
        lang_instruction = "Sua resposta, incluindo todas as explicações, introduções e resumos, deve ser escrita em Português (pt-BR). Apenas o código gerado pode manter as convenções de variáveis da linguagem (geralmente inglês)."
        
        # 1) Front generates UI (Executa se 'front' estiver na lista)
        if "front" in agents_to_run:
            print(">>> 🖥️ FRONT-END AGENT: Ativado e gerando interface (HTML/CSS/JS)...") # NOVO
            
            front_prompt = f"{lang_instruction}\nTask: {task}\nLanguage: {language}\n\nPlease provide the front-end implementation (HTML, CSS, and JavaScript) in three separate code blocks. Focus on clean code suitable to be used as implementation snippets."
            
            front_out = self.front.generate_response(front_prompt, language)
            print(">>> 🖥️ FRONT-END AGENT: Concluído.") # NOVO

        # 2) Back generates API/logic (Executa se 'back' estiver na lista)
        if "back" in agents_to_run:
            print(">>> ⚙️ BACK-END AGENT: Ativado e gerando lógica da API...") # NOVO
            
            # O prompt de contexto usa 'front_out' se ele tiver sido gerado, caso contrário usa ""
            # NOVO: Adiciona instrução de idioma ao prompt
            back_prompt_context = f"{lang_instruction}\nTask: {task}\nLanguage: {language}\nFront output (for context):\n{front_out}\n\nPlease provide a backend implementation (code + explanation of routes, payloads and validation) in {language}. Respond only with code blocks and short comments suitable to be used as implementation snippets."
            
            back_out = self.back.generate_response(back_prompt_context, language)
            print(">>> ⚙️ BACK-END AGENT: Concluído.") # NOVO

        # 3) QA reviews both outputs (Executa se 'qa' estiver na lista)
        if "qa" in agents_to_run:
            print(">>> 🧪 QA AGENT: Ativado e gerando testes e critérios de qualidade...") # NOVO
            
            # NOVO: Adiciona instrução de idioma ao prompt
            qa_prompt_context = f"{lang_instruction}\nTask: {task}\nLanguage: {language}\nFront output:\n{front_out}\n\nBack output:\n{back_out}\n\nComo engenheiro de QA, gere: 1) Casos de teste manuais (passos + resultados esperados), 2) Exemplos de testes automatizados para a linguagem escolhida (se aplicável), e 3) Um checklist de pontos de integração e riscos potenciais. Seja explícito sobre quais comandos rodar para executar os testes."
            
            qa_out = self.qa.generate_response(qa_prompt_context, language)
            print(">>> 🧪 QA AGENT: Concluído.") # NOVO

        # persist
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        # Persiste todas as saídas, incluindo associação opcional ao usuário
        # Detecta dinamicamente se a coluna user_id existe
        try:
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
            conn.commit()
        finally:
            conn.close()
        
        print(f"\n✅ ORQUESTRADOR: Tarefa '{task}' finalizada com sucesso. Retornando resposta ao cliente.") # NOVO

        return {
            "task": task,
            "language": language,
            "front": front_out,
            "back": back_out,
            "qa": qa_out
        }