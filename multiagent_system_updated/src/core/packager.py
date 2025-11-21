import io
import re
import zipfile
from typing import Optional


def _extract_code_blocks(text: str) -> list[dict]:
    """
    Extrai blocos de código Markdown (```lang\n...```), tentando identificar nome de arquivo
    nas primeiras linhas do bloco (comentários contendo algo como 'index.html', 'styles.css', etc.).
    Retorna lista de dicts: {language, content, filename}
    """
    blocks: list[dict] = []
    # Captura ```lang\n...\n```
    pattern = re.compile(r"```([a-zA-Z0-9_+-]*)\n(.*?)```", re.DOTALL)
    for m in pattern.finditer(text or ""):
        lang = m.group(1) or ""
        content = m.group(2)
        filename = None
        # Verifica até as 3 primeiras linhas por um possível nome de arquivo
        first_lines = (content.splitlines()[:3]) if content else []
        for line in first_lines:
            l = line.strip()
            # Padrões comuns de comentário com nome de arquivo
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

Observação: arquivos podem ser exemplos e exigem ajustes conforme stack escolhida.
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
        # Grava arquivos
        for fn, content in desired.items():
            if content:
                zf.writestr(f"frontend/{fn}", content)
        # Guarda o bruto
        if front:
            zf.writestr("frontend/FRONT_RAW.md", front)

        # BACKEND
        if back:
            zf.writestr("backend/README.md", back)
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

            spring_main_written = False
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
                    pkg_path, cls = _java_path_and_name(content)
                    # evita múltiplos @SpringBootApplication: mantém apenas o primeiro
                    if "@SpringBootApplication" in content:
                        if spring_main_written:
                            content = content.replace("@SpringBootApplication", "")
                        else:
                            spring_main_written = True
                    name = _sanitize_java_filename(fn, cls)
                    path = f"backend/src/main/java/{pkg_path}/{name}"
                    zf.writestr(path, content)
                elif lang in ("xml", "pom") and ("<project" in content):
                    # Provável pom.xml — complementa com JPA/H2, jakarta.persistence-api e plugin se faltarem
                    def _augment_spring_pom(xml: str) -> str:
                        out = xml
                        if "spring-boot-starter-parent" not in out:
                            out = out.replace("<modelVersion>4.0.0</modelVersion>", "<modelVersion>4.0.0</modelVersion>\n  <parent>\n    <groupId>org.springframework.boot</groupId>\n    <artifactId>spring-boot-starter-parent</artifactId>\n    <version>3.3.0</version>\n    <relativePath/>\n  </parent>")
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
                elif lang in ("yml", "yaml"):
                    zf.writestr("backend/src/main/resources/application.yml", content)
                elif lang in ("bash", "sh"):
                    name = _sanitize_generic_filename(lang, fn, f"server_part_{i}")
                    zf.writestr(f"backend/scripts/{name}", content)
                else:
                    name = _sanitize_generic_filename(lang, fn, f"server_part_{i}")
                    zf.writestr(f"backend/{name}", content)

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


def build_structured_zip(task: str, language: str, front: str, back: str, qa: str, preset: str = "flask", project_name: str = "projeto", group_id: str = "com.example.demo") -> io.BytesIO:
    """
    Gera um ZIP com estrutura de projeto completa baseada em 'preset':
      - flask: backend Python/Flask
      - express: backend Node.js/Express
      - spring: backend Java/Spring Boot (Maven)
    Integra os artefatos dos agentes em locais apropriados e mantém arquivos RAW.
    """
    mem = io.BytesIO()
    with zipfile.ZipFile(mem, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        # README top
        zf.writestr("README.md", f"""# {project_name}

Preset: {preset}
Task: {task}
Language: {language}

Este projeto foi gerado automaticamente com estrutura padrão ({preset}).
Arquivos RAW dos agentes são mantidos em frontend/FRONT_RAW.md e backend/README.md.
""")

        # Frontend (mesma lógica do build_project_zip)
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
        for fn, content in desired.items():
            if content:
                zf.writestr(f"frontend/{fn}", content)
        if front:
            zf.writestr("frontend/FRONT_RAW.md", front)

        # Presets para backend
        if preset == "flask":
            zf.writestr("backend/requirements.txt", "flask\nitsdangerous\n")
            zf.writestr("backend/app/__init__.py", "from flask import Flask\napp = Flask(__name__)\n")
            zf.writestr("backend/app/main.py", """from flask import request, jsonify\nfrom . import app\n\n@app.route('/health')\ndef health():\n    return jsonify({'status':'ok'})\n\n# TODO: mover rotas geradas aqui\n""")
        elif preset == "express":
            pkg = """{\n  \"name\": \"{name}\",\n  \"version\": \"0.1.0\",\n  \"private\": true,\n  \"scripts\": {\n    \"start\": \"node src/index.js\"\n  },\n  \"dependencies\": {\n    \"express\": \"^4.18.2\"\n  }\n}\n""".replace("{name}", project_name)
            zf.writestr("backend/package.json", pkg)
            zf.writestr("backend/src/index.js", """const express = require('express');\nconst app = express();\napp.use(express.json());\napp.get('/health', (req,res)=>res.json({status:'ok'}));\n// TODO: mover rotas geradas aqui\napp.listen(3000, ()=>console.log('Server on 3000'));\n""")
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
            zf.writestr(f"backend/src/main/java/{base_path}/{app_name}.java", """package {group};\nimport org.springframework.boot.SpringApplication;\nimport org.springframework.boot.autoconfigure.SpringBootApplication;\n@SpringBootApplication\npublic class {app} {\n  public static void main(String[] args){ SpringApplication.run({app}.class, args); }\n}\n""".replace("{group}", group_id).replace("{app}", app_name))
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
    show-sql: true
  h2:
    console:
      enabled: true
""")

        # Backend RAW e blocos com heurísticas (reutiliza lógica do build_project_zip)
        if back:
            zf.writestr("backend/README.md", back)
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
                    pkg_path, cls = _java_path_and_name(content)
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
                elif lang in ("yml", "yaml"):
                    zf.writestr("backend/src/main/resources/application.yml", content)
                elif lang in ("bash", "sh"):
                    name = _sanitize_generic_filename(lang, fn, f"server_part_{i}")
                    zf.writestr(f"backend/scripts/{name}", content)
                else:
                    name = _sanitize_generic_filename(lang, fn, f"server_part_{i}")
                    zf.writestr(f"backend/{name}", content)

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