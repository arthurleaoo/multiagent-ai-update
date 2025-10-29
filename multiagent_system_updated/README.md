# Multiagent System (Updated)
Projeto multiagente em Python (Front / Back / QA) que aceita a linguagem desejada via requisição.

## Recursos implementados
- Recebe `task` e `language` por POST `/generate`
- Orquestrador: Front -> Back -> QA (QA lê Front+Back antes de gerar testes)
- Persistência em SQLite (history)
- Prompts otimizados e consistentes
- Código pronto para rodar localmente

## Como rodar
1. Copie `.env.example` para `.env` e adicione sua OPENAI_API_KEY.
2. Crie e ative virtualenv.
3. `pip install -r requirements.txt`
4. `python main.py`
5. Teste:
   POST http://127.0.0.1:5000/generate
   Body JSON:
   {
     "task": "Crie uma tela de login com validação de email e senha.",
     "language": "Node.js"
   }
