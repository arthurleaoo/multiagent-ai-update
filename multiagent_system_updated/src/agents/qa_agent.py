from src.agents.base_agent import BaseAgent
from textwrap import dedent

class QAAgent(BaseAgent):
    def __init__(self):
        super().__init__("QAAgent", "Quality Assurance and Testing")

    def generate_response(self, task: str, language: str) -> str:
        system = "You are an experienced QA engineer. Produce manual and automated tests and a risk checklist."
        user = dedent(f"""{task}

        Requirements:
        - Provide a set of manual test cases with steps and expected results.
        - Provide one or more automated test examples (use pytest for Python, jest/mocha for Node.js, or describe commands for other languages).
        - Provide CI suggestions and acceptance criteria.
        """)
        return self.client.ask(system, user, max_tokens=1200)
