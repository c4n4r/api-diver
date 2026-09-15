"""Petits utilitaires partagés : slugs et noms de variables d'environnement."""

from __future__ import annotations

import re

_SLUG_INVALID_RE = re.compile(r"[^a-z0-9]+")
_ENV_INVALID_RE = re.compile(r"[^A-Z0-9]+")


def slugify(text: str, fallback: str = "api") -> str:
    """Slug conforme aux noms de skills : ^[a-z0-9]+(-[a-z0-9]+)*$, max 64."""
    slug = _SLUG_INVALID_RE.sub("-", (text or "").lower()).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)[:64].strip("-")
    if not slug or not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", slug):
        return fallback
    return slug


def env_prefix(api_name: str) -> str:
    """Préfixe de variables d'env pour une API : « pet-store » -> « PET_STORE »."""
    prefix = _ENV_INVALID_RE.sub("_", (api_name or "").upper()).strip("_")
    return prefix or "API"


def env_name(api_name: str, suffix: str) -> str:
    """Nom de placeholder complet : (« pet-store », « id ») -> « PET_STORE_ID »."""
    clean = _ENV_INVALID_RE.sub("_", (suffix or "").upper()).strip("_")
    return f"{env_prefix(api_name)}_{clean}" if clean else env_prefix(api_name)
