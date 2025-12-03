import io
import re
import json
from turtle import reset
import zipfile
from typing import Optional


def _extract_code_blocks(text: str) -> list[dict]:
    """
    Extrai blocos de código Markdown (```lang\n...```) e tenta identificar
    nomes de arquivos associados ao bloco.

    Heurísticas suportadas para filename:
    - Comentário nas primeiras linhas do bloco contendo "<nome.ext>" (HTML, JS, CSS, Python)
    - Linha imediatamente ANTERIOR ao bloco contendo um caminho como "backend/app/main.py"
    - Primeiras 5 linhas do bloco contendo apenas um caminho "foo/bar.ext" (sem comentário)

    Retorna lista de dicts: {language, content, filename}
    """
    blocks: list[dict] = []
    # Aceita "```python", "``` python" e quebra de linha Windows (\r\n)
    pattern = re.compile(r"```\s*([a-zA-Z0-9_+-]*)\s*\r?\n(.*?)```", re.DOTALL)
    source = text or ""
    for m in pattern.finditer(source):
        lang = m.group(1) or ""
        content = m.group(2)
        filename = None

        # 1) Comentários nas primeiras linhas
        first_lines = (content.splitlines()[:5]) if content else []
        for line in first_lines:
            l = line.strip()
            candidates = [
                r"<!--\s*(.+\.[a-zA-Z0-9]+)\s*-->",  # HTML
                r"//\s*(.+\.[a-zA-Z0-9]+)",          # JS/TS
                r"/\*\s*(.+\.[a-zA-Z0-9]+)\s*\*/", # CSS/JS
                r"#\s*(.+\.[a-zA-Z0-9]+)",           # Python/Config
            ]
            for p in candidates:
                mm = re.match(p, l)
                if mm:
                    filename = mm.group(1)
                    break
            if filename:
                break

        # 2) Linha anterior ao bloco, ex: "backend/app/main.py"
        if not filename:
            # pega até duas linhas anteriores do ponto inicial do bloco
            pre = source[: m.start()].splitlines()
            look_back = [pre[-1].strip()] if pre else []
            if len(pre) >= 2:
                look_back.insert(0, pre[-2].strip())
            for l in look_back:
                mm = re.match(r"^[#>*\-\s]*([A-Za-z0-9_./\\\-]+\.[A-Za-z0-9]+)\s*$", l)
                if mm:
                    filename = mm.group(1)
                    break

        # 3) Primeiras linhas com caminho direto sem comentário
        if not filename:
            for line in first_lines:
                l = line.strip()
                mm = re.match(r"^([A-Za-z0-9_./\\\-]+\.[A-Za-z0-9]+)\s*$", l)
                if mm:
                    filename = mm.group(1)
                    break

        blocks.append({"language": lang, "content": content, "filename": filename})
    return blocks


def _looks_like_java(content: str) -> bool:
    """Heurística simples para identificar conteúdo Java mesmo se a linguagem vier incorreta."""
    s = (content or "")
    patterns = [
        r"\bpublic\s+class\b",
        r"\bclass\s+[A-Za-z0-9_]+\b",
        r"^\s*import\s+[A-Za-z0-9_.]+;",
        r"@SpringBootApplication",
        r"@RestController",
        r"@RequestMapping",
    ]
    for p in patterns:
        if re.search(p, s, re.MULTILINE):
            return True
    return False


def _sanitize_flask_python(content: str) -> str:
    """Sanitiza arquivos Python de backend para usar um único app Flask.
    - Remove instâncias locais de `app = Flask(__name__)`
    - Remove `app.run(...)` e blocos `if __name__ == '__main__':`
    - Injeta `from . import app` para usar o app compartilhado de backend/app/__init__.py
    """
    lines = (content or "").splitlines()
    out_lines: list[str] = []
    skip_block = False
    for ln in lines:
        l = ln.strip()
        # Pula blocos main
        if l.startswith("if __name__ == '__main__':") or l.startswith('if __name__ == "__main__":'):
            skip_block = True
            continue
        if skip_block:
            # encerra skip ao encontrar linha vazia ou dedent visível
            if l == "" or (not ln.startswith(" ") and not ln.startswith("\t")):
                skip_block = False
            continue
        # Remove app.run chamadas
        if re.search(r"\bapp\s*\.\s*run\s*\(", l):
            continue
        # Remove instância local de Flask
        if re.search(r"^app\s*=\s*Flask\(\s*__name__\s*\)\s*$", l):
            continue
        out_lines.append(ln)
    sanitized = "\n".join(out_lines)
    # Injeta import do app compartilhado apenas quando necessário:
    # - Arquivos que usam @app.route ou instanciam Flask localmente
    # - NÃO injeta em módulos que apenas definem Blueprints
    uses_app_routes = re.search(r"@\s*app\s*\.\s*route\s*\(", sanitized)
    defines_blueprint = re.search(r"\bBlueprint\s*\(", sanitized)
    instantiates_flask = re.search(r"\bFlask\s*\(", sanitized)
    if (uses_app_routes or instantiates_flask) and not defines_blueprint:
        if "from . import app" not in sanitized:
            imports = list(re.finditer(r"^(?:from\s+\S+\s+import\s+\S+|import\s+\S+)", sanitized, re.MULTILINE))
            if imports:
                idx = imports[-1].end()
                sanitized = sanitized[:idx] + "\nfrom . import app\n" + sanitized[idx:]
            else:
                sanitized = "from . import app\n" + sanitized
    return sanitized


def _sanitize_express_js(content: str) -> str:
    """Sanitiza arquivos Node/Express para evitar múltiplos servidores.
    - Remove linhas com `app.listen(` ou `server.listen(`
    - Remove bloco `if (require.main === module) { ... }` (se existir)
    """
    lines = (content or "").splitlines()
    out_lines: list[str] = []
    skipping_main = False
    brace_depth = 0
    for ln in lines:
        l = ln.strip()
        if skipping_main:
            brace_depth += ln.count("{")
            brace_depth -= ln.count("}")
            if brace_depth <= 0:
                skipping_main = False
            continue
        if "require.main === module" in l:
            skipping_main = True
            brace_depth = 0
            continue
        if re.search(r"\b(app|server)\s*\.\s*listen\s*\(", l):
            continue
        out_lines.append(ln)
    sanitized = "\n".join(out_lines)
    # Corrige possíveis '}' sobrando causados por remoção do bloco require.main
    # Remove chaves de fechamento soltas no final do arquivo
    while sanitized.rstrip().endswith("}") and sanitized.count("}") > sanitized.count("{"):
        sanitized = sanitized.rstrip()
        sanitized = sanitized[:-1]
    return sanitized

def _sanitize_front_js(content: str) -> str:
    """Sanitiza arquivos de frontend para evitar erros ao iterar listas.
    - Substitui `users.forEach(` por iteração segura que aceita Page/content/items/users/data ou array
    """
    text = content or ""
    # Patch específico para a coleção 'users' usada em telas comuns de listagem
    safe_iter = (
        "((Array.isArray(users) ? users : (users && users.content) || (users && users.items) "
        "|| (users && users.users) || (users && users.data) || []))"
    )
    text = re.sub(r"(?<!\w)users\s*\.\s*forEach\s*\(", safe_iter + ".forEach(", text)
    return text

def _infer_resource(task: str, front: Optional[str], back: Optional[str], qa: Optional[str]) -> str:
    """Infer the desired resource collection name from task text and any code/spec blocks.
    - Looks for '/api/<resource>' in provided texts
    - Parses JSON-like 'path' fields if present
    - Falls back to a word after 'CRUD de' in Portuguese or 'CRUD of' in English
    - Default: 'users'
    """
    texts = [task or "", front or "", back or "", qa or ""]
    candidates: list[str] = []
    for t in texts:
        # paths like /api/users or /users
        for m in re.findall(r"/(?:api/)?([a-zA-Z][a-zA-Z0-9_-]+)(?:/|\b)", t):
            if m.lower() in ("health",):
                continue
            candidates.append(m.lower())
        # JSON contract paths: "path": "/users"
        for m in re.findall(r"\"path\"\s*:\s*\"/(?:api/)?([a-zA-Z0-9_-]+)\"", t):
            candidates.append(m.lower())
        # Portuguese 'CRUD de <algo>' or English 'CRUD of <something>'
        m1 = re.search(r"crud\s+de\s+([a-zA-Zçáéíóúâêôãõü]+)", t, re.IGNORECASE)
        if m1:
            candidates.append(m1.group(1).lower())
        m2 = re.search(r"crud\s+of\s+([a-zA-Z]+)", t, re.IGNORECASE)
        if m2:
            candidates.append(m2.group(1).lower())
    if candidates:
        from collections import Counter
        resource = Counter(candidates).most_common(1)[0][0]
    else:
        resource = "users"
    if resource.endswith("/:"):
        resource = resource.split("/:")[0]
    if resource.endswith(":id"):
        resource = resource[:-3]
    if not resource.endswith("s"):
        if resource.endswith("m"):
            resource = resource[:-1] + "ns"
        elif resource.endswith("y"):
            resource = resource[:-1] + "ies"
        else:
            resource = resource + "s"
    return re.sub(r"[^a-z0-9_-]", "", resource)

def _build_express_crud(resource: str) -> str:
    """Generate an Express in-memory CRUD for the given resource with Page-like response."""
    r = resource
    return (
        "const express = require('express');\n"
        "const cors = require('cors');\n"
        "const app = express();\n"
        "const PORT = process.env.PORT || 3000;\n\n"
        "app.use(cors());\n"
        "app.use(express.json());\n\n"
        "// Healthcheck\n"
        "app.get('/health', (req,res)=>res.json({status:'ok'}));\n\n"
        "// Estado em memória para '" + r + "'\n"
        "const records = [];\n"
        "let currentId = 1;\n\n"
        "// GET /api/" + r + " (Page-like)\n"
        "app.get('/api/" + r + "', (req, res) => {\n"
        "  const name = (req.query.name || '').toString().toLowerCase();\n"
        "  const size = Math.max(1, parseInt(req.query.size || '10', 10));\n"
        "  const page = Math.max(0, parseInt(req.query.page || '0', 10));\n\n"
        "  const filtered = name ? records.filter(u => (u.name || '').toLowerCase().includes(name)) : records;\n"
        "  const start = page * size;\n"
        "  const end = start + size;\n"
        "  const content = filtered.slice(start, end);\n\n"
        "  res.json({ content, totalElements: filtered.length, size, number: page });\n"
        "});\n\n"
        "// POST /api/" + r + "\n"
        "app.post('/api/" + r + "', (req, res) => {\n"
        "  const { name } = req.body || {};\n"
        "  if (!name || typeof name !== 'string') {\n"
        "    return res.status(400).json({ error: 'name é obrigatório' });\n"
        "  }\n"
        "  const rec = { id: currentId++, name };\n"
        "  records.push(rec);\n"
        "  res.status(201).json(rec);\n"
        "});\n\n"
        "// PUT /api/" + r + "/:id\n"
        "app.put('/api/" + r + "/:id', (req, res) => {\n"
        "  const id = Number(req.params.id);\n"
        "  const { name } = req.body || {};\n"
        "  const idx = records.findIndex(u => u.id === id);\n"
        "  if (idx === -1) return res.status(404).json({ error: 'Registro não encontrado' });\n"
        "  if (!name || typeof name !== 'string') return res.status(400).json({ error: 'name é obrigatório' });\n"
        "  records[idx].name = name;\n"
        "  res.json(records[idx]);\n"
        "});\n\n"
        "// DELETE /api/" + r + "/:id\n"
        "app.delete('/api/" + r + "/:id', (req, res) => {\n"
        "  const id = Number(req.params.id);\n"
        "  const idx = records.findIndex(u => u.id === id);\n"
        "  if (idx === -1) return res.status(404).json({ error: 'Registro não encontrado' });\n"
        "  records.splice(idx, 1);\n"
        "  res.status(204).send();\n"
        "});\n\n"
        "app.listen(PORT, ()=>console.log('Server on ' + PORT));\n"
    )

def _sanitize_java(content: str) -> str:
    """Remove cabeçalhos de texto livres antes do código Java para evitar erros de compilação."""
    lines = (content or "").splitlines()
    start_idx = 0
    tokens = (
        "package ", "import ", "@", "public ", "class ", "interface ", "enum ", "/*", "//"
    )
    for i, ln in enumerate(lines):
        l = ln.strip()
        if l == "":
            continue
        if any(l.startswith(t) for t in tokens):
            start_idx = i
            break
    cleaned = "\n".join(lines[start_idx:])
    # Normaliza imports para compatibilidade com Spring Boot 3 (jakarta.*)
    cleaned = cleaned.replace("javax.persistence", "jakarta.persistence")
    cleaned = cleaned.replace("javax.validation", "jakarta.validation")
    return cleaned


def _sanitize_java_entity_table(content: str) -> str:
    """Se o conteúdo for uma entidade JPA sem @Table e a classe for User,
    adiciona @Table(name="users") para evitar a palavra reservada USER no H2.
    Também corrige @Table(name="user") → "users" e garante import de Table.
    """
    text = content or ""
    if "@Entity" not in text:
        return text

    # Corrige nome de tabela explícito "user" para "users"
    text = re.sub(r"@Table\s*\(\s*name\s*=\s*\"user\"\s*\)", "@Table(name=\"users\")", text)

    # Detecta nome da classe
    m = re.search(r"\bclass\s+([A-Za-z0-9_]+)", text)
    class_name = (m.group(1) if m else "")
    has_table = "@Table(" in text

    if class_name.lower() == "user" and not has_table:
        # Inserir @Table após @Entity
        lines = text.splitlines()
        out = []
        inserted = False
        for ln in lines:
            out.append(ln)
            if not inserted and ln.strip().startswith("@Entity"):
                out.append("@Table(name = \"users\")")
                inserted = True
        text = "\n".join(out)

        # Garante import de Table
        if "import jakarta.persistence.Table;" not in text:
            # Inserir após outros imports jakarta.persistence, se possível
            import_lines = []
            other_lines = []
            for ln in text.splitlines():
                if ln.strip().startswith("import "):
                    import_lines.append(ln)
                else:
                    other_lines.append(ln)
            if import_lines:
                # Reconstrói com novo import junto aos demais
                text = "\n".join(import_lines + ["import jakarta.persistence.Table;"] + other_lines)
            else:
                text = "import jakarta.persistence.Table;\n" + text

    return text


def _safe_ext(lang: str) -> str:
    """Normaliza a 'extensão' derivada da linguagem do bloco.
    Remove caracteres não alfanuméricos; fallback para 'txt' se vazio.
    """
    s = (lang or "").lower()
    s = re.sub(r"[^a-z0-9]+", "", s)
    if s in ("", "markdown", "md", "plain", "text"):
        return "txt"
    return s


def _sanitize_java_filename(fn: Optional[str], fallback_class: str) -> str:
    """Gera um nome de arquivo Java seguro.
    - Usa `fallback_class` se `fn` for vazio ou não terminar com `.java`.
    - Remove caracteres inválidos, espaços e extensões estranhas.
    """
    if not fn or not fn.lower().endswith(".java"):
        base = fallback_class
    else:
        base = fn[:-5]  # remove .java
    base = re.sub(r"[^A-Za-z0-9_]", "", base) or fallback_class
    return base + ".java"


def _lang_ext(lang: str) -> str:
    """Mapeia linguagem para extensão esperada; fallback usando _safe_ext."""
    m = {
        "python": "py", "py": "py",
        "javascript": "js", "js": "js",
        "typescript": "ts", "ts": "ts",
        "java": "java",
        "yaml": "yml", "yml": "yml",
        "xml": "xml", "pom": "xml",
        "json": "json",
        "bash": "sh", "sh": "sh",
        "html": "html", "css": "css"
    }
    return m.get((lang or "").lower(), _safe_ext(lang or "txt"))


def _postprocess_front_files(desired: dict[str, Optional[str]], base_url_hint: Optional[str] = "/api", default_port: int = 5001) -> dict[str, Optional[str]]:
    """
    Garante que o frontend gerado esteja pronto para consumo imediato:
    - Injeta uma constante `API_BASE` com fallback para `http://127.0.0.1:5001/<base_url_hint>` se não existir.
    - Cria `index.html` e `script.js` mínimos se estiverem ausentes.
    - Não interfere agressivamente se já houver conteúdo; apenas adiciona o fallback de API_BASE.
    """
    updated = dict(desired)
    default_api_base = f"http://127.0.0.1:{default_port}{base_url_hint or '/api'}"

    # script.js
    script = updated.get("script.js")
    header = (
        "(function(){\n"
        "  try {\n"
        "    const qp = new URLSearchParams(window.location.search);\n"
        "    const override = qp.get('api');\n"
        f"    const computed = override || window.API_BASE || window.API_BASE_URL || \"{default_api_base}\";\n"
        "    window.API_BASE = computed;\n"
        "    if (!window.API_BASE_URL || (typeof window.API_BASE_URL === 'string' && window.API_BASE_URL.startsWith('/'))) {\n"
        "      window.API_BASE_URL = computed;\n"
        "    }\n"
        "  } catch (e) {\n"
        f"    const computed = window.API_BASE || window.API_BASE_URL || \"{default_api_base}\";\n"
        "    window.API_BASE = computed;\n"
        "    if (!window.API_BASE_URL || (typeof window.API_BASE_URL === 'string' && window.API_BASE_URL.startsWith('/'))) {\n"
        "      window.API_BASE_URL = computed;\n"
        "    }\n"
        "  }\n"
        "})();\n"
    )
    helper = (
        "async function apiFetch(path, options = {}) {\n"
        "  const url = `${API_BASE}${path.startsWith('/') ? path : '/' + path}`;\n"
        "  const opts = { ...options };\n"
        "  if (opts.body && !(opts.headers && (opts.headers['Content-Type'] || opts.headers['content-type']))) {\n"
        "    opts.headers = { ...(opts.headers || {}), 'Content-Type': 'application/json' };\n"
        "  }\n"
        "  const resp = await fetch(url, opts);\n"
        "  const ct = resp.headers.get('content-type') || '';\n"
        "  const isJson = ct.includes('application/json');\n"
        "  const payload = isJson ? await resp.json() : await resp.text();\n"
        "  if (!resp.ok) {\n"
        "    const msg = typeof payload === 'string' ? payload : (payload.message || JSON.stringify(payload));\n"
        "    throw new Error(msg);\n"
        "  }\n"
        "  return payload;\n"
        "}\n"
    )
    if not script or not script.strip():
        # Script mínimo para formulário de login
        updated["script.js"] = (
            header + helper + "\n"
            + "document.addEventListener('DOMContentLoaded', () => {\n"
            + "  const form = document.getElementById('loginForm');\n"
            + "  if (!form) return;\n"
            + "  form.addEventListener('submit', async (e) => {\n"
            + "    e.preventDefault();\n"
            + "    const username = document.getElementById('username').value;\n"
            + "    const password = document.getElementById('password').value;\n"
            + "    const msg = document.getElementById('responseMessage');\n"
            + "    try {\n"
            + "      const data = await apiFetch('/auth/login', {\n"
            + "        method: 'POST',\n"
            + "        body: JSON.stringify({ username, password })\n"
            + "      });\n"
            + "      msg.textContent = `Bem-vindo: ${data.username}`;\n"
            + "    } catch (err) {\n"
            + "      console.error(err);\n"
            + "      msg.textContent = `Erro de rede: ${err.message}`;\n"
            + "    }\n"
            + "  });\n"
            + "});\n"
        )
    else:
        # Sempre prefixa header (não declara const/var), para corrigir bases relativas e aceitar ?api=
        sanitized_script = _sanitize_front_js(script)
        if "apiFetch(" not in sanitized_script:
            updated["script.js"] = header + helper + sanitized_script
        else:
            updated["script.js"] = header + sanitized_script

    # index.html
    index_html = updated.get("index.html")
    if not index_html or not index_html.strip():
        updated["index.html"] = (
            "<!doctype html>\n"
            "<html lang=\"pt-BR\">\n"
            "<head>\n"
            "  <meta charset=\"utf-8\">\n"
            "  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
            "  <title>Login</title>\n"
            "  <style>body{font-family:sans-serif;display:flex;min-height:100vh;align-items:center;justify-content:center;background:#f5f5f5} .card{background:#fff; padding:24px; border-radius:8px; box-shadow:0 2px 8px rgba(0,0,0,.1); width:320px} .row{display:flex; flex-direction:column; gap:8px} input{padding:8px;border:1px solid #ddd;border-radius:4px} button{padding:10px;border:none;border-radius:4px;background:#2e7d32;color:#fff;cursor:pointer} #responseMessage{margin-top:10px;color:#333}</style>\n"
            "</head>\n"
            "<body>\n"
            "  <div class=\"card\">\n"
            "    <h2>Login</h2>\n"
            "    <form id=\"loginForm\" class=\"row\">\n"
            "      <input id=\"username\" type=\"text\" placeholder=\"Usuário\" required />\n"
            "      <input id=\"password\" type=\"password\" placeholder=\"Senha\" required />\n"
            "      <button type=\"submit\">Entrar</button>\n"
            "    </form>\n"
            "    <div id=\"responseMessage\"></div>\n"
            "  </div>\n"
            "  <script src=\"./script.js\"></script>\n"
            "</body>\n"
            "</html>\n"
        )

    return updated


def _sanitize_generic_filename(lang: str, fn: Optional[str], fallback_base: str, force_ext: bool = True) -> str:
    """Sanitiza nome de arquivo genérico:
    - Remove caminhos (usa apenas basename)
    - Elimina caracteres não alfanuméricos, espaços e nomes iniciando com '-'
    - Força extensão coerente com a linguagem
    """
    name = (fn or fallback_base).strip()
    # remove caminhos
    name = name.replace("\\", "/")
    name = name.split("/")[-1]
    # descarta nomes inválidos
    if name.startswith("-") or not re.search(r"[A-Za-z0-9]", name):
        name = fallback_base
    # separa base e ext existente
    base, ext_existing = (name.rsplit('.', 1) + [None])[:2] if '.' in name else (name, None)
    base = re.sub(r"[^A-Za-z0-9_]", "", base) or fallback_base
    ext = _lang_ext(lang)
    if force_ext:
        return f"{base}.{ext}"
    # se não forçar, mantém ext se adequada
    if ext_existing and ext_existing.lower() == ext:
        return f"{base}.{ext_existing}"
    return f"{base}.{ext}"


def build_project_zip(task: str, language: str, front: str, back: str, qa: str) -> io.BytesIO:
    """Constroi um ZIP em memória com conteúdo gerado pelos agentes.
    Estrutura:
      /README.md
      /frontend/index.html, styles.css, script.js (ou fallback)
      /backend/README.md (com conteúdo bruto); opcional extração de blocos
      /qa/README.md (conteúdo bruto)
    """
    mem = io.BytesIO()
    with zipfile.ZipFile(mem, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        # Top-level README com contexto
        top_readme = f"""# Projeto Gerado

Task: {task}
Language: {language}

Este arquivo zip contém os artefatos gerados pelos agentes:
- frontend: UI (HTML/CSS/JS)
- backend: implementação/rotas geradas pelo agente de backend
- qa: casos de teste e sugestões

Como executar (Flask backend + frontend estático):
1) Backend
   - Instale dependências: `pip install -r backend/requirements.txt`
   - Rode o servidor (porta 5001): `python -m flask --app backend.app:app run --port 5001`
2) Frontend
   - Sirva os arquivos: `python -m http.server 5500`
   - Abra: `http://127.0.0.1:5500/frontend/index.html`

Observação: o frontend usa `API_BASE` com fallback para `http://127.0.0.1:5001/api`. Você pode sobrescrever via `window.API_BASE` ou passando `?api=http://127.0.0.1:5001/api` na URL.

Testes rápidos de API (Flask):
- `GET http://127.0.0.1:5001/health`
- `GET http://127.0.0.1:5001/api/tasks`
- `POST http://127.0.0.1:5001/api/tasks` Body JSON: `{{"task":"Nova tarefa"}}`
"""
        zf.writestr("README.md", top_readme)

        # FRONTEND
        front_blocks = _extract_code_blocks(front)
        # Mapeia nomes desejados
        desired = {
            "index.html": None,
            "styles.css": None,
            "script.js": None,
        }
        # Primeiro, tenta pelo filename detectado
        for b in front_blocks:
            fn = (b.get("filename") or "").lower()
            if fn in desired and desired[fn] is None:
                desired[fn] = b["content"]
        # Fallback: usa os três primeiros blocos se faltou algum
        fb_idx = 0
        for key in desired:
            if desired[key] is None and fb_idx < len(front_blocks):
                desired[key] = front_blocks[fb_idx]["content"]
                fb_idx += 1
        # Armazena original e escreve versões com fallback inicial (porta 5001)
        front_desired_original = dict(desired)
        desired_tmp = _postprocess_front_files(front_desired_original, base_url_hint="/api", default_port=5001)
        for fn, content in desired_tmp.items():
            if content:
                zf.writestr(f"frontend/{fn}", content)
        # Guarda o bruto
        if front:
            zf.writestr("frontend/FRONT_RAW.md", front)

        # BACKEND
        if back:
            zf.writestr("backend/BACK_RAW.md", back)
            # Opcional: tenta extrair blocos e escrever arquivos com heurísticas
            back_blocks = _extract_code_blocks(back)

            # Detecta e registra contrato de API em docs/api_contract.json
            for b in back_blocks:
                fn = (b.get("filename") or "").lower()
                lang = (b.get("language") or "").lower()
                content = b.get("content") or ""
                if fn == "api_contract.json" or (lang == "json" and '"endpoints"' in content and '"base_url"' in content):
                    zf.writestr("docs/api_contract.json", content)
                    # marca para não duplicar em backend/
                    b["_skip_write"] = True

            def _java_path_and_name(content: str) -> tuple[str, str]:
                """Tenta inferir package e nome de classe para Java.
                Usa heurística: main -> base; controller -> .controller; entity -> .model; service -> .service; repository -> .repository
                """
                base_pkg = "com.example.demo"
                if "@SpringBootApplication" in (content or ""):
                    pkg = base_pkg
                elif "@RestController" in (content or "") or "@Controller" in (content or ""):
                    pkg = base_pkg + ".controller"
                elif "@Entity" in (content or ""):
                    pkg = base_pkg + ".model"
                elif "@Service" in (content or ""):
                    pkg = base_pkg + ".service"
                elif "@Repository" in (content or ""):
                    pkg = base_pkg + ".repository"
                else:
                    pkg = base_pkg + ".controller"
                cls = "ServerPart"
                for line in (content or "").splitlines():
                    line = line.strip()
                    if line.startswith("package ") and line.endswith(";"):
                        # Mantém package detectado apenas para arquivos que não são main
                        if "@SpringBootApplication" not in (content or ""):
                            pkg = line[len("package "):-1].strip()
                    m = re.match(r"public\s+class\s+([A-Za-z0-9_]+)", line)
                    if m:
                        cls = m.group(1)
                        break
                pkg_path = pkg.replace(".", "/")
                return pkg_path, cls

            # Detecta stack para estruturar corretamente
            has_flask = any(
                (b.get("language") or "").lower() in ("python", "py") or
                ("Flask(" in (b.get("content") or "") or "from flask" in (b.get("content") or ""))
                for b in back_blocks
            ) or (language.lower() == "python")
            has_express = any(
                (b.get("language") or "").lower() in ("javascript", "js", "typescript", "ts") or
                ("express" in (b.get("content") or "").lower())
                for b in back_blocks
            ) or (language.lower() in ("javascript", "js", "node", "typescript", "ts"))

            if has_flask:
                # Scaffold Flask com CORS, health e registro explícito/automático de Blueprints
                zf.writestr("backend/requirements.txt", "flask\nitsdangerous\nflask-cors\npython-dotenv\n")
                # Garante execução na porta 5001 por padrão quando usar `flask run`
                zf.writestr("backend/.flaskenv", "FLASK_APP=backend.app:app\nFLASK_RUN_PORT=5001\n")
                zf.writestr(
                    "backend/app/__init__.py",
                    """from flask import Flask, Blueprint\nfrom flask_cors import CORS\nimport pkgutil, importlib\n\napp = Flask(__name__)\nCORS(app)\n\n@app.get('/health')\ndef _health():\n    return {"status": "ok"}\n\n# Registra explicitamente o Blueprint 'main' e depois faz auto-discovery\ndef _register_blueprints():\n    # Registro explícito do 'main' se existir\n    try:\n        from .main import main as main_bp\n        if 'main' not in app.blueprints:\n            app.register_blueprint(main_bp)\n    except Exception as e:\n        print(f"[app] Falha ao registrar blueprint 'main': {e}")\n\n    # Auto-discovery de Blueprints em backend/app/*\n    try:\n        for _, modname, _ in pkgutil.iter_modules(__path__):\n            try:\n                m = importlib.import_module(f"{__name__}.{modname}")\n                for attr_name in dir(m):\n                    obj = getattr(m, attr_name)\n                    if isinstance(obj, Blueprint) and obj.name not in app.blueprints:\n                        app.register_blueprint(obj)\n            except Exception as e:\n                print(f"[app] Ignorando módulo {modname}: {e}")\n    except Exception as e:\n        print(f"[app] Falha ao varrer blueprints: {e}")\n\n    print(f"[app] Blueprints registrados: {list(app.blueprints.keys())}")\n\n_register_blueprints()\n"""
                )
                # Só escreve main.py mínimo se não houver bloco no README apontando para backend/app/main.py
                if not re.search(r"backend/app/main\.py", back or "", re.IGNORECASE):
                    zf.writestr(
                        "backend/app/main.py",
                        """from flask import Blueprint, jsonify, request, abort\n\n# Blueprint principal com prefixo /api\nmain = Blueprint('main', __name__, url_prefix='/api')\n\n# Estado em memória (apenas para demo)\ntasks = []\ntask_id_counter = 1\n\n@main.route('/tasks', methods=['GET'])\ndef get_tasks():\n    return jsonify({ 'tasks': tasks })\n\n@main.route('/tasks', methods=['POST'])\ndef create_task():\n    global task_id_counter\n    data = request.get_json()\n    if not data or 'task' not in data:\n        abort(400, description='Invalid input')\n    task = { 'id': task_id_counter, 'task': data['task'] }\n    tasks.append(task)\n    task_id_counter += 1\n    return jsonify(task), 201\n\n# TODO: mover rotas adicionais aqui\n"""
                    )

            if has_express:
                # scaffold mínimo para app único (com CORS)
                pkg = """{\n  \"name\": \"generated-server\",\n  \"version\": \"0.1.0\",\n  \"private\": true,\n  \"scripts\": {\n    \"start\": \"node src/index.js\"\n  },\n  \"dependencies\": {\n    \"express\": \"^4.18.2\",\n    \"cors\": \"^2.8.5\"\n  }\n}\n"""
                zf.writestr("backend/package.json", pkg)
                # Express CRUD gerado dinamicamente conforme a entidade solicitada no prompt/contrato
                try:
                    resource = _infer_resource(task or "", front, back, qa)
                except Exception:
                    resource = "users"
                zf.writestr("backend/src/index.js", _build_express_crud(resource))

            spring_main_written = False
            saw_java = False
            pom_written = False
            java_pkgs: set[str] = set()
            for i, b in enumerate(back_blocks, start=1):
                lang = (b.get("language") or "txt").lower()
                content = b.get("content") or ""
                fn = b.get("filename")
                if b.get("_skip_write"):
                    continue

                # Corrige linguagem mal rotulada e sanitiza conteúdo Java
                if (lang != "java" and _looks_like_java(content)) or lang == "java":
                    lang = "java"
                    content = _sanitize_java(content)
                    content = _sanitize_java_entity_table(content)
                    content = _sanitize_java_entity_table(content)

                # Corrige linguagem mal rotulada e sanitiza conteúdo Java
                if (lang != "java" and _looks_like_java(content)) or lang == "java":
                    lang = "java"
                    content = _sanitize_java(content)
                    content = _sanitize_java_entity_table(content)
                    content = _sanitize_java_entity_table(content)

                if reset == "spring" and lang == "java":
                    saw_java = True
                    pkg_path, cls = _java_path_and_name(content)
                    # registra pacote para cálculo de scan base
                    try:
                        java_pkgs.add(pkg_path.replace("/", "."))
                    except Exception:
                        pass
                    # evita múltiplos @SpringBootApplication: mantém apenas o primeiro
                    if "@SpringBootApplication" in content:
                        if spring_main_written:
                            content = content.replace("@SpringBootApplication", "")
                        else:
                            spring_main_written = True
                    name = _sanitize_java_filename(fn, cls)
                    path = f"backend/src/main/java/{pkg_path}/{name}"
                    zf.writestr(path, content)
                elif reset == "spring" and lang in ("xml", "pom") and ("<project" in content):
                    # Provável pom.xml — complementa com JPA/H2, jakarta.persistence-api e plugin se faltarem
                    def _augment_spring_pom(xml: str) -> str:
                        out = xml
                        if "spring-boot-starter-parent" not in out:
                            out = out.replace("<modelVersion>4.0.0</modelVersion>", "<modelVersion>4.0.0</modelVersion>\n  <parent>\n    <groupId>org.springframework.boot</groupId>\n    <artifactId>spring-boot-starter-parent</artifactId>\n    <version>3.3.0</version>\n    <relativePath/>\n  </parent>")
                        if "spring-boot-starter-web" not in out:
                            out = out.replace("</dependencies>", "  <dependency>\n      <groupId>org.springframework.boot</groupId>\n      <artifactId>spring-boot-starter-web</artifactId>\n    </dependency>\n  </dependencies>")
                        if "spring-boot-starter-data-jpa" not in out:
                            out = out.replace("</dependencies>", "  <dependency>\n      <groupId>org.springframework.boot</groupId>\n      <artifactId>spring-boot-starter-data-jpa</artifactId>\n    </dependency>\n    <dependency>\n      <groupId>com.h2database</groupId>\n      <artifactId>h2</artifactId>\n      <scope>runtime</scope>\n    </dependency>\n  </dependencies>")
                        if "jakarta.persistence-api" not in out:
                            out = out.replace("</dependencies>", "  <dependency>\n      <groupId>jakarta.persistence</groupId>\n      <artifactId>jakarta.persistence-api</artifactId>\n    </dependency>\n  </dependencies>")
                        if "spring-boot-maven-plugin" not in out:
                            if "</build>" in out:
                                out = out.replace("</build>", "  <plugins>\n      <plugin>\n        <groupId>org.springframework.boot</groupId>\n        <artifactId>spring-boot-maven-plugin</artifactId>\n      </plugin>\n    </plugins>\n  </build>")
                            else:
                                out = out.replace("</project>", "  <build>\n    <plugins>\n      <plugin>\n        <groupId>org.springframework.boot</groupId>\n        <artifactId>spring-boot-maven-plugin</artifactId>\n      </plugin>\n    </plugins>\n  </build>\n</project>")
                        return out
                    zf.writestr("backend/pom.xml", _augment_spring_pom(content))
                    pom_written = True
                elif lang in ("yml", "yaml"):
                    zf.writestr("backend/src/main/resources/application.yml", content)
                elif lang in ("python", "py") or (has_flask and ("flask" in content.lower() or "@app.route" in content.lower())):
                    # Roteia para backend/app e sanitiza para app compartilhado
                    name = _sanitize_generic_filename("python", fn, f"routes_{i}")
                    sanitized = _sanitize_flask_python(content)
                    zf.writestr(f"backend/app/{name}", sanitized)
                elif lang in ("javascript", "js", "typescript", "ts") or (has_express and ("express" in content.lower())):
                    # Roteia para backend/src e remove listens
                    ext_lang = "javascript" if lang in ("javascript", "js") else ("typescript" if lang in ("typescript", "ts") else lang)
                    name = _sanitize_generic_filename(ext_lang, fn, f"server_part_{i}")
                    sanitized = _sanitize_express_js(content)
                    base_lower = (name or "").lower()
                    # Evita criar arquivos duplicados do servidor Express. Todas as rotas ficam em index.js.
                    if base_lower in ("app.js", "server.js", "index.js"):
                        # Não escreve arquivos separados; o scaffold de index.js já concentra as rotas.
                        pass
                    else:
                        zf.writestr(f"backend/src/{name}", sanitized)
                elif lang in ("bash", "sh"):
                    name = _sanitize_generic_filename(lang, fn, f"server_part_{i}")
                    zf.writestr(f"backend/scripts/{name}", content)
                else:
                    name = _sanitize_generic_filename(lang, fn, f"server_part_{i}")
                    zf.writestr(f"backend/{name}", content)

            # Se tivemos Java mas nenhum main foi mantido, cria um main com scan para evitar 404
            if saw_java and not spring_main_written:
                base_pkg = "com.example"
                pkg_path = base_pkg.replace(".", "/")
                name = "DemoApplication.java"
                # Determina raiz de scan a partir dos pacotes detectados; fallback para "com.example"
                def _compute_scan_base(pkgs: set[str], default_base: str) -> str:
                    if not pkgs:
                        return ".".join(default_base.split(".")[:2]) or default_base
                    parts_list = [p.split(".") for p in pkgs]
                    base: list[str] = []
                    for i in range(min(len(p) for p in parts_list)):
                        token = parts_list[0][i]
                        if all(len(p) > i and p[i] == token for p in parts_list):
                            base.append(token)
                        else:
                            break
                    if len(base) < 2:
                        return ".".join(default_base.split(".")[:2]) or default_base
                    return ".".join(base)

                scan_base = _compute_scan_base(java_pkgs, base_pkg)
                main_src = (
                    "package com.example;\n"
                    "import org.springframework.boot.SpringApplication;\n"
                    "import org.springframework.boot.autoconfigure.SpringBootApplication;\n"
                    "import org.springframework.boot.autoconfigure.domain.EntityScan;\n"
                    "import org.springframework.data.jpa.repository.config.EnableJpaRepositories;\n"
                    "\n"
                    "@SpringBootApplication(scanBasePackages = \"{scan}\")\n"
                    "@EntityScan(basePackages = \"{scan}\")\n"
                    "@EnableJpaRepositories(basePackages = \"{scan}\")\n"
                    "public class DemoApplication {\n"
                    "  public static void main(String[] args){ SpringApplication.run(DemoApplication.class, args); }\n"
                    "}\n"
                ).replace("{scan}", scan_base)
                zf.writestr(f"backend/src/main/java/{pkg_path}/{name}", main_src)
            # Cria POM mínimo se tivemos Java e nenhum POM foi escrito
            if saw_java and not pom_written:
                minimal_pom = (
                    "<project xmlns=\"http://maven.apache.org/POM/4.0.0\" xmlns:xsi=\"http://www.w3.org/2001/XMLSchema-instance\" xsi:schemaLocation=\"http://maven.apache.org/POM/4.0.0 http://maven.apache.org/xsd/maven-4.0.0.xsd\">\n"
                    "  <modelVersion>4.0.0</modelVersion>\n"
                    "  <parent>\n"
                    "    <groupId>org.springframework.boot</groupId>\n"
                    "    <artifactId>spring-boot-starter-parent</artifactId>\n"
                    "    <version>3.3.0</version>\n"
                    "    <relativePath/>\n"
                    "  </parent>\n"
                    "  <groupId>com.example</groupId>\n"
                    "  <artifactId>generated</artifactId>\n"
                    "  <version>0.1.0</version>\n"
                    "  <dependencies>\n"
                    "    <dependency>\n"
                    "      <groupId>org.springframework.boot</groupId>\n"
                    "      <artifactId>spring-boot-starter-web</artifactId>\n"
                    "    </dependency>\n"
                    "  </dependencies>\n"
                    "  <build>\n"
                    "    <plugins>\n"
                    "      <plugin>\n"
                    "        <groupId>org.springframework.boot</groupId>\n"
                    "        <artifactId>spring-boot-maven-plugin</artifactId>\n"
                    "      </plugin>\n"
                    "    </plugins>\n"
                    "  </build>\n"
                    "</project>\n"
                )
                zf.writestr("backend/pom.xml", minimal_pom)
            # Adiciona HealthController mínimo para facilitar teste em Java
            if saw_java:
                ctrl_pkg_path = "com/example/controller"
                ctrl_src = (
                    "package com.example.controller;\n"
                    "import org.springframework.web.bind.annotation.*;\n"
                    "import java.util.Map;\n"
                    "@RestController\n"
                    "@CrossOrigin(origins = \"*\")\n"
                    "public class HealthController {\n"
                    "  @GetMapping(\"/health\")\n"
                    "  public Map<String,String> health(){ return Map.of(\"status\", \"ok\"); }\n"
                    "}\n"
                )
                zf.writestr(f"backend/src/main/java/{ctrl_pkg_path}/HealthController.java", ctrl_src)
                # Configuração global de CORS para todos os endpoints
                cors_pkg_path = "com/example/config"
                cors_src = (
                    "package com.example.config;\n"
                    "import org.springframework.context.annotation.Bean;\n"
                    "import org.springframework.context.annotation.Configuration;\n"
                    "import org.springframework.web.servlet.config.annotation.CorsRegistry;\n"
                    "import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;\n\n"
                    "@Configuration\n"
                    "public class CorsConfig {\n"
                    "  @Bean\n"
                    "  public WebMvcConfigurer corsConfigurer() {\n"
                    "    return new WebMvcConfigurer() {\n"
                    "      @Override\n"
                    "      public void addCorsMappings(CorsRegistry registry) {\n"
                    "        registry.addMapping(\"/**\").allowedOrigins(\"*\").allowedMethods(\"*\").allowedHeaders(\"*\");\n"
                    "      }\n"
                    "    };\n"
                    "  }\n"
                    "}\n"
                )
                zf.writestr(f"backend/src/main/java/{cors_pkg_path}/CorsConfig.java", cors_src)

            # Atualiza frontend com porta adequada conforme stack detectada
            default_port = 5001 if has_flask else (3000 if has_express else (8080 if saw_java else 5001))
            desired_final = _postprocess_front_files(front_desired_original, base_url_hint="/api", default_port=default_port)
            for fn, content in desired_final.items():
                if content:
                    zf.writestr(f"frontend/{fn}", content)

            # Atualiza README com comandos por stack
            run_notes = "\nComo executar:\n"
            if has_flask:
                run_notes += (
                    "1) Backend (Flask)\n"
                    "   - pip install -r backend/requirements.txt\n"
                    "   - python -m flask --app backend.app:app run --port 5001\n"
                )
            if has_express:
                run_notes += (
                    "2) Backend (Node/Express)\n"
                    "   - cd backend\n"
                    "   - npm install\n"
                    "   - npm start\n"
                    "   - Verifique: GET http://localhost:3000/health\n"
                    "   - Verifique: GET http://localhost:3000/api/tasks e POST /api/tasks\n"
                )
            if saw_java:
                run_notes += (
                    "3) Backend (Java/Spring Boot)\n"
                    "   - mvn -f backend/pom.xml spring-boot:run\n"
                )
            run_notes += (
                "4) Frontend\n"
                "   - python -m http.server 5500\n"
                "   - Abra http://127.0.0.1:5500/frontend/index.html\n"
            )
            top_readme_updated = top_readme + "\n" + run_notes
            zf.writestr("README.md", top_readme_updated)

        # QA
        if qa:
            zf.writestr("qa/README.md", qa)
            qa_blocks = _extract_code_blocks(qa)
            for i, b in enumerate(qa_blocks, start=1):
                lang = (b.get("language") or "txt").lower()
                content = b.get("content") or ""
                fn = b.get("filename")
                if lang in ("javascript", "js"):
                    name = fn or ("login.test.js" if "login" in content.lower() else f"test_{i}.js")
                    zf.writestr(f"qa/{name}", content)
                else:
                    ext = b.get("language") or "txt"
                    name = fn or f"tests_example_{i}.{ext}"
                    zf.writestr(f"qa/{name}", content)

    mem.seek(0)
    return mem


def build_structured_zip(task: str, language: str, front: str, back: str, qa: str, preset: str = "flask", project_name: str = "projeto", group_id: str = "com.example", contract: dict | None = None, include_front: bool = True) -> io.BytesIO:
    """
    Gera um ZIP com estrutura de projeto completa baseada em 'preset':
      - flask: backend Python/Flask
      - express: backend Node.js/Express
      - spring: backend Java/Spring Boot (Maven)
    Integra os artefatos dos agentes em locais apropriados e mantém arquivos RAW.
    """
    mem = io.BytesIO()
    with zipfile.ZipFile(mem, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        # README top (conteúdo dinâmico conforme preset)
        if preset == "flask":
            backend_run = (
                "1) Backend (Flask)\n"
                "   - pip install -r backend/requirements.txt\n"
                "   - python -m flask --app backend.app:app run --port 5001\n"
            )
            api_port = 5001
        elif preset == "express":
            backend_run = (
                "1) Backend (Node/Express)\n"
                "   - cd backend\n"
                "   - npm install\n"
                "   - npm start\n"
            )
            api_port = 3000
        else:
            backend_run = (
                "1) Backend (Java/Spring Boot)\n"
                "   - mvn -f backend/pom.xml spring-boot:run\n"
            )
            api_port = 8080

        top_readme_structured = (
            f"# {project_name}\n\n"
            f"Preset: {preset}\n"
            f"Task: {task}\n"
            f"Language: {language}\n\n"
            "Este projeto foi gerado automaticamente com estrutura padrão.\n"
            "Arquivos RAW dos agentes são mantidos em frontend/FRONT_RAW.md e backend/README.md.\n\n"
            "Como executar:\n"
            f"{backend_run}"
            "2) Frontend\n"
            "   - python -m http.server 5500\n"
            "   - Abra: http://127.0.0.1:5500/frontend/index.html\n\n"
            f"Observação: o frontend usa `API_BASE` com fallback para `http://127.0.0.1:{api_port}/api`. Você pode sobrescrever via `window.API_BASE` ou adicionando `?api=http://127.0.0.1:{api_port}/api` na URL.\n"
            f"Verificação rápida: GET http://127.0.0.1:{api_port}/health e GET http://127.0.0.1:{api_port}/api/tasks (se houver blueprint `main`).\n\n"
            f"Endpoints padrão:\n"
            f"- GET http://127.0.0.1:{api_port}/health\n"
            f"- GET http://127.0.0.1:{api_port}/api/tasks\n"
f'- POST http://127.0.0.1:{api_port}/api/tasks Body: {{"task":"Nova tarefa"}}\n'
        )
        zf.writestr("README.md", top_readme_structured)

        # Enriquecimento de contrato com schema (se ausente) e gravação em docs
        def _infer_resource_name_from_endpoints(base: str, endpoints: list[dict]) -> str | None:
            try:
                for e in endpoints or []:
                    p = (e or {}).get("path") or ""
                    if p.startswith(base + "/"):
                        rel = p[len(base):]
                        if not rel.startswith("/"):
                            rel = "/" + rel
                        name = (rel[1:].split("/")[0]) or None
                        if name:
                            return name
                return None
            except Exception:
                return None

        def _derive_schema_from_contract(c: dict) -> list[dict]:
            base = (c or {}).get("base_url") or "/api"
            eps = (c or {}).get("endpoints") or []
            name = _infer_resource_name_from_endpoints(base, eps) or "items"
            schema: list[dict] = []
            body_types: dict[str, str] = {}
            try:
                for e in eps:
                    m = ((e or {}).get("method") or "GET").upper()
                    p = (e or {}).get("path") or ""
                    rel = p
                    if p.startswith(base):
                        rel = p[len(base):] or "/"
                    if not rel.startswith("/"):
                        rel = "/" + rel
                    if m == "POST" and rel == f"/{name}":
                        body = (e or {}).get("body") or {}
                        for k, t in (body.items() if isinstance(body, dict) else []):
                            body_types[str(k)] = str(t or "string")
            except Exception:
                pass
            if body_types:
                for k, t in body_types.items():
                    ty = "string"
                    tt = str(t).lower()
                    if tt in ("int", "integer", "number", "float", "double"): ty = "number"
                    elif tt in ("bool", "boolean"): ty = "boolean"
                    schema.append({"name": k, "type": ty, "required": True})
            else:
                schema.append({"name": "name", "type": "string", "required": True})
            return [{"name": name, "schema": schema}]

        contract_enriched = dict(contract or {})
        if not contract_enriched.get("resources"):
            try:
                contract_enriched["resources"] = _derive_schema_from_contract(contract_enriched)
            except Exception:
                contract_enriched["resources"] = [{"name": "items", "schema": [{"name": "name", "type": "string", "required": True}]}]
        try:
            zf.writestr("docs/api_contract.json", json.dumps(contract_enriched, ensure_ascii=False, indent=2))
        except Exception:
            pass
        contract = contract_enriched

        # Frontend opcional, só quando solicitado
        if include_front:
            front_blocks = _extract_code_blocks(front)
            desired = {"index.html": None, "styles.css": None, "script.js": None}
            for b in front_blocks:
                fn = (b.get("filename") or "").lower()
                if fn in desired and desired[fn] is None:
                    desired[fn] = b["content"]
            fb_idx = 0
            for key in desired:
                if desired[key] is None and fb_idx < len(front_blocks):
                    desired[key] = front_blocks[fb_idx]["content"]
                    fb_idx += 1
            # Pós-processa para garantir API_BASE e fallbacks conforme preset
            default_port = 5001 if preset == "flask" else (3000 if preset == "express" else 8080)
            desired = _postprocess_front_files(desired, base_url_hint="/api", default_port=default_port)

        def _fe_contract_endpoints(c: dict) -> list[dict]:
            arr: list[dict] = []
            if isinstance(c, dict):
                for e in c.get("endpoints", []) or []:
                    m = ((e or {}).get("method") or "GET").upper()
                    p = ((e or {}).get("path") or "").strip()
                    if p:
                        arr.append({"method": m, "path": p})
            return arr

        def _fe_base(c: dict, default: str) -> str:
            b = (c or {}).get("base_url") or default
            b = b if isinstance(b, str) else default
            if not b.startswith("/"):
                b = "/" + b
            return b

        feps = _fe_contract_endpoints(contract or {})
        base_front = _fe_base(contract or {}, "/api")

        def _discover_front_resource(endpoints: list[dict]) -> dict | None:
            for e in endpoints:
                p = (e.get("path") or "").strip()
                if not p:
                    continue
                rel = p
                if rel.startswith(base_front):
                    rel = rel[len(base_front):] or "/"
                if not rel.startswith("/"):
                    rel = "/" + rel
                m = re.match(r"^/([a-zA-Z0-9_-]+)(?:/.*)?$", rel)
                if m:
                    name = m.group(1)
                    return {"name": name}
            return None

        res_info = _discover_front_resource(feps)

        def _path_matches(p: str, path: str) -> bool:
            if not p:
                return False
            candidates = [path, f"{base_front}{path}"]
            # variantes com parâmetros: :id, {id}, <id>
            if path.endswith(":id"):
                base = path[:-3]
                candidates += [base + "{id}", base + "<id>", f"{base_front}{base}{{id}}", f"{base_front}{base}<id>"]
            elif path.endswith("/{id}"):
                base = path[:-5]
                candidates += [base + "/:id", base + "/<id>", f"{base_front}{base}/:id", f"{base_front}{base}/<id>"]
            elif path.endswith("/<id>"):
                base = path[:-5]
                candidates += [base + "/:id", base + "/{id}", f"{base_front}{base}/:id", f"{base_front}{base}/{id}"]
            return any(p == c for c in candidates)

        def _ep_exists(method: str, path: str) -> bool:
            for e in feps:
                m = (e.get("method") or "").upper()
                p = (e.get("path") or "").strip()
                if m == method.upper() and _path_matches(p, path):
                    return True
            return False

        if include_front:
            # A criação de index.html será feita após detectar o tipo de recurso (to‑do vs CRUD)
            desired["styles.css"] = (
                "body{font-family:Arial,Helvetica,sans-serif;padding:20px}"
                "h1{margin-bottom:16px}"
                ".form{margin-bottom:12px;display:flex;gap:8px;flex-wrap:wrap}"
                ".item{display:flex;gap:8px;align-items:center;margin:8px 0;flex-wrap:wrap}"
                ".item input,.item select{flex:1;padding:6px}"
                ".item button{padding:6px 10px}"
            )
            api_base_default = f"http://127.0.0.1:{api_port}{base_front}"
            schema_list = []
            try:
                resources = (contract or {}).get("resources") or []
                chosen = None
                for r in resources:
                    rn = (r or {}).get("name")
                    if (res_info or {}).get("name") and rn == (res_info or {}).get("name"):
                        chosen = r
                        break
                    if chosen is None:
                        chosen = r
                schema_list = (chosen or {}).get("schema") or []
            except Exception:
                schema_list = []
            schema_js = json.dumps(schema_list, ensure_ascii=False)
            resource_name = (res_info or {"name":"tasks"}).get("name") or "tasks"
            todo_names = {"tasks","todos","todo","tarefas"}
            has_bool = any((isinstance(f, dict) and (f.get("type") == "boolean")) for f in (schema_list or []))
            task_l = (task or "").lower()
            crud_in_task = ("crud" in task_l)
            # Dispara To-Do somente por termos específicos, não por "todos" em Português
            todo_triggers = ("to-do" in task_l) or ("todo" in task_l) or ("to do" in task_l) or ("lista de tarefas" in task_l) or ("checklist" in task_l) or ("afazeres" in task_l)
            is_todo_by_task = bool(todo_triggers and not crud_in_task)
            is_todo = bool(has_bool or is_todo_by_task or ((resource_name in todo_names) and not crud_in_task))
            title_res = resource_name.capitalize()
            desired["index.html"] = (
                "<!DOCTYPE html>\n"
                "<html lang=\"pt-BR\">\n"
                "<head>\n"
                "  <meta charset=\"UTF-8\" />\n"
                "  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\" />\n"
                + (f"  <title>To-Do List de {title_res}</title>\n" if is_todo else f"  <title>CRUD de {title_res}</title>\n") +
                "  <link rel=\"stylesheet\" href=\"styles.css\" />\n"
                "</head>\n"
                "<body>\n"
                + (f"  <h1>To-Do List de {title_res}</h1>\n" if is_todo else f"  <h1>CRUD de {title_res}</h1>\n") +
                "  <div class=\"form\" id=\"form\"></div>\n"
                "  <button id=\"add-btn\">Adicionar</button>\n"
                "  <div id=\"list\"></div>\n"
                "  <script src=\"script.js\"></script>\n"
                "</body>\n"
                "</html>\n"
            )
            resource_name = (res_info or {"name":"tasks"}).get("name") or "tasks"
            todo_names = {"tasks","todos","todo","tarefas"}
            has_bool = any((isinstance(f, dict) and (f.get("type") == "boolean")) for f in (schema_list or []))
            task_l = (task or "").lower()
            crud_in_task = ("crud" in task_l)
            todo_triggers = ("to-do" in task_l) or ("todo" in task_l) or ("to do" in task_l) or ("lista de tarefas" in task_l) or ("checklist" in task_l) or ("afazeres" in task_l)
            is_todo_by_task = bool(todo_triggers and not crud_in_task)
            is_todo = bool(has_bool or is_todo_by_task or ((resource_name in todo_names) and not crud_in_task))
            if is_todo:
                desired["script.js"] = (
                    "const API_BASE=(function(){const p=new URLSearchParams(window.location.search);return window.API_BASE||p.get('api')||'"
                    + api_base_default + "';})();\n"
                    f"const RESOURCE='{resource_name}';\n"
                    f"const SCHEMA={schema_js};\n"
                    "const listEl=document.getElementById('list');\n"
                    "const formEl=document.getElementById('form');\n"
                    "const addBtn=document.getElementById('add-btn');\n"
                    "function boolField(){ const f=(SCHEMA||[]).find(x=>x&&x.type==='boolean'); return (f&&f.name)||'done'; }\n"
                    "function buildForm(){ formEl.innerHTML=''; const i=document.createElement('input'); i.type='text'; i.id='new-name'; i.placeholder='Nova tarefa'; i.autocomplete='off'; i.setAttribute('aria-label','Nova tarefa'); formEl.appendChild(i); }\n"
                    "buildForm();\n"
                    "function join(base, path){ const b=String(base||'').replace(/\\/+$/,''); const p=String(path||'').replace(/^\\+/,''); return b + '/' + p; }\n"
                    "async function loadItems(){ try{ const r=await fetch(join(API_BASE, RESOURCE)); if(!r.ok) throw new Error('HTTP '+r.status); const data=await r.json(); const items = Array.isArray(data) ? data : (Array.isArray(data.items)?data.items:(Array.isArray(data.content)?data.content:[])); render(items); } catch(e){ console.error('GET failed', e); listEl.innerHTML='<div>API indisponível</div>'; } }\n"
                    "function render(items){ listEl.innerHTML=''; const bf=boolField(); for(const t of items){ const rid=String(t.id ?? t._id ?? ''); const row=document.createElement('div'); row.className='item'; const chk=document.createElement('input'); chk.type='checkbox'; chk.checked=Boolean(t[bf]??false); chk.onchange=()=>toggleItem((t.id??t._id), chk.checked, bf); const span=document.createElement('span'); span.textContent=String(t.name ?? t.title ?? rid); if(chk.checked){ span.style.textDecoration='line-through'; span.style.opacity='0.7'; } const del=document.createElement('button'); del.textContent='Excluir'; del.onclick=()=>deleteItem((t.id??t._id)); row.appendChild(chk); row.appendChild(span); row.appendChild(del); listEl.appendChild(row); } }\n"
                    "async function addItem(){ try{ const n=(document.getElementById('new-name').value||'').trim(); if(!n){ console.error('Campo name é obrigatório'); return; } const bf=boolField(); const body={ name:n }; body[bf]=false; const r=await fetch(join(API_BASE, RESOURCE),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}); if(!r.ok) throw new Error('HTTP '+r.status); document.getElementById('new-name').value=''; await loadItems(); } catch(e){ console.error('POST failed', e); } }\n"
                    "async function toggleItem(id,val,bf){ try{ const body={}; body[bf]=Boolean(val); const r=await fetch(join(API_BASE, RESOURCE + '/' + encodeURIComponent(id)),{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}); if(!r.ok) throw new Error('HTTP '+r.status); await loadItems(); } catch(e){ console.error('PUT failed', e); } }\n"
                    "async function deleteItem(id){ try{ const r=await fetch(join(API_BASE, RESOURCE + '/' + encodeURIComponent(id)),{method:'DELETE'}); if(!r.ok) throw new Error('HTTP '+r.status); await loadItems(); } catch(e){ console.error('DELETE failed', e); } }\n"
                    "addBtn.onclick=addItem;\n"
                    "loadItems();\n"
                )
            else:
                desired["script.js"] = (
                    "const API_BASE=(function(){const p=new URLSearchParams(window.location.search);return window.API_BASE||p.get('api')||'"
                    + api_base_default + "';})();\n"
                    f"const RESOURCE='{resource_name}';\n"
                    f"const SCHEMA={schema_js};\n"
                    "const listEl=document.getElementById('list');\n"
                    "const formEl=document.getElementById('form');\n"
                    "const addBtn=document.getElementById('add-btn');\n"
                    "function buildForm(){ const defs=(SCHEMA&&SCHEMA.length)?SCHEMA:[{name:'name',type:'string',required:true}]; formEl.innerHTML=''; for(const f of defs){ let input; if(f.type==='number'){ input=document.createElement('input'); input.type='number'; } else if(f.type==='boolean'){ input=document.createElement('input'); input.type='checkbox'; } else if(f.type==='enum' && Array.isArray(f.values)){ input=document.createElement('select'); for(const v of f.values){ const o=document.createElement('option'); o.value=String(v); o.textContent=String(v); input.appendChild(o);} } else { input=document.createElement('input'); input.type='text'; } input.id='new-'+f.name; input.name=f.name; input.placeholder=f.name; input.autocomplete='off'; input.setAttribute('aria-label',f.name); formEl.appendChild(input);} }\n"
                    "buildForm();\n"
                    "function join(base, path){ const b=String(base||'').replace(/\\/+$/,''); const p=String(path||'').replace(/^\\+/,''); return b + '/' + p; }\n"
                    "async function loadItems(){ try{ const r=await fetch(join(API_BASE, RESOURCE)); if(!r.ok) throw new Error('HTTP '+r.status); const data=await r.json(); const items = Array.isArray(data) ? data : (Array.isArray(data.items)?data.items:(Array.isArray(data.content)?data.content:[])); render(items); } catch(e){ console.error('GET failed', e); listEl.innerHTML='<div>API indisponível</div>'; } }\n"
                    "function render(items){ listEl.innerHTML=''; const defs=(SCHEMA&&SCHEMA.length)?SCHEMA:[{name:'name',type:'string',required:true}]; for(const t of items){ const row=document.createElement('div'); row.className='item'; const rid=String(t.id ?? t._id ?? ''); for(const f of defs){ let input; if(f.type==='number'){ input=document.createElement('input'); input.type='number'; input.value=(t[f.name]??''); } else if(f.type==='boolean'){ input=document.createElement('input'); input.type='checkbox'; input.checked=Boolean(t[f.name]??false); } else if(f.type==='enum' && Array.isArray(f.values)){ input=document.createElement('select'); for(const v of f.values){ const o=document.createElement('option'); o.value=String(v); o.textContent=String(v); if(String(t[f.name])===String(v)) o.selected=true; input.appendChild(o);} } else { input=document.createElement('input'); input.type='text'; input.value=String(t[f.name]??''); } input.id='row-'+rid+'-'+f.name; input.name=f.name; input.placeholder=f.name; input.autocomplete='off'; input.setAttribute('aria-label',f.name); row.appendChild(input);} const saveBtn=document.createElement('button'); saveBtn.textContent='Salvar'; saveBtn.onclick=()=>{ const body=collectRow(rid); updateItem((t.id ?? t._id),body); }; const delBtn=document.createElement('button'); delBtn.textContent='Excluir'; delBtn.onclick=()=>deleteItem((t.id ?? t._id)); row.appendChild(saveBtn); row.appendChild(delBtn); listEl.appendChild(row);} }\n"
                    "function collectNew(){ const defs=(SCHEMA&&SCHEMA.length)?SCHEMA:[{name:'name',type:'string',required:true}]; const body={}; for(const f of defs){ const el=document.getElementById('new-'+f.name); if(!el) continue; if(f.type==='boolean'){ body[f.name]=Boolean(el.checked); } else if(f.type==='number'){ const v=String(el.value||''); body[f.name]=v?Number(v):null; } else { body[f.name]=String(el.value||''); } } for(const f of defs){ if(f.required && (body[f.name]===undefined || body[f.name]===null || body[f.name]==='')){ return {error:'Campo '+f.name+' é obrigatório'}; } } return body; }\n"
                    "function collectRow(rid){ const defs=(SCHEMA&&SCHEMA.length)?SCHEMA:[{name:'name',type:'string',required:true}]; const body={}; for(const f of defs){ const el=document.getElementById('row-'+rid+'-'+f.name); if(!el) continue; if(f.type==='boolean'){ body[f.name]=Boolean(el.checked); } else if(f.type==='number'){ const v=String(el.value||''); body[f.name]=v?Number(v):null; } else { body[f.name]=String(el.value||''); } } return body; }\n"
                    "async function addItem(){ try{ const body=collectNew(); if(body.error){ console.error(body.error); return; } const r=await fetch(join(API_BASE, RESOURCE),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}); if(!r.ok) throw new Error('HTTP '+r.status); formEl.querySelectorAll('input,select').forEach(e=>{if(e.type==='checkbox')e.checked=false; else e.value='';}); await loadItems(); } catch(e){ console.error('POST failed', e); } }\n"
                    "async function updateItem(id,body){ try{ const r=await fetch(join(API_BASE, RESOURCE + '/' + encodeURIComponent(id)),{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}); if(!r.ok) throw new Error('HTTP '+r.status); await loadItems(); } catch(e){ console.error('PUT failed', e); } }\n"
                    "async function deleteItem(id){ try{ const r=await fetch(join(API_BASE, RESOURCE + '/' + encodeURIComponent(id)),{method:'DELETE'}); if(!r.ok) throw new Error('HTTP '+r.status); await loadItems(); } catch(e){ console.error('DELETE failed', e); } }\n"
                    "addBtn.onclick=addItem;\n"
                    "loadItems();\n"
                )
        if include_front:
            for fn, content in desired.items():
                if content:
                    zf.writestr(f"frontend/{fn}", content)
            if front:
                zf.writestr("frontend/FRONT_RAW.md", front)

        def _contract_endpoints(c: dict) -> list[dict]:
            eps: list[dict] = []
            if isinstance(c, dict):
                for e in c.get("endpoints", []) or []:
                    m = ((e or {}).get("method") or "GET").upper()
                    p = ((e or {}).get("path") or "").strip()
                    if p:
                        eps.append({"method": m, "path": p})
            return eps

        def _normalize_base(c: dict, default: str) -> str:
            b = (c or {}).get("base_url") or default
            b = b if isinstance(b, str) else default
            if not b.startswith("/"):
                b = "/" + b
            return b

        eps = _contract_endpoints(contract or {})
        base_url = _normalize_base(contract or {}, "/api")

        # Presets para backend
        if preset == "flask":
            zf.writestr("backend/requirements.txt", "flask\nitsdangerous\nflask-cors\npython-dotenv\n")
            # Força porta 5001 ao usar `flask run` sem --port
            zf.writestr("backend/.flaskenv", "FLASK_APP=backend.app:app\nFLASK_RUN_PORT=5001\n")
            zf.writestr(
                "backend/app/__init__.py",
                """from flask import Flask, Blueprint\nfrom flask_cors import CORS\nimport pkgutil, importlib\n\napp = Flask(__name__)\nCORS(app)\n\n@app.get('/health')\ndef _health():\n    return {"status": "ok"}\n\n# Registra explicitamente o Blueprint 'main' e depois faz auto-discovery\ndef _register_blueprints():\n    # Registro explícito do 'main' se existir\n    try:\n        from .main import main as main_bp\n        if 'main' not in app.blueprints:\n            app.register_blueprint(main_bp)\n    except Exception as e:\n        print(f"[app] Falha ao registrar blueprint 'main': {e}")\n\n    # Auto-discovery de Blueprints em backend/app/*\n    try:\n        for _, modname, _ in pkgutil.iter_modules(__path__):\n            try:\n                m = importlib.import_module(f"{__name__}.{modname}")\n                for attr_name in dir(m):\n                    obj = getattr(m, attr_name)\n                    if isinstance(obj, Blueprint) and obj.name not in app.blueprints:\n                        app.register_blueprint(obj)\n            except Exception as e:\n                print(f"[app] Ignorando módulo {modname}: {e}")\n    except Exception as e:\n        print(f"[app] Falha ao varrer blueprints: {e}")\n\n    print(f"[app] Blueprints registrados: {list(app.blueprints.keys())}")\n\n_register_blueprints()\n"""
            )
            if not re.search(r"backend/app/main\.py", back or "", re.IGNORECASE):
                if eps:
                    # descobre recurso principal
                    try:
                        first_path = None
                        for _e in eps:
                            _p = (_e.get('path') or '')
                            if _p.startswith(base_url + '/'):
                                first_path = _p
                                break
                        if first_path:
                            rel0 = first_path[len(base_url):]
                            if not rel0.startswith('/'):
                                rel0 = '/' + rel0
                            resource_name = (rel0[1:].split('/')[0]) or 'items'
                        else:
                            resource_name = 'items'
                    except Exception:
                        resource_name = 'items'

                    lines = []
                    lines.append("from flask import Blueprint, jsonify, request")
                    lines.append(f"main = Blueprint('main', __name__, url_prefix='{base_url}')")
                    try:
                        _schema = None
                        _resources = (contract or {}).get("resources") or []
                        for _r in _resources:
                            if (_r or {}).get("name") == resource_name:
                                _schema = (_r or {}).get("schema")
                                break
                            if _schema is None:
                                _schema = (_r or {}).get("schema")
                        _required = [ (f or {}).get("name") for f in (_schema or []) if (f or {}).get("required") ]
                    except Exception:
                        _required = []
                    # Sanitiza campos obrigatórios
                    valid_required = [x for x in (_required or []) if isinstance(x, str) and re.match(r"^[A-Za-z][A-Za-z0-9_]{0,30}$", x)]
                    if not valid_required:
                        valid_required = ['name']
                    lines.append("REQUIRED = " + json.dumps(valid_required, ensure_ascii=False))
                    lines.append("items = []")
                    lines.append("current_id = 1")
                    for e in eps:
                        p = e.get("path") or ""
                        m = (e.get("method") or "GET").upper()
                        rel = p
                        if p.startswith(base_url):
                            rel = p[len(base_url):] or "/"
                        if not rel.startswith("/"):
                            rel = "/" + rel
                        coll_rel = f"/{resource_name}"
                        item_variants = {f"/{resource_name}/:id", f"/{resource_name}/{{id}}", f"/{resource_name}/<id>"}
                        rel_flask = rel.replace("/:id", "/<id>").replace("/{id}", "/<id>")
                        func = f"ep_{m.lower()}_{re.sub(r'[^a-z0-9]+','_', rel_flask.strip('/')).strip('_') or 'root'}"
                        lines.append(f"@main.route('{rel_flask}', methods=['{m}'])")
                        if rel == coll_rel and m == "GET":
                            lines.append(f"def {func}():")
                            lines.append("    return jsonify(items)")
                        elif rel == coll_rel and m == "POST":
                            lines.append(f"def {func}():")
                            lines.append("    data = (request.get_json(silent=True) or {})")
                            lines.append("    for k in REQUIRED:\n        val = data.get(k)\n        if val is None or val == '':\n            return jsonify({'error': f'Campo {k} é obrigatório'}), 400")
                            lines.append("    it = {'id': current_id}")
                            lines.append("    for k, v in data.items():\n        if k != 'id':\n            it[k] = v")
                            lines.append("    if it.get('name') is None and it.get('title') is not None:\n        it['name'] = it.get('title')")
                            lines.append("    current_id += 1")
                            lines.append("    items.append(it)")
                            lines.append("    return jsonify(it), 201")
                        elif rel in item_variants and m == "PUT":
                            lines.append(f"def {func}(id):")
                            lines.append("    data = (request.get_json(silent=True) or {})")
                            lines.append("    for it in items:")
                            lines.append("        if str(it.get('id')) == str(id):")
                            lines.append("            for k, v in data.items():\n                if k != 'id':\n                    it[k] = v")
                            lines.append("            if data.get('name') is None and data.get('title') is not None:\n                it['name'] = data.get('title')")
                            lines.append("            return jsonify(it)")
                            lines.append("    return jsonify({'error': 'Item não encontrado'}), 404")
                        elif rel in item_variants and m == "DELETE":
                            lines.append(f"def {func}(id):")
                            lines.append("    for i, it in enumerate(items):")
                            lines.append("        if str(it.get('id')) == str(id):")
                            lines.append("            items.pop(i)")
                            lines.append("            return ('', 204)")
                            lines.append("    return jsonify({'error': 'Item não encontrado'}), 404")
                        else:
                            lines.append(f"def {func}():")
                            lines.append("    return jsonify({'ok': True})")
                    zf.writestr("backend/app/main.py", "\n".join(lines))
                else:
                    zf.writestr(
                        "backend/app/main.py",
                        "from flask import Blueprint, jsonify\nmain = Blueprint('main', __name__, url_prefix='/api')\n@main.route('/tasks', methods=['GET'])\ndef get_tasks():\n    return jsonify({'tasks': []})\n"
                    )
        elif preset == "express":
            pkg = """{\n  \"name\": \"{name}\",\n  \"version\": \"0.1.0\",\n  \"private\": true,\n  \"scripts\": {\n    \"start\": \"node src/index.js\"\n  },\n  \"dependencies\": {\n    \"express\": \"^4.18.2\",\n    \"cors\": \"^2.8.5\"\n  }\n}\n""".replace("{name}", project_name)
            zf.writestr("backend/package.json", pkg)
            # Para robustez, geramos servidor Express do zero a partir do contrato
            if eps:
                parts = []
                parts.append("const express = require('express')")
                parts.append("const cors = require('cors')")
                parts.append("const app = express()")
                parts.append("const PORT = process.env.PORT || 3000")
                parts.append("app.use(cors())")
                parts.append("app.options('*', cors())")
                parts.append("app.use(express.json())")
                parts.append("app.get('/health', (req,res)=>res.json({status:'ok'}))")
                # descobre recurso principal (Python) e injeta como constante JS
                try:
                    first_path = None
                    for _e in eps:
                        _p = (_e.get('path') or '')
                        if _p.startswith(base_url + '/'):
                            first_path = _p
                            break
                    if first_path:
                        rel = first_path[len(base_url):]
                        if not rel.startswith('/'):
                            rel = '/' + rel
                        resource_name = (rel[1:].split('/')[0]) or 'tasks'
                    else:
                        resource_name = 'tasks'
                except Exception:
                    resource_name = 'tasks'
                parts.append("const RESOURCE = '" + resource_name + "'")
                try:
                    _schema = None
                    _resources = (contract or {}).get("resources") or []
                    for _r in _resources:
                        if (_r or {}).get("name") == resource_name:
                            _schema = (_r or {}).get("schema")
                            break
                        if _schema is None:
                            _schema = (_r or {}).get("schema")
                    _required = [ (f or {}).get("name") for f in (_schema or []) if (f or {}).get("required") ]
                except Exception:
                    _required = []
                # Sanitiza campos obrigatórios: mantém apenas nomes alfanuméricos/underscore; fallback para ['name']
                valid_required = [x for x in (_required or []) if isinstance(x, str) and re.match(r"^[A-Za-z][A-Za-z0-9_]{0,30}$", x)]
                if not valid_required:
                    valid_required = ['name']
                parts.append("const REQUIRED = " + json.dumps(valid_required, ensure_ascii=False))
                parts.append("let items = []")
                parts.append("let currentId = 1")
                has_get_coll = False
                has_post_coll = False
                has_put_item = False
                has_delete_item = False
                for e in eps:
                    m = (e.get('method') or 'GET').lower()
                    p = e.get('path') or ''
                    path = p if p.startswith('/') else '/' + p
                    if base_url and not path.startswith(base_url):
                        path_full = base_url + (path if path != '/' else '')
                    else:
                        path_full = path
                    # normaliza caminhos do recurso principal
                    coll = f"{base_url}/" + resource_name
                    item = f"{base_url}/" + resource_name + "/:id"
                    if path_full == coll:
                        if m == 'get':
                            parts.append("app.get('" + coll + "', (req,res)=>res.json(items))")
                            has_get_coll = True
                        elif m == 'post':
                            parts.append("app.post('" + coll + "', (req,res)=>{ const body = req.body || {}; for(const k of REQUIRED){ if(body[k]===undefined || body[k]===null || body[k]===''){ return res.status(400).json({ error: 'Campo '+k+' é obrigatório' }); } } const it = { id: currentId++ }; for(const k in body){ if(k!=='id') it[k]=body[k]; } if(it.name===undefined && it.title!==undefined){ it.name=it.title; } items.push(it); res.status(201).json(it); })")
                            has_post_coll = True
                        else:
                            parts.append(f"app.{m}('{path_full}', (req,res)=>res.json({{ ok: true }}))")
                    elif path_full == item:
                        if m == 'put':
                            parts.append("app.put('" + item + "', (req,res)=>{ const { id } = req.params; const body = req.body || {}; const t = items.find(x=>String(x.id)===String(id)); if(!t) return res.status(404).json({ error: 'Item não encontrado' }); for(const k in body){ if(k!=='id') t[k]=body[k]; } if(body.name===undefined && body.title!==undefined){ t.name=body.title; } res.json(t); })")
                            has_put_item = True
                        elif m == 'delete':
                            parts.append("app.delete('" + item + "', (req,res)=>{ const { id } = req.params; const i = items.findIndex(x=>String(x.id)===String(id)); if(i<0) return res.status(404).json({ error: 'Item não encontrado' }); items.splice(i,1); res.status(204).end(); })")
                            has_delete_item = True
                        else:
                            parts.append(f"app.{m}('{path_full}', (req,res)=>res.json({{ ok: true }}))")
                    else:
                        parts.append(f"app.{m}('{path_full}', (req,res)=>res.json({{ ok: true }}))")
                coll2 = f"{base_url}/" + resource_name
                item2 = coll2 + ":id"
                tl = (task or "").lower()
                crud_in_task = ("crud" in tl)
                # Termos que indicam claramente To-Do
                todo_triggers = ("to-do" in tl) or ("todo" in tl) or ("to do" in tl) or ("lista de tarefas" in tl) or ("checklist" in tl) or ("afazeres" in tl)
                is_todo_expr = (((resource_name.lower() in ("tasks","todos","todo","tarefas")) and not crud_in_task) or (todo_triggers and not crud_in_task))
                if not has_get_coll:
                    parts.append("app.get('" + coll2 + "', (req,res)=>res.json(items))")
                if not has_post_coll:
                    if is_todo_expr:
                        parts.append("app.post('" + coll2 + "', (req,res)=>{ const body = req.body || {}; for(const k of REQUIRED){ if(body[k]===undefined || body[k]===null || body[k]===''){ return res.status(400).json({ error: 'Campo '+k+' é obrigatório' }); } } const it = { id: currentId++, name: String(body.name||'') }; it.done = body.done===undefined ? false : !!body.done; items.push(it); res.status(201).json(it); })")
                    else:
                        parts.append("app.post('" + coll2 + "', (req,res)=>{ const body = req.body || {}; for(const k of REQUIRED){ if(body[k]===undefined || body[k]===null || body[k]===''){ return res.status(400).json({ error: 'Campo '+k+' é obrigatório' }); } } const it = { id: currentId++ }; for(const k in body){ if(k!=='id') it[k]=body[k]; } if(it.name===undefined && it.title!==undefined){ it.name=it.title; } items.push(it); res.status(201).json(it); })")
                if not has_put_item:
                    if is_todo_expr:
                        parts.append("app.put('" + item2 + "', (req,res)=>{ const id = String((req.params.id||'')).replace(/^\/+|\/+$/g,''); const body = req.body || {}; const t = items.find(x=>String(x.id)===id); if(!t) return res.status(404).json({ error: 'Item não encontrado' }); if(body.name!==undefined){ t.name=String(body.name||''); } if(body.done!==undefined){ t.done=!!body.done; } res.json(t); })")
                    else:
                        parts.append("app.put('" + item2 + "', (req,res)=>{ const { id } = req.params; const body = req.body || {}; const t = items.find(x=>String(x.id)===String(id)); if(!t) return res.status(404).json({ error: 'Item não encontrado' }); for(const k in body){ if(k!=='id') t[k]=body[k]; } if(body.name===undefined && body.title!==undefined){ t.name=body.title; } res.json(t); })")
                if not has_delete_item:
                    parts.append("app.delete('" + item2 + "', (req,res)=>{ const { id } = req.params; const i = items.findIndex(x=>String(x.id)===String(id)); if(i<0) return res.status(404).json({ error: 'Item não encontrado' }); items.splice(i,1); res.status(204).end(); })")
                parts.append("app.listen(PORT, ()=>console.log('Server on ' + PORT))")
                zf.writestr("backend/src/index.js", "\n".join(parts))
            else:
                try:
                    resource = _infer_resource(task or "", front, back, qa)
                except Exception:
                    resource = "users"
                zf.writestr("backend/src/index.js", _build_express_crud(resource))
        elif preset == "spring":
            pom = f"""
<project xmlns=\"http://maven.apache.org/POM/4.0.0\" xmlns:xsi=\"http://www.w3.org/2001/XMLSchema-instance\" xsi:schemaLocation=\"http://maven.apache.org/POM/4.0.0 http://maven.apache.org/xsd/maven-4.0.0.xsd\">
  <modelVersion>4.0.0</modelVersion>
  <parent>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-parent</artifactId>
    <version>3.3.0</version>
    <relativePath/>
  </parent>
  <groupId>{group_id}</groupId>
  <artifactId>{project_name}</artifactId>
  <version>0.1.0</version>
  <properties>
    <java.version>17</java.version>
  </properties>
  <dependencies>
    <dependency>
      <groupId>org.springframework.boot</groupId>
      <artifactId>spring-boot-starter-web</artifactId>
    </dependency>
    <dependency>
      <groupId>org.springframework.boot</groupId>
      <artifactId>spring-boot-starter-data-jpa</artifactId>
    </dependency>
    <dependency>
      <groupId>jakarta.persistence</groupId>
      <artifactId>jakarta.persistence-api</artifactId>
    </dependency>
    <dependency>
      <groupId>com.h2database</groupId>
      <artifactId>h2</artifactId>
      <scope>runtime</scope>
    </dependency>
  </dependencies>
  <build>
    <plugins>
      <plugin>
        <groupId>org.springframework.boot</groupId>
        <artifactId>spring-boot-maven-plugin</artifactId>
      </plugin>
    </plugins>
  </build>
</project>
"""
            zf.writestr("backend/pom.xml", pom)
            base_path = group_id.replace(".", "/")
            app_name = f"{project_name.capitalize()}Application"
            # Define base para scan: usa raiz do group_id (ex.: com.example)
            scan_base = ".".join(group_id.split(".")[:2]) or group_id
            zf.writestr(
                f"backend/src/main/java/{base_path}/{app_name}.java",
                """package {group};
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.autoconfigure.domain.EntityScan;
import org.springframework.data.jpa.repository.config.EnableJpaRepositories;

@SpringBootApplication(scanBasePackages = "{scan}")
@EntityScan(basePackages = "{scan}")
@EnableJpaRepositories(basePackages = "{scan}")
public class {app} {
  public static void main(String[] args){ SpringApplication.run({app}.class, args); }
}
""".replace("{group}", group_id).replace("{app}", app_name).replace("{scan}", scan_base)
            )
            # configuração mínima para JPA + H2
            zf.writestr("backend/src/main/resources/application.yml", """
spring:
  datasource:
    url: jdbc:h2:mem:testdb
    driverClassName: org.h2.Driver
    username: sa
    password: ""
  jpa:
    hibernate:
      ddl-auto: create-drop
    properties:
      hibernate:
        globally_quoted_identifiers: true
    show-sql: true
  h2:
    console:
      enabled: true
""")
            ctrl_pkg_path = group_id.replace('.', '/') + "/controller"
            if eps:
                base = base_url
                cls = "ApiController"
                # descobre recurso principal
                try:
                    first_path = None
                    for _e in eps:
                        _p = (_e.get('path') or '')
                        if _p.startswith(base + '/'):
                            first_path = _p
                            break
                    if first_path:
                        rel0 = first_path[len(base):]
                        if not rel0.startswith('/'):
                            rel0 = '/' + rel0
                        resource_name = (rel0[1:].split('/')[0]) or 'items'
                    else:
                        resource_name = 'items'
                except Exception:
                    resource_name = 'items'
                lines = []
                lines.append(f"package {group_id}.controller;")
                lines.append("import org.springframework.web.bind.annotation.*;")
                lines.append("import java.util.*;")
                lines.append("@RestController")
                lines.append("@CrossOrigin(origins = \"*\")")
                lines.append(f"@RequestMapping(\"{base}\")")
                lines.append(f"public class {cls} {{")
                try:
                    _schema = None
                    _resources = (contract or {}).get("resources") or []
                    for _r in _resources:
                        if (_r or {}).get("name") == resource_name:
                            _schema = (_r or {}).get("schema")
                            break
                        if _schema is None:
                            _schema = (_r or {}).get("schema")
                    _required = [ (f or {}).get("name") for f in (_schema or []) if (f or {}).get("required") ]
                except Exception:
                    _required = []
                # Sanitiza campos obrigatórios
                valid_required = [x for x in (_required or []) if isinstance(x, str) and re.match(r"^[A-Za-z][A-Za-z0-9_]{0,30}$", x)]
                if not valid_required:
                    valid_required = ['name']
                req_java = ", ".join(["\"" + x + "\"" for x in valid_required])
                lines.append(f"  private java.util.List<String> REQUIRED = java.util.List.of({req_java});")
                lines.append("  private List<Map<String,Object>> items = new ArrayList<>();")
                lines.append("  private int currentId = 1;")
                for e in eps:
                    m = (e.get('method') or 'GET').upper()
                    p = e.get('path') or ''
                    rel = p
                    if p.startswith(base):
                        rel = p[len(base):] or "/"
                    if not rel.startswith("/"):
                        rel = "/" + rel
                    coll_rel = f"/{resource_name}"
                    item_variants = {f"/{resource_name}/:id", f"/{resource_name}/{{id}}", f"/{resource_name}/<id>"}
                    spring_rel = rel.replace("/:id", "/{id}").replace("/<id>", "/{id}")
                    func = f"ep_{m.lower()}_{re.sub(r'[^a-z0-9]+','_', spring_rel.strip('/')).strip('_') or 'root'}"
                    if rel == coll_rel and m == "GET":
                        lines.append(f"  @GetMapping(\"{coll_rel}\")")
                        lines.append(f"  public List<Map<String,Object>> {func}() {{ return items; }}")
                    elif rel == coll_rel and m == "POST":
                        lines.append(f"  @PostMapping(\"{coll_rel}\")")
                        lines.append(f"  public Map<String,Object> {func}(@RequestBody Map<String,Object> body) {{")
                        lines.append("    for(String k : REQUIRED){ Object v = body.get(k); if(v == null || String.valueOf(v).isEmpty()){ return Map.of(\"error\", \"Campo "+k+" é obrigatório\"); } }")
                        lines.append("    Map<String,Object> it = new HashMap<>();")
                        lines.append("    it.put(\"id\", currentId++);")
                        lines.append("    for(Map.Entry<String,Object> e : body.entrySet()){ if(!\"id\".equals(e.getKey())) it.put(e.getKey(), e.getValue()); }")
                        lines.append("    if(it.get(\"name\") == null && it.get(\"title\") != null){ it.put(\"name\", String.valueOf(it.get(\"title\"))); }")
                        lines.append("    items.add(it);")
                        lines.append("    return it;")
                        lines.append("  }")
                    elif rel in item_variants and m == "PUT":
                        lines.append(f"  @PutMapping(\"{spring_rel}\")")
                        lines.append(f"  public Map<String,Object> {func}(@PathVariable String id, @RequestBody Map<String,Object> body) {{")
                        lines.append("    for(Map<String,Object> it : items){ if(String.valueOf(it.get(\"id\")).equals(String.valueOf(id))){ for(Map.Entry<String,Object> e : body.entrySet()){ if(!\"id\".equals(e.getKey())) it.put(e.getKey(), e.getValue()); } if(body.get(\"name\") == null && body.get(\"title\") != null){ it.put(\"name\", String.valueOf(body.get(\"title\"))); } return it; } }")
                        lines.append("    return Map.of(\"error\", \"Item não encontrado\");")
                        lines.append("  }")
                    elif rel in item_variants and m == "DELETE":
                        lines.append(f"  @DeleteMapping(\"{spring_rel}\")")
                        lines.append(f"  public Map<String,Object> {func}(@PathVariable String id) {{")
                        lines.append("    for(int i=0;i<items.size();i++){ Map<String,Object> it = items.get(i); if(String.valueOf(it.get(\"id\")).equals(String.valueOf(id))){ items.remove(i); return Map.of(\"ok\", true); } }")
                        lines.append("    return Map.of(\"error\", \"Item não encontrado\");")
                        lines.append("  }")
                    else:
                        lines.append(f"  @RequestMapping(\"{spring_rel}\")")
                        lines.append(f"  public Map<String,Object> {func}() {{ return Map.of(\"ok\", true); }}")
                lines.append("}")
                zf.writestr(f"backend/src/main/java/{ctrl_pkg_path}/{cls}.java", "\n".join(lines))
            else:
                ctrl_src = (
                    f"package {group_id}.controller;\n"
                    "import org.springframework.web.bind.annotation.*;\n"
                    "import java.util.Map;\n"
                    "@RestController\n"
                    "@CrossOrigin(origins = \"*\")\n"
                    "public class HealthController {\n"
                    "  @GetMapping(\"/health\")\n"
                    "  public Map<String,String> health(){ return Map.of(\"status\", \"ok\"); }\n"
                    "}\n"
                )
                zf.writestr(f"backend/src/main/java/{ctrl_pkg_path}/HealthController.java", ctrl_src)
            # Configuração global de CORS para todos os endpoints
            cors_pkg_path = group_id.replace('.', '/') + "/config"
            cors_src = (
                f"package {group_id}.config;\n"
                "import org.springframework.context.annotation.Bean;\n"
                "import org.springframework.context.annotation.Configuration;\n"
                "import org.springframework.web.servlet.config.annotation.CorsRegistry;\n"
                "import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;\n\n"
                "@Configuration\n"
                "public class CorsConfig {\n"
                "  @Bean\n"
                "  public WebMvcConfigurer corsConfigurer() {\n"
                "    return new WebMvcConfigurer() {\n"
                "      @Override\n"
                "      public void addCorsMappings(CorsRegistry registry) {\n"
                "        registry.addMapping(\"/**\").allowedOrigins(\"*\").allowedMethods(\"*\").allowedHeaders(\"*\");\n"
                "      }\n"
                "    };\n"
                "  }\n"
                "}\n"
            )
            zf.writestr(f"backend/src/main/java/{cors_pkg_path}/CorsConfig.java", cors_src)

        # Backend RAW e blocos com heurísticas (reutiliza lógica do build_project_zip)
        if back:
            zf.writestr("backend/BACK_RAW.md", back)
            back_blocks = _extract_code_blocks(back)

            # Detecta e registra contrato de API em docs/api_contract.json
            for b in back_blocks:
                fn = (b.get("filename") or "").lower()
                lang = (b.get("language") or "").lower()
                content = b.get("content") or ""
                if fn == "api_contract.json" or (lang == "json" and '"endpoints"' in content and '"base_url"' in content):
                    zf.writestr("docs/api_contract.json", content)
                    b["_skip_write"] = True

            def _java_path_and_name(content: str) -> tuple[str, str]:
                base_pkg = group_id
                if "@SpringBootApplication" in (content or ""):
                    pkg = base_pkg
                elif "@RestController" in (content or "") or "@Controller" in (content or ""):
                    pkg = base_pkg + ".controller"
                elif "@Entity" in (content or ""):
                    pkg = base_pkg + ".model"
                elif "@Service" in (content or ""):
                    pkg = base_pkg + ".service"
                elif "@Repository" in (content or ""):
                    pkg = base_pkg + ".repository"
                else:
                    pkg = base_pkg + ".controller"
                cls = "ServerPart"
                for line in (content or "").splitlines():
                    line = line.strip()
                    if line.startswith("package ") and line.endswith(";"):
                        if "@SpringBootApplication" not in (content or ""):
                            pkg = line[len("package "):-1].strip()
                    m = re.match(r"public\s+class\s+([A-Za-z0-9_]+)", line)
                    if m:
                        cls = m.group(1)
                        break
                pkg_path = pkg.replace(".", "/")
                return pkg_path, cls

            spring_main_written = False
            saw_java = False
            pom_written = False
            java_pkgs: set[str] = set()
            for i, b in enumerate(back_blocks, start=1):
                lang = (b.get("language") or "txt").lower()
                content = b.get("content") or ""
                fn = b.get("filename")
                if b.get("_skip_write"):
                    continue

                # Corrige linguagem mal rotulada e sanitiza conteúdo Java
                if (lang != "java" and _looks_like_java(content)) or lang == "java":
                    lang = "java"
                    content = _sanitize_java(content)

                # Corrige linguagem mal rotulada e sanitiza conteúdo Java
                if (lang != "java" and _looks_like_java(content)) or lang == "java":
                    lang = "java"
                    content = _sanitize_java(content)

                if lang == "java":
                    saw_java = True
                    pkg_path, cls = _java_path_and_name(content)
                    # registra pacote detectado para definir scan
                    try:
                        java_pkgs.add(pkg_path.replace("/", "."))
                    except Exception:
                        pass
                    if "@SpringBootApplication" in content:
                        if spring_main_written:
                            content = content.replace("@SpringBootApplication", "")
                        else:
                            spring_main_written = True
                    name = _sanitize_java_filename(fn, cls)
                    path = f"backend/src/main/java/{pkg_path}/{name}"
                    zf.writestr(path, content)
                elif lang in ("xml", "pom") and ("<project" in content):
                    # Augmenta POM do agente com dependências mínimas se faltarem
                    def _augment_spring_pom(xml: str) -> str:
                        out = xml
                        if "spring-boot-starter-parent" not in out:
                            # adiciona parent simples logo após <modelVersion>
                            out = out.replace("<modelVersion>4.0.0</modelVersion>", "<modelVersion>4.0.0</modelVersion>\n  <parent>\n    <groupId>org.springframework.boot</groupId>\n    <artifactId>spring-boot-starter-parent</artifactId>\n    <version>3.3.0</version>\n    <relativePath/>\n  </parent>")
                        if "spring-boot-starter-web" not in out:
                            out = out.replace("</dependencies>", "  <dependency>\n      <groupId>org.springframework.boot</groupId>\n      <artifactId>spring-boot-starter-web</artifactId>\n    </dependency>\n  </dependencies>")
                        if "spring-boot-starter-data-jpa" not in out:
                            out = out.replace("</dependencies>", "  <dependency>\n      <groupId>org.springframework.boot</groupId>\n      <artifactId>spring-boot-starter-data-jpa</artifactId>\n    </dependency>\n    <dependency>\n      <groupId>com.h2database</groupId>\n      <artifactId>h2</artifactId>\n      <scope>runtime</scope>\n    </dependency>\n  </dependencies>")
                        if "jakarta.persistence-api" not in out:
                            out = out.replace("</dependencies>", "  <dependency>\n      <groupId>jakarta.persistence</groupId>\n      <artifactId>jakarta.persistence-api</artifactId>\n    </dependency>\n  </dependencies>")
                        if "spring-boot-maven-plugin" not in out:
                            if "</build>" in out:
                                out = out.replace("</build>", "  <plugins>\n      <plugin>\n        <groupId>org.springframework.boot</groupId>\n        <artifactId>spring-boot-maven-plugin</artifactId>\n      </plugin>\n    </plugins>\n  </build>")
                            else:
                                out = out.replace("</project>", "  <build>\n    <plugins>\n      <plugin>\n        <groupId>org.springframework.boot</groupId>\n        <artifactId>spring-boot-maven-plugin</artifactId>\n      </plugin>\n    </plugins>\n  </build>\n</project>")
                        return out
                    zf.writestr("backend/pom.xml", _augment_spring_pom(content))
                    pom_written = True
                elif preset == "spring" and lang in ("yml", "yaml"):
                    zf.writestr("backend/src/main/resources/application.yml", content)
                elif preset == "flask" and (lang in ("python", "py") or ("flask" in content.lower() or "@app.route" in content.lower())):
                    name = _sanitize_generic_filename("python", fn, f"routes_{i}")
                    sanitized = _sanitize_flask_python(content)
                    zf.writestr(f"backend/app/{name}", sanitized)
                elif preset == "express" and (lang in ("javascript", "js", "typescript", "ts") or ("express" in content.lower())):
                    ext_lang = "javascript" if lang in ("javascript", "js") else ("typescript" if lang in ("typescript", "ts") else lang)
                    name = _sanitize_generic_filename(ext_lang, fn, f"server_part_{i}")
                    sanitized = _sanitize_express_js(content)
                    base_lower = (name or "").lower()
                    # Evita criar arquivos duplicados do servidor Express. Todas as rotas ficam em index.js.
                    if any(base_lower.endswith(x) for x in ("app.js", "server.js", "index.js", "main.js")):
                        # Não escreve arquivos separados; o scaffold de index.js já concentra as rotas.
                        pass
                    else:
                        zf.writestr(f"backend/src/{name}", sanitized)
                elif lang in ("bash", "sh"):
                    name = _sanitize_generic_filename(lang, fn, f"server_part_{i}")
                    zf.writestr(f"backend/scripts/{name}", content)
                else:
                    name = _sanitize_generic_filename(lang, fn, f"server_part_{i}")
                    zf.writestr(f"backend/{name}", content)

        # Fallbacks para tornar o projeto executável em Spring, se necessário
        if preset == "spring" and saw_java and not spring_main_written:
            base_path = group_id.replace(".", "/")
            app_name = f"{project_name.capitalize()}Application"
            # Determina scan base a partir dos pacotes Java detectados; fallback para raiz do group_id
            def _compute_scan_base(pkgs: set[str], default_base: str) -> str:
                if not pkgs:
                    return ".".join(default_base.split(".")[:2]) or default_base
                parts_list = [p.split(".") for p in pkgs]
                base: list[str] = []
                for i in range(min(len(p) for p in parts_list)):
                    token = parts_list[0][i]
                    if all(len(p) > i and p[i] == token for p in parts_list):
                        base.append(token)
                    else:
                        break
                if len(base) < 2:
                    return ".".join(default_base.split(".")[:2]) or default_base
                return ".".join(base)

            scan_base = _compute_scan_base(java_pkgs, group_id)
            zf.writestr(
                f"backend/src/main/java/{base_path}/{app_name}.java",
                """package {group};
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.autoconfigure.domain.EntityScan;
import org.springframework.data.jpa.repository.config.EnableJpaRepositories;

@SpringBootApplication(scanBasePackages = "{scan}")
@EntityScan(basePackages = "{scan}")
@EnableJpaRepositories(basePackages = "{scan}")
public class {app} {
  public static void main(String[] args){ SpringApplication.run({app}.class, args); }
}
""".replace("{group}", group_id).replace("{app}", app_name).replace("{scan}", scan_base)
            )
        if preset == "spring" and saw_java and not pom_written:
            pom = f"""
<project xmlns=\"http://maven.apache.org/POM/4.0.0\" xmlns:xsi=\"http://www.w3.org/2001/XMLSchema-instance\" xsi:schemaLocation=\"http://maven.apache.org/POM/4.0.0 http://maven.apache.org/xsd/maven-4.0.0.xsd\">
  <modelVersion>4.0.0</modelVersion>
  <parent>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-parent</artifactId>
    <version>3.3.0</version>
    <relativePath/>
  </parent>
  <groupId>{group_id}</groupId>
  <artifactId>{project_name}</artifactId>
  <version>0.1.0</version>
  <dependencies>
    <dependency>
      <groupId>org.springframework.boot</groupId>
      <artifactId>spring-boot-starter-web</artifactId>
    </dependency>
  </dependencies>
  <build>
    <plugins>
      <plugin>
        <groupId>org.springframework.boot</groupId>
        <artifactId>spring-boot-maven-plugin</artifactId>
      </plugin>
    </plugins>
  </build>
</project>
"""
            zf.writestr("backend/pom.xml", pom)

        # QA (mesma heurística melhorada)
        if qa:
            zf.writestr("qa/README.md", qa)
            qa_blocks = _extract_code_blocks(qa)
            for i, b in enumerate(qa_blocks, start=1):
                lang = (b.get("language") or "txt").lower()
                content = b.get("content") or ""
                fn = b.get("filename")
                if lang in ("javascript", "js"):
                    name = fn or ("login.test.js" if "login" in content.lower() else f"test_{i}.js")
                    zf.writestr(f"qa/{name}", content)
                else:
                    ext = b.get("language") or "txt"
                    name = fn or f"tests_example_{i}.{ext}"
                    zf.writestr(f"qa/{name}", content)

    mem.seek(0)
    return mem
