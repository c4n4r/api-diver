"""Erreurs métier d'api-diver."""

from __future__ import annotations


class ApiDiverError(Exception):
    """Erreur de base, interceptée par le CLI pour un message propre."""


class WorkspaceError(ApiDiverError):
    pass


class FetchError(ApiDiverError):
    pass


class SpecError(ApiDiverError):
    pass


class GeneratorError(ApiDiverError):
    pass
