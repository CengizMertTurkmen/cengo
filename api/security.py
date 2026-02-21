import os

from fastapi import HTTPException, Security
from fastapi.security.api_key import APIKeyHeader

_api_key_header = APIKeyHeader(name="X-Api-Key", auto_error=False)


def require_api_key(key: str = Security(_api_key_header)):
    """Tüm korumalı endpoint'lerde kullanılan API key doğrulaması."""
    expected = os.environ.get("API_KEY", "")
    if not expected:
        raise HTTPException(status_code=500, detail="Sunucuda API_KEY tanımlı değil.")
    if key != expected:
        raise HTTPException(status_code=401, detail="Geçersiz veya eksik API key.")
