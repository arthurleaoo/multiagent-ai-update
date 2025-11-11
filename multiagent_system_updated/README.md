# Multiagent System (Updated)
Projeto multiagente em Python (Front / Back / QA) que aceita a linguagem desejada via requisição.

## Recursos implementados
- Recebe `task` e `language` por POST `/generate`
- Orquestrador: Front -> Back -> QA (QA lê Front+Back antes de gerar testes)
- Persistência em SQLite (history)
- Prompts otimizados e consistentes
- Código pronto para rodar localmente
- Autenticação de usuário (registro, login, perfil) e proteção do `/generate`

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

## Autenticação

### Variáveis de ambiente
- `SECRET_KEY`: chave de assinatura dos tokens (obrigatória em produção). Caso ausente, uma chave efêmera é gerada em dev.
- `TOKEN_MAX_AGE` (opcional): tempo de validade do token em segundos (padrão 604800 = 7 dias).

### Registro
POST `http://127.0.0.1:5000/auth/register`
Body JSON:
```
{
  "email": "user@example.com",
  "password": "minha_senha_segura"
}
```
Resposta (201):
```
{
  "id": 1,
  "email": "user@example.com",
  "token": "<Bearer Token>"
}
```

### Login
POST `http://127.0.0.1:5000/auth/login`
Body JSON:
```
{
  "email": "user@example.com",
  "password": "minha_senha_segura"
}
```
Resposta (200):
```
{
  "id": 1,
  "email": "user@example.com",
  "token": "<Bearer Token>"
}
```

### Perfil
GET `http://127.0.0.1:5000/auth/me`
Header: `Authorization: Bearer <token>`
Ou via query string (compatibilidade): `?authorization=Bearer <token>` ou `?token=<token>`
Resposta (200):
```
{
  "id": 1,
  "email": "user@example.com",
  "created_at": "2025-01-01T00:00:00"
}
```

### Uso do `/generate` autenticado
POST `http://127.0.0.1:5000/generate`
Headers:
- `Authorization: Bearer <token>`
Ou via query string (compatibilidade): `?authorization=Bearer <token>` ou `?token=<token>`
Body JSON:
```
{
  "task": "Crie uma tela de login...",
  "language": "Python",
  "agents": ["front", "back", "qa"]
}
```
Observações:
- Sem o header `Authorization`, o endpoint retorna `401 Não autenticado`.
- As execuções geradas passam a ser associadas ao `user_id` quando disponível.
