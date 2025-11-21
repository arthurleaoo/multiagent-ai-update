from src.agents.base_agent import BaseAgent
from textwrap import dedent

class BackAgent(BaseAgent):
    def __init__(self):
        super().__init__("BackAgent", "Back-End Development")

    def generate_response(self, task: str, language: str) -> str:
        # 'task' pode incluir contexto do front_output.
        system = "You are a senior backend engineer. Return production-ready server code and a compact API contract."
        user = dedent(f"""{task}

        Output rules:
        - Respond ONLY with markdown code blocks; no prose outside code blocks.
        - Include runnable server code in {language} or a common stack (Node.js/Express, Python/FastAPI/Flask, Java/Spring, C#/.NET), with assumptions near the top as comments.
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
