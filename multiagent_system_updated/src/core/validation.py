import re
import json
from typing import Dict, List, Tuple, Optional
from urllib.parse import urlparse

try:
    import jsonschema  # type: ignore
except Exception:
    jsonschema = None  # validaremos condicionalmente


API_CONTRACT_SCHEMA = {
    "type": "object",
    "required": ["base_url", "endpoints"],
    "properties": {
        "base_url": {"type": "string"},
        "endpoints": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["path", "method"],
                "properties": {
                    "path": {"type": "string"},
                    "method": {"type": "string"},
                    "request": {"type": "object"},
                    "response": {"type": "object"},
                },
            },
        },
    },
}


def validate_contract_minimal(contract: Dict) -> Tuple[bool, Optional[str]]:
    try:
        if jsonschema is None:
            # fallback mínimo sem jsonschema
            if not isinstance(contract, dict):
                return False, "Contract must be a dict"
            if "base_url" not in contract or "endpoints" not in contract:
                return False, "Missing base_url or endpoints"
            return True, None
        jsonschema.validate(instance=contract, schema=API_CONTRACT_SCHEMA)
        return True, None
    except Exception as e:
        return False, f"Contract validation error: {e}"


def check_single_entrypoint(file_paths: List[str], allowed_entrynames: List[str]) -> Tuple[bool, Optional[str]]:
    normalized = [p.replace("\\", "/").split("/")[-1].lower() for p in file_paths]
    matches = [p for p in normalized if p in [n.lower() for n in allowed_entrynames]]
    if len(matches) == 0:
        return False, f"No entrypoint found. Expected one of: {allowed_entrynames}"
    if len(matches) > 1:
        return False, f"Ambiguous entrypoints found: {matches}"
    return True, None


def _extract_fetch_calls(js_content: str) -> List[Tuple[str, str]]:
    """
    Retorna lista de (method, url) a partir de fetch() com parsing simples.
    - Default method = GET
    - Se existir segundo argumento com { method: 'POST' }, usa esse método
    """
    calls: List[Tuple[str, str]] = []
    if not js_content:
        return calls
    # fetch('URL', { ...method: 'POST'... }) ou "POST"
    pattern = re.compile(r"fetch\(\s*([\'\"])(?P<url>[^\'\"]+)\1\s*(?:,\s*\{(?P<opts>.*?)\})?\s*\)", re.DOTALL)
    for m in pattern.finditer(js_content):
        url = m.group("url")
        opts = m.group("opts") or ""
        method = "GET"
        # tenta encontrar method: 'POST' ou "POST"
        mm = re.search(r"method\s*:\s*([\'\"])(?P<m>[^\'\"]+)\1", opts, re.IGNORECASE)
        if mm:
            method = (mm.group("m") or "GET").upper()
        calls.append((method, url))
    return calls


def extract_fetch_paths_from_script(js_content: str) -> List[str]:
    paths: List[str] = []
    for method, raw in _extract_fetch_calls(js_content):
        try:
            p = urlparse(raw)
            path = p.path or raw
        except Exception:
            path = raw
        paths.append(path)
    return paths


def check_front_vs_contract(front_files: Dict[str, str], contract: Dict) -> Tuple[bool, Optional[str]]:
    endpoints = set()
    for e in contract.get("endpoints", []) or []:
        method = (e.get("method") or "GET").upper()
        path = e.get("path") or ""
        endpoints.add((method, path))

    # analisa todos .js/.ts
    used: List[Tuple[str, str]] = []
    for p, c in front_files.items():
        low = p.lower()
        if low.endswith(".js") or low.endswith(".ts"):
            used.extend(_extract_fetch_calls(c))

    if not used:
        return True, None

    missing: List[Tuple[str, str]] = []
    for method, raw in used:
        path = raw
        try:
            path = urlparse(raw).path or raw
        except Exception:
            pass
        if (method, path) in endpoints:
            continue
        # tolera ausência de /api prefix
        alt = path
        if path.startswith("/api"):
            alt = path[len("/api"):]
        if (method, alt) in endpoints:
            continue
        missing.append((method, path))
    if missing:
        return False, f"Frontend fetch usage not covered by contract: {missing}"
    return True, None


def infer_contract_from_backend(back_text: str) -> Dict:
    """Heurística mínima para extrair endpoints de Flask/Express do texto bruto."""
    endpoints: List[Dict] = []
    # Flask: @app.route('/path', methods=['GET','POST'])
    for m in re.finditer(r"@\s*app\s*\.\s*route\s*\(\s*([\'\"])(?P<path>[^\'\"]+)\1\s*,\s*methods\s*=\s*\[(?P<methods>[^\]]+)\]\s*\)", back_text):
        path = m.group("path")
        methods_raw = m.group("methods")
        for mm in re.finditer(r"([\'\"])(?P<method>[A-Za-z]+)\1", methods_raw):
            endpoints.append({"path": path, "method": mm.group("method").upper()})
    for m in re.finditer(r"@\s*app\s*\.\s*route\s*\(\s*([\'\"])(?P<path>[^\'\"]+)\1\s*\)", back_text):
        endpoints.append({"path": m.group("path"), "method": "GET"})
    # Express: app.get('/path'), app.post('/path') etc.
    for meth in ("get", "post", "put", "delete", "patch"):
        pattern = re.compile(rf"app\s*\.\s*{meth}\s*\(\s*([\'\"])(?P<path>[^\'\"]+)\1", re.IGNORECASE)
        for m in pattern.finditer(back_text):
            endpoints.append({"path": m.group("path"), "method": meth.upper()})
    base_url = "/api" if any((e.get("path") or "").startswith("/api") for e in endpoints) else "/"
    return {"base_url": base_url, "endpoints": endpoints}


def try_load_contract_from_blocks(blocks: List[Dict]) -> Optional[Dict]:
    for b in blocks:
        lang = (b.get("language") or "").lower()
        content = b.get("content") or ""
        fn = (b.get("filename") or "").lower()
        if lang == "json" or fn.endswith("api_contract.json"):
            try:
                obj = json.loads(content)
                ok, _ = validate_contract_minimal(obj)
                if ok:
                    return obj
            except Exception:
                continue
    return None
