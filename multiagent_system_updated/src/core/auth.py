import os
from datetime import datetime
from typing import Optional

from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from werkzeug.security import generate_password_hash, check_password_hash


# Cache em memória para garantir consistência da assinatura durante o ciclo de vida do processo
_SECRET_CACHE: str | None = None


def get_secret_key() -> str:
    global _SECRET_CACHE
    # Se houver variável de ambiente, prioriza sempre
    env_secret = os.getenv("SECRET_KEY")
    if env_secret:
        _SECRET_CACHE = env_secret
        return env_secret

    # Se não houver, reutiliza a mesma chave gerada durante a vida do processo
    if _SECRET_CACHE is None:
        _SECRET_CACHE = os.urandom(24).hex()
    return _SECRET_CACHE


def get_serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(get_secret_key())


def hash_password(password: str) -> str:
    # Opcional: pepper (segredo adicional) para fortalecer hashes
    pepper = os.getenv("PASSWORD_PEPPER", "")
    return generate_password_hash(password + pepper)


def verify_password(password_hash: str, password: str) -> bool:
    pepper = os.getenv("PASSWORD_PEPPER", "")
    return check_password_hash(password_hash, password + pepper)


def validate_password_strength(password: str) -> tuple[bool, str]:
    """
    Regras de força de senha (equilíbrio entre segurança e usabilidade):
    - Mínimo 8 caracteres
    - Pelo menos 1 letra minúscula
    - Pelo menos 1 letra maiúscula
    - Pelo menos 1 dígito
    - Pelo menos 1 caractere especial (ex.: !@#$%^&*_-)
    Retorna (ok, mensagem_de_erro_se_houver)
    """
    if len(password) < 8:
        return False, "Senha deve conter pelo menos 8 caracteres"
    has_lower = any(c.islower() for c in password)
    has_upper = any(c.isupper() for c in password)
    has_digit = any(c.isdigit() for c in password)
    specials = set("!@#$%^&*()-_=+[]{};:,.<>/?|\\")
    has_special = any(c in specials for c in password)
    if not has_lower:
        return False, "Senha deve conter pelo menos 1 letra minúscula"
    if not has_upper:
        return False, "Senha deve conter pelo menos 1 letra maiúscula"
    if not has_digit:
        return False, "Senha deve conter pelo menos 1 dígito"
    if not has_special:
        return False, "Senha deve conter pelo menos 1 caractere especial"
    return True, ""


def create_token(user_id: int) -> str:
    s = get_serializer()
    payload = {
        "uid": user_id,
        "iat": int(datetime.utcnow().timestamp()),
    }
    return s.dumps(payload)


def verify_token(token: str, max_age_seconds: Optional[int] = None) -> Optional[int]:
    """
    Retorna user_id se o token for válido, caso contrário None.
    max_age_seconds: tempo máximo de validade. Se None, usa 7 dias.
    """
    s = get_serializer()
    if max_age_seconds is None:
        max_age_seconds = int(os.getenv("TOKEN_MAX_AGE", "604800"))  # 7 dias
    try:
        data = s.loads(token, max_age=max_age_seconds)
        return int(data.get("uid"))
    except (BadSignature, SignatureExpired, ValueError, TypeError):
        return None