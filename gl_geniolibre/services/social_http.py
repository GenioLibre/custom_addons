# -*- coding: utf-8 -*-
"""Utilidades compartidas para llamadas a APIs sociales."""

import re
import time

import requests


SOCIAL_HTTP_TIMEOUT = 30
INSTAGRAM_HTTP_TIMEOUT = 60
SOCIAL_RETRY_ATTEMPTS = 3
SOCIAL_RETRYABLE_STATUS_CODES = (408, 425, 429, 500, 502, 503, 504)
PUBLICATION_STATUS_SELECTION = [
    ("Pendiente", "Pendiente"),
    ("Programado", "Programado"),
    ("Procesando", "Procesando"),
    ("Revisando", "Revisando"),
    ("Publicado", "Publicado"),
    ("Cancelado", "Cancelado"),
    ("Error", "Error"),
]

_SECRET_QUERY_KEYS = re.compile(
    r"([?&](?:access_token|token|client_secret|api_key|secret)=)[^&\s]+",
    re.IGNORECASE,
)
_LONG_SECRET = re.compile(r"(?<![A-Za-z0-9])[A-Za-z0-9_-]{32,}(?![A-Za-z0-9])")


def sanitize_error_message(error):
    """Evita guardar o enviar credenciales dentro de mensajes de error."""
    message = str(error or "Error no especificado")
    message = _SECRET_QUERY_KEYS.sub(r"\1[REDACTED]", message)
    return _LONG_SECRET.sub("[REDACTED]", message)[:2000]


def response_error_message(response):
    """Obtiene un error breve y seguro sin asumir que la respuesta es JSON."""
    try:
        payload = response.json() or {}
        error = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(error, dict):
            detail = error.get("message") or error.get("type") or error
        else:
            detail = payload.get("message") if isinstance(payload, dict) else payload
        if detail:
            return sanitize_error_message(detail)
    except (ValueError, TypeError, AttributeError):
        pass
    return sanitize_error_message(getattr(response, "text", "Respuesta HTTP sin detalle")[:500])


def request_with_retries(
    method,
    url,
    *,
    attempts=SOCIAL_RETRY_ATTEMPTS,
    retry_statuses=SOCIAL_RETRYABLE_STATUS_CODES,
    **kwargs,
):
    """Reintenta solo lecturas o llamadas explícitamente idempotentes."""
    method = method.upper()
    safe_to_retry = kwargs.pop("safe_to_retry", False)
    can_retry = method in {"GET", "HEAD", "OPTIONS"} or safe_to_retry
    last_error = None

    for attempt in range(1, attempts + 1):
        try:
            response = requests.request(method, url, **kwargs)
            if not can_retry or response.status_code not in retry_statuses or attempt == attempts:
                return response
            last_error = requests.exceptions.HTTPError(
                f"HTTP {response.status_code} en {method} {url}", response=response
            )
        except requests.exceptions.RequestException as exc:
            last_error = exc
            if not can_retry or attempt == attempts:
                raise

        time.sleep(min(2 ** (attempt - 1), 4))

    raise last_error
