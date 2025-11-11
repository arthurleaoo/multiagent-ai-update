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
    return generate_password_hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    return check_password_hash(password_hash, password)


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