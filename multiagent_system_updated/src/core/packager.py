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
            # Opcional: tenta extrair blocos e escrever arquivos auxiliares
            back_blocks = _extract_code_blocks(back)
            for i, b in enumerate(back_blocks, start=1):
                fn = b.get("filename")
                ext = b.get("language") or "txt"
                if not fn:
                    fn = f"server_part_{i}.{ext}"
                zf.writestr(f"backend/{fn}", b.get("content") or "")

        # QA
        if qa:
            zf.writestr("qa/README.md", qa)
            qa_blocks = _extract_code_blocks(qa)
            for i, b in enumerate(qa_blocks, start=1):
                fn = b.get("filename")
                ext = b.get("language") or "txt"
                if not fn:
                    fn = f"tests_example_{i}.{ext}"
                zf.writestr(f"qa/{fn}", b.get("content") or "")

    mem.seek(0)
    return mem