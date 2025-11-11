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

            def _java_path_and_name(content: str) -> tuple[str, str]:
                """Tenta inferir package e nome de classe para Java."""
                pkg = "com.example.demo.controller"
                cls = "ServerPart"
                for line in (content or "").splitlines():
                    line = line.strip()
                    if line.startswith("package ") and line.endswith(";"):
                        pkg = line[len("package "):-1].strip()
                    m = re.match(r"public\s+class\s+([A-Za-z0-9_]+)", line)
                    if m:
                        cls = m.group(1)
                        break
                pkg_path = pkg.replace(".", "/")
                return pkg_path, cls

            for i, b in enumerate(back_blocks, start=1):
                lang = (b.get("language") or "txt").lower()
                content = b.get("content") or ""
                fn = b.get("filename")

                if lang == "java":
                    pkg_path, cls = _java_path_and_name(content)
                    name = fn or f"{cls}.java"
                    path = f"backend/src/main/java/{pkg_path}/{name}"
                    zf.writestr(path, content)
                elif lang in ("xml", "pom") and ("<project" in content):
                    # Provável pom.xml
                    zf.writestr("backend/pom.xml", content)
                elif lang in ("yml", "yaml"):
                    zf.writestr("backend/src/main/resources/application.yml", content)
                elif lang in ("bash", "sh"):
                    name = fn or f"server_part_{i}.sh"
                    zf.writestr(f"backend/scripts/{name}", content)
                else:
                    ext = b.get("language") or "txt"
                    name = fn or f"server_part_{i}.{ext}"
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
            pom = f"""<project xmlns=\"http://maven.apache.org/POM/4.0.0\" xmlns:xsi=\"http://www.w3.org/2001/XMLSchema-instance\" xsi:schemaLocation=\"http://maven.apache.org/POM/4.0.0 http://maven.apache.org/xsd/maven-4.0.0.xsd\">\n  <modelVersion>4.0.0</modelVersion>\n  <groupId>{group_id}</groupId>\n  <artifactId>{project_name}</artifactId>\n  <version>0.1.0</version>\n  <dependencies>\n    <dependency>\n      <groupId>org.springframework.boot</groupId>\n      <artifactId>spring-boot-starter-web</artifactId>\n      <version>3.3.0</version>\n    </dependency>\n  </dependencies>\n</project>\n"""
            zf.writestr("backend/pom.xml", pom)
            base_path = group_id.replace(".", "/")
            zf.writestr(f"backend/src/main/java/{base_path}/DemoApplication.java", """package {group};\nimport org.springframework.boot.SpringApplication;\nimport org.springframework.boot.autoconfigure.SpringBootApplication;\n@SpringBootApplication\npublic class DemoApplication {\n  public static void main(String[] args){ SpringApplication.run(DemoApplication.class, args); }\n}\n""".replace("{group}", group_id))

        # Backend RAW e blocos com heurísticas (reutiliza lógica do build_project_zip)
        if back:
            zf.writestr("backend/README.md", back)
            back_blocks = _extract_code_blocks(back)

            def _java_path_and_name(content: str) -> tuple[str, str]:
                pkg = f"{group_id}.controller"
                cls = "ServerPart"
                for line in (content or "").splitlines():
                    line = line.strip()
                    if line.startswith("package ") and line.endswith(";"):
                        pkg = line[len("package "):-1].strip()
                    m = re.match(r"public\s+class\s+([A-Za-z0-9_]+)", line)
                    if m:
                        cls = m.group(1)
                        break
                pkg_path = pkg.replace(".", "/")
                return pkg_path, cls

            for i, b in enumerate(back_blocks, start=1):
                lang = (b.get("language") or "txt").lower()
                content = b.get("content") or ""
                fn = b.get("filename")

                if lang == "java":
                    pkg_path, cls = _java_path_and_name(content)
                    name = fn or f"{cls}.java"
                    path = f"backend/src/main/java/{pkg_path}/{name}"
                    zf.writestr(path, content)
                elif lang in ("xml", "pom") and ("<project" in content):
                    zf.writestr("backend/pom.xml", content)
                elif lang in ("yml", "yaml"):
                    zf.writestr("backend/src/main/resources/application.yml", content)
                elif lang in ("bash", "sh"):
                    name = fn or f"server_part_{i}.sh"
                    zf.writestr(f"backend/scripts/{name}", content)
                else:
                    ext = b.get("language") or "txt"
                    name = fn or f"server_part_{i}.{ext}"
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