from abc import ABC, abstractmethod
from src.core.openai_client import OpenAIClient

class BaseAgent(ABC):
    def __init__(self, name: str, specialty: str):
        self.name = name
        self.specialty = specialty
        self.client = OpenAIClient()

    @abstractmethod
    def generate_response(self, task: str, language: str) -> str:
        raise NotImplementedError
