# src/core/orchestrator.py (MODIFICADO para orquestração dinâmica)

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
    cur.execute("""CREATE TABLE IF NOT EXISTS history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task TEXT NOT NULL,
        language TEXT,
        front_response TEXT,
        back_response TEXT,
        qa_response TEXT,
        created_at TEXT NOT NULL
    )""")
    conn.commit()
    conn.close()

class Orchestrator:
    def __init__(self):
        ensure_db()
        self.front = FrontAgent()
        self.back = BackAgent()
        self.qa = QAAgent()

    # 💡 MODIFICAÇÃO CHAVE: Adiciona 'agents_to_run'
    def run_all(self, task: str, language: str = "Python", agents_to_run: list = ["front", "back", "qa"]) -> dict:
        
        # Inicializa todas as saídas como vazias
        front_out = ""
        back_out = ""
        qa_out = ""

        # 1) Front generates UI (Executa se 'front' estiver na lista)
        if "front" in agents_to_run:
            front_out = self.front.generate_response(task, language)

        # 2) Back generates API/logic (Executa se 'back' estiver na lista)
        if "back" in agents_to_run:
            # O prompt de contexto usa 'front_out' se ele tiver sido gerado, caso contrário usa ""
            back_prompt_context = f"Task: {task}\nLanguage: {language}\nFront output (for context):\n{front_out}\n\nPlease provide a backend implementation (code + explanation of routes, payloads and validation) in {language}. Respond only with code blocks and short comments suitable to be used as implementation snippets."
            back_out = self.back.generate_response(back_prompt_context, language)

        # 3) QA reviews both outputs (Executa se 'qa' estiver na lista)
        if "qa" in agents_to_run:
            qa_prompt_context = f"Task: {task}\nLanguage: {language}\nFront output:\n{front_out}\n\nBack output:\n{back_out}\n\nAs a QA engineer, generate: 1) manual test cases (steps + expected results), 2) automated test examples for the chosen language (if applicable), 3) a checklist of integration points and potential risks. Be explicit about which commands to run to execute tests."
            qa_out = self.qa.generate_response(qa_prompt_context, language)

        # persist
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        # Persiste todas as saídas, mesmo as que estão vazias
        cur.execute("INSERT INTO history (task, language, front_response, back_response, qa_response, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (task, language, front_out, back_out, qa_out, datetime.utcnow().isoformat()))
        conn.commit()
        conn.close()

        return {
            "task": task,
            "language": language,
            "front": front_out,
            "back": back_out,
            "qa": qa_out
        }