from src.agents.base_agent import BaseAgent
from textwrap import dedent

class BackAgent(BaseAgent):
    def __init__(self):
        super().__init__("BackAgent", "Back-End Development")

    def generate_response(self, task: str, language: str) -> str:
        # Here 'task' may already include front_output context when called by orchestrator
        system = "You are a senior backend engineer. Provide clear, runnable server-side code and examples."
        user = dedent(f"""{task}

        Requirements:
        - Implement routes/APIs required by the UI.
        - Provide data models (if applicable), validation rules, and example requests/responses.
        - If {language.lower()} is not idiomatic for server code, prefer a common server stack (e.g., Node.js -> Express, Java -> Spring Boot, C# -> .NET). State assumptions.
        - Provide curl/Postman examples to test endpoints.
        """)
        return self.client.ask(system, user, max_tokens=1400)
