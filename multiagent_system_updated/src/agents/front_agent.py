from src.agents.base_agent import BaseAgent
from textwrap import dedent

class FrontAgent(BaseAgent):
    def __init__(self):
        super().__init__("FrontAgent", "Front-End Development")

    def generate_response(self, task: str, language: str) -> str:
        system = "You are a senior front-end engineer. Provide production-ready UI snippets and integration notes."
        user = dedent(f"""Project task: {task}

        Constraints:
        - Target integration language for backend: {language}
        - Provide 3 files separated and labeled: index.html, styles.css, script.js (if applicable). Wrap each file in a Markdown code block with filename comment.
        - Indicate expected backend endpoints and payloads (URL, method, JSON shape).
        - Keep code minimal, copy-pastable and well-commented.
        """)
        return self.client.ask(system, user, max_tokens=1200)
