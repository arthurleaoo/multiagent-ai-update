from src.agents.base_agent import BaseAgent
from textwrap import dedent

class FrontAgent(BaseAgent):
    def __init__(self):
        super().__init__("FrontAgent", "Front-End Development")

    def generate_response(self, task: str, language: str) -> str:
        system = "You are a senior front-end engineer. Return only code files with clean structure and robust API integration."
        user = dedent(f"""Project task: {task}

        Output rules:
        - Respond ONLY with markdown code blocks labeled with filenames.
        - Emit a minimal, runnable front in a clean structure:
          - `frontend/index.html`
          - `frontend/styles.css`
          - `frontend/script.js`
        - In `script.js`, implement an API client using `const API_BASE = window.API_BASE_URL || '/api';` and real `fetch` calls.
        - Handle responses defensively:
          - Check `response.ok` and `Content-Type` header starts with `application/json` before calling `response.json()`.
          - If not JSON, fallback to `response.text()` and show a user-friendly message.
        - If an API contract is present in the task, integrate endpoints exactly (URL, method, body, headers).
        - Keep comments concise; no prose outside code blocks.
        """)
        return self.client.ask(system, user, max_tokens=3000)
