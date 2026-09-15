"""Résolution des $ref locaux dans un document OpenAPI/Swagger brut.

Chaque référence locale (`#/...`) est remplacée par une copie profonde de sa
cible, avec détection de cycles et limite de profondeur. Les références
externes (URL) sont conservées telles quelles et signalées en warning.
"""

from __future__ import annotations

import copy
from typing import Any

MAX_DEPTH = 15


def _lookup_pointer(doc: dict, pointer: str) -> Any:
    if not pointer.startswith("#/"):
        return None
    current: Any = doc
    for raw_part in pointer[2:].split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return None
    return current


def resolve_document(doc: dict) -> tuple[dict, list[str]]:
    """Résout tous les $ref locaux de `doc` et retourne (document, warnings)."""
    warnings: list[str]
    seen_external: set[str]

    warnings = []
    seen_external = set()

    def walk(node: Any, stack: frozenset) -> Any:
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str):
                if not ref.startswith("#/"):
                    if ref not in seen_external:
                        seen_external.add(ref)
                        warnings.append(f"référence externe non résolue : {ref}")
                    return {"type": "any", "description": f"(référence externe : {ref})"}
                if ref in stack:
                    return {"x-cycle": ref.rsplit("/", 1)[-1]}
                target = _lookup_pointer(doc, ref)
                if target is None:
                    warnings.append(f"référence introuvable : {ref}")
                    return {"type": "string", "description": f"(référence introuvable : {ref})"}
                if len(stack) >= MAX_DEPTH:
                    return {"type": "string", "description": "(profondeur maximale atteinte)"}
                resolved = walk(copy.deepcopy(target), stack | {ref})
                out = dict(resolved) if isinstance(resolved, dict) else {"type": "any"}
                if isinstance(resolved, dict) and "x-ref-name" not in resolved:
                    out["x-ref-name"] = ref.rsplit("/", 1)[-1]
                # les clés voisines du $ref sont fusionnées (permis en OAS 3)
                for key, value in node.items():
                    if key != "$ref":
                        out.setdefault(key, value)
                return out
            return {k: walk(v, stack) for k, v in node.items()}
        if isinstance(node, list):
            return [walk(item, stack) for item in node]
        return node

    return walk(copy.deepcopy(doc), frozenset()), warnings
