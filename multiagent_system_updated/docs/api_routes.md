# API Routes e Payloads

Base URL: `http://<FLASK_HOST>:<FLASK_PORT>` (padrões `127.0.0.1:5000`).

- Autenticação: Bearer Token em `Authorization: Bearer <token>`.
- Content-Type: `application/json` em requisições com corpo.

## Sumário
- `GET /health` — status do servidor.
- `POST /auth/register` — criação de usuário e emissão de token.
- `POST /auth/login` — autenticação e emissão de token.
- `GET /auth/me` — perfil do usuário autenticado.
- `POST /generate` — geração multiagente (requer autenticação).

---

## `GET /health`
- Headers: nenhum.
- Body: vazio.
- Respostas:
  - 200: `{ "status": "ok" }`

Exemplo (PowerShell):
```
curl http://127.0.0.1:5000/health
```

---

## `POST /auth/register`
- Headers: `Content-Type: application/json`.
- Body (JSON):
```
{
  "email": "user@example.com",
  "password": "minha_senha_segura"
}
```
- Regras:
  - `email` obrigatório, único (não pode já existir).
  - `password` obrigatório, mínimo 6 caracteres.
- Respostas:
  - 201: `{"id": <number>, "email": "...", "token": "<Bearer Token>"}`
  - 400: campos ausentes ou senha fraca.
  - 409: email já registrado.

Exemplo (PowerShell):
```
curl -X POST http://127.0.0.1:5000/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"user@example.com","password":"minha_senha_segura"}'
```

---

## `POST /auth/login`
- Headers: `Content-Type: application/json`.
- Body (JSON):
```
{
  "email": "user@example.com",
  "password": "minha_senha_segura"
}
```
- Respostas:
  - 200: `{"id": <number>, "email": "...", "token": "<Bearer Token>"}`
  - 400: campos ausentes.
  - 401: credenciais inválidas.

Exemplo (PowerShell):
```
curl -X POST http://127.0.0.1:5000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"user@example.com","password":"minha_senha_segura"}'
```

---

## `GET /auth/me`
- Headers:
  - `Authorization: Bearer <token>`
  - Ou via query string (compatibilidade): `?authorization=Bearer <token>` ou `?token=<token>`
- Body: vazio.
- Respostas:
  - 200: `{"id": <number>, "email": "...", "created_at": "<ISO>"}`
  - 401: não autenticado.
  - 404: usuário não encontrado.

Exemplo (PowerShell):
```
curl http://127.0.0.1:5000/auth/me \
  -H "Authorization: Bearer <token>"
```

---

## `POST /generate`
- Requer autenticação.
- Headers:
  - `Authorization: Bearer <token>`
  - Ou via query string (compatibilidade): `?authorization=Bearer <token>` ou `?token=<token>`
  - `Content-Type: application/json`
- Body (JSON):
```
{
  "task": "Descreva a tarefa a ser realizada.",
  "language": "Python",                 // opcional (padrão: "Python")
  "agents": ["front", "back", "qa"]   // opcional, válido: front|back|qa
}
```
- Campo `task`: obrigatório.
- Campo `language`: opcional; língua-alvo para integração backend e prompts.
- Campo `agents`: opcional; se omitido, executa `["front","back","qa"]`.
- Respostas:
  - 200: 
```
{
  "task": "...",
  "language": "Python",
  "front": "<HTML/CSS/JS em blocos>",
  "back": "<implementação de API/servidor>",
  "qa": "<casos de teste manuais e automatizados>"
}
```
  - 400: `{ "error": "Campo 'task' é obrigatório" }`
  - 401: `{ "error": "Não autenticado" }`
  - 500: `{ "error": "<mensagem de erro>" }`

Exemplo (PowerShell):
```
curl -X POST http://127.0.0.1:5000/generate \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
        "task":"Crie uma tela de login com validação.",
        "language":"Node.js",
        "agents":["front","back","qa"]
      }'
```

---

## Observações adicionais
- Tokens: validade padrão de 7 dias (`TOKEN_MAX_AGE` pode ajustar).
- Persistência: cada execução de `/generate` é gravada em `history` e associada ao `user_id` quando autenticada.
- Erros: respostas de erro incluem `{ "error": "..." }` com HTTP status apropriado.