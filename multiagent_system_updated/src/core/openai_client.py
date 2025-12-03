import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()


class OpenAIClient:
    def __init__(self, model: str = "gpt-4o-mini"):
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY não encontrado no .env")
        self.client = OpenAI(api_key=api_key)
        self.model = model

    def ask(self, system: str, user: str, max_tokens: int = 3500, temperature: float = 0.1) -> str:
        """
        Envia uma mensagem para a API da OpenAI (nova interface >= 1.0.0)
        com timeout estendido (180s) e maior limite de saída por padrão.
        """
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_completion_tokens=max_tokens,
            temperature=temperature,
            timeout=180  # Aumenta o limite para 3 minutos
        )

        return response.choices[0].message.content.strip()
