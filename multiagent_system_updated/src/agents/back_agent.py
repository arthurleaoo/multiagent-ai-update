from src.agents.base_agent import BaseAgent
from textwrap import dedent

class BackAgent(BaseAgent):
    def __init__(self):
        super().__init__("BackAgent", "Back-End Development")

    def generate_response(self, task: str, language: str) -> str:
        # 'task' pode incluir contexto do front_output.
        system = "You are a senior backend engineer. Return production-ready server code and a compact API contract. Ensure a single server entrypoint and consistent API base."
        user = dedent(f"""{task}

        Output rules:
        - Respond ONLY with markdown code blocks; no prose outside code blocks.
        - Include runnable server code in {language} or a common stack (Node.js/Express, Python/FastAPI/Flask, Java/Spring, C#/.NET), with assumptions near the top as comments.
        - SINGLE SERVER: Do NOT create more than one server/app/process. If Python/Flask, use ONE app instance and ONE entrypoint.
        - Python/Flask specifics (when applicable):
          - Use a single entrypoint with filenames: `backend/app/__init__.py` (app factory optional) and `backend/app/main.py` (routes).
          - All endpoints under a base `API_BASE = '/api'` (e.g., `/api/health`, `/api/login`).
          - Do NOT create additional files like `server.py` starting another Flask app. No second `app = Flask(__name__)` and no extra `app.run()`.
          - Return JSON with `flask.jsonify(...)` and proper error handling.
        - After code, include a single JSON file named `api_contract.json` describing endpoints, methods, request/response shapes, auth requirements, and example curl.
        - Label the JSON block as a file with a filename hint so tooling can place it under `docs/api_contract.json`.

        API_CONTRACT fields (example):
        {{
          "base_url": "/api",
          "endpoints": [
            {{"path": "/items", "method": "GET", "query": {{"q": "string?"}}, "response": {{"items": [{{"id": "int", "name": "string"}}]}}}},
            {{"path": "/items", "method": "POST", "body": {{"name": "string"}}, "response": {{"id": "int", "name": "string"}}}}
          ],
          "auth": {{"type": "bearer", "header": "Authorization: Bearer <token>"}},
          "examples": [
            "curl -X GET $API/items",
            "curl -X POST $API/items -H 'Content-Type: application/json' -d '{{\"name\":\"foo\"}}'"
          ]
        }}
        """)
        return self.client.ask(system, user, max_tokens=3600)
