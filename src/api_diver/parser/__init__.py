"""Point d'entrée des parsers : détection de la version et dispatch."""

from __future__ import annotations

from ..errors import SpecError
from ..model import ApiSpec
from . import v2, v3


def parse_document(
    doc: object,
    name: str,
    source_url: str,
    group_label: str = "",
    collect_warnings: list | None = None,
) -> ApiSpec:
    if not isinstance(doc, dict):
        raise SpecError("le document récupéré n'est pas un objet JSON/YAML exploitable")
    openapi = str(doc.get("openapi", "") or "")
    swagger = str(doc.get("swagger", "") or "")
    if openapi.startswith("3"):
        return v3.parse(doc, name=name, source_url=source_url, group_label=group_label,
                        collect_warnings=collect_warnings)
    if swagger.startswith("2"):
        return v2.parse(doc, name=name, source_url=source_url, group_label=group_label,
                        collect_warnings=collect_warnings)
    raise SpecError(
        "document non reconnu : ni OpenAPI 3 (clé « openapi ») ni Swagger 2.0 (clé « swagger »)"
    )
