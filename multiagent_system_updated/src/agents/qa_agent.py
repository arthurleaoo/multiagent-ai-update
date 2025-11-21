from src.agents.base_agent import BaseAgent
from textwrap import dedent

class QAAgent(BaseAgent):
    def __init__(self):
        super().__init__("QAAgent", "Quality Assurance and Testing")

    def generate_response(self, task: str, language: str) -> str:
        system = "You are an experienced QA engineer. Return tests that validate backend contract and frontend integration."
        user = dedent(f"""{task}

        Output rules:
        - Respond ONLY with code blocks and command snippets; no prose outside code blocks.
        - Provide manual test cases (steps + expected results) in a `qa/TEST_PLAN.md` block.
        - Provide automated tests for backend (e.g., `qa/backend_test.py` with pytest or `qa/backend.test.js` with jest) hitting the real endpoints per contract.
        - Provide smoke tests for frontend integration (commands or minimal tests) ensuring fetches call the correct URLs, methods, headers.
        - Include example `curl` commands that must succeed against the generated backend.
        """)
        return self.client.ask(system, user, max_tokens=1800)
