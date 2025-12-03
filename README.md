

# Multiagent System – Geração Automatizada de Frontend / Backend / QA

Sistema multiagente em Python projetado para gerar automaticamente código de frontend, backend e testes QA a partir de uma única solicitação. O pipeline integra três agentes especializados e um orquestrador central, garantindo consistência, validação e produtividade. A solução inclui autenticação JWT, persistência local em SQLite, presets para frameworks (Flask, Express, Spring Boot) e suporte a múltiplas linguagens.


## Estrutura do Projeto (agora em bloco de código)

```
/
├── data/
│   └── history.db
├── multiagent_system_updated/
│   ├── data/
│   │   ├── history.db
│   │   └── history.sqbpro
│   ├── src/
│   │   ├── agents/
│   │   │   ├── __init__.py
│   │   │   ├── base_agent.py
│   │   │   ├── back_agent.py
│   │   │   ├── front_agent.py
│   │   │   └── qa_agent.py
│   │   └── core/
│   │       ├── __init__.py
│   │       ├── auth.py
│   │       ├── openai_client.py
│   │       ├── orchestrator.py
│   │       ├── packager.py
│   │       ├── schema.sql
│   │       └── validation.py
│   ├── main.py
│   └── README.md
├── requirements.txt
├── .env
├── .env.example
└── .gitignore
```

---


 O entrypoint oficial do sistema é multiagent_system_updated/main.py.

---

📌 Como Executar o Projeto
1. Entrar no diretório correto

O projeto não roda no diretório raiz.
Acesse o módulo principal:

```

cd multiagent_system_updated

```

---

## Criar e ativar o ambiente virtual

Linux/Mac:

```
python3 -m venv venv
source venv/bin/activate 
```

Windows:

```
python -m venv venv
venv\Scripts\activate
```

---

## Instalar dependências

O requirements.txt está no diretório raiz, então rode:

```
pip install -r ../requirements.txt
```


## Configurar variáveis de ambiente

Crie o arquivo .env e adicione: 

```
OPENAI_API_KEY=sua-chave
SECRET_KEY=chave-secreta
TOKEN_MAX_AGE=604800
DATABASE_PATH=./data/history.db
PASSWORD_PEPPER=valor_unico
```

---

## Executar o servidor

```
python main.py
```
O servidor iniciará em:

```
http://127.0.0.1:5000
```
O banco SQLite é criado automaticamente caso não exista.

---


##  📌 Tecnologias Utilizadas

## Backend

Python 3.10+

Flask (API REST)

SQLite3

PyJWT (autenticação)

bcrypt (hashing seguro)

python-dotenv (carregamento de variáveis)

## Inteligência / Geração de Código

OpenAI API

Arquitetura multiagente (Front → Back → QA)

Validação estrutural via contrato

## Presets Inclusos

Flask – Python

Express.js – Node.js

Spring Boot – Java

----
----
📌 Orquestração dos Agentes
----
# O pipeline segue esta ordem:

Front Agent
Gera UI, páginas, componentes, validações.

Back Agent
Implementa rotas, serviços, modelos e lógica de negócios.

QA Agent
Avalia Front + Back, valida contrato e produz testes automatizados.

Packager (opcional)
Monta um ZIP completo com frontend, backend, documentação e esquema.


Toda execução é registrada no banco history.db.

---
## 📌 Endpoints Disponíveis

### 🔐 Autenticação

| Método | Rota          | Descrição                |
|--------|---------------|--------------------------|
| POST   | /auth/register | Criar conta             |
| POST   | /auth/login    | Retorna JWT            |
| GET    | /auth/me       | Retorna dados do usuário |

---

### ⚙️ Geração de Código

| Método | Rota           | Descrição                              |
|--------|----------------|------------------------------------------|
| POST   | /generate      | Executa pipeline Front → Back → QA      |
| POST   | /generate_zip  | Gera ZIP completo                       |


## Headers obrigatórios

````
Authorization: Bearer <TOKEN>
Content-Type: application/json
````
## Exemplo de corpo

````
{
  "task": "Criar CRUD de tarefas",
  "language": "Python",
  "agents": ["front", "back", "qa"],
  "preset": "flask"
}
````

## 📌 Exemplo Completo via cURL

Registrar:

```
curl -X POST http://127.0.0.1:5000/auth/register \
  -H "Content-Type: application/json" \
  -d "{\"email\":\"teste@ex.com\",\"password\":\"Senha@123\"}"
```

Login:

```
curl -X POST http://127.0.0.1:5000/auth/login \
  -H "Content-Type: application/json" \
  -d "{\"email\":\"teste@ex.com\",\"password\":\"Senha@123\"}"
```

Gerar ZIP:

```
curl -X POST http://127.0.0.1:5000/generate_zip \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d "{\"task\":\"CRUD de tarefas\",\"language\":\"Node\",\"agents\":[\"front\",\"back\",\"qa\"],\"preset\":\"express\"}"
```

---
## 📌 Observações Importantes

- A execução deve ocorrer dentro da pasta multiagent_system_updated/.
- O banco SQLite grava todas as requisições, tokens e logs.
- O sistema bloqueia tentativas de login indevidas após múltiplas falhas.
- O QA Agent valida consistência entre Front e Back antes de gerar testes.
- A geração ZIP produz uma estrutura completa, pronta para deploy ou estudos.

---
