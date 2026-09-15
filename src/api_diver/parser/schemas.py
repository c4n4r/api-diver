"""Convertisseurs partagés : schémas bruts -> SchemaNode, paramètres, sécurité."""

from __future__ import annotations

import re
from typing import Any, Optional

from ..model import Parameter, RequestBody, SchemaNode, SecurityScheme

_WS_RE = re.compile(r"\s+")


def clean_text(text: Any, max_len: int = 400) -> str:
    if text is None:
        return ""
    flat = _WS_RE.sub(" ", str(text)).strip()
    if len(flat) > max_len:
        flat = flat[: max_len - 1] + "…"
    return flat


def _infer_type(node: dict) -> str:
    t = node.get("type")
    if isinstance(t, list):  # OpenAPI 3.1 : type peut être une liste
        non_null = [x for x in t if x != "null"]
        t = non_null[0] if non_null else "string"
    if t:
        return str(t)
    if "properties" in node or "additionalProperties" in node or "allOf" in node:
        return "object"
    if "items" in node:
        return "array"
    return "string"


def _merge_allof(base: SchemaNode, other: SchemaNode) -> None:
    if other.properties:
        base.properties = {**base.properties, **other.properties}
    if other.required:
        base.required = list(dict.fromkeys(base.required + other.required))
    if other.enum:
        base.enum = other.enum
    if other.items is not None:
        base.items = other.items
    if other.additional_properties is not None:
        base.additional_properties = other.additional_properties
    if not base.description and other.description:
        base.description = other.description
    if not base.format and other.format:
        base.format = other.format
    if base.type in ("string", "any") and other.type not in ("string", "any", "object"):
        base.type = other.type


def build_schema(node: Any, depth: int = 0) -> Optional[SchemaNode]:
    """Construit un SchemaNode depuis un nœud de spec (déjà résolu côté $ref)."""
    if node is None:
        return None
    if node is True:
        return SchemaNode(type="any")
    if not isinstance(node, dict):
        return SchemaNode(type="any", description=clean_text(node))

    if "x-cycle" in node:
        return SchemaNode(type="any", description=f"(référence circulaire : {node['x-cycle']})")
    if "$ref" in node:
        return SchemaNode(type="ref", description=f"(référence externe : {node['$ref']})")
    if depth > 15:
        return SchemaNode(type="any", description="(schéma trop profond)")

    schema = SchemaNode()
    schema.ref_name = str(node.get("x-ref-name", ""))
    schema.description = clean_text(node.get("description", ""))
    schema.format = str(node.get("format", "") or "")
    schema.type = _infer_type(node)
    if node.get("nullable") or node.get("readOnly"):
        notes = []
        if node.get("nullable"):
            notes.append("nullable")
        if node.get("readOnly"):
            notes.append("lecture seule")
        if notes:
            schema.description = (schema.description + " " if schema.description else "") + (
                "(" + ", ".join(notes) + ")"
            )

    enum = node.get("enum")
    if isinstance(enum, list):
        schema.enum = enum
    if node.get("default") is not None:
        schema.default = node.get("default")
    example = node.get("example")
    if example is None and isinstance(node.get("examples"), list) and node["examples"]:
        example = node["examples"][0]
    if example is not None:
        schema.example = example

    # allOf : fusion des sous-schémas (au-dessus des propres propriétés)
    if isinstance(node.get("allOf"), list):
        schema.type = "object"
        for sub in node["allOf"]:
            child = build_schema(sub, depth + 1)
            if child is not None:
                _merge_allof(schema, child)

    # anyOf / oneOf : la première variante sert de base, les autres sont notées
    variants = node.get("anyOf") or node.get("oneOf")
    if isinstance(variants, list) and not schema.properties and not schema.enum:
        alts = [b for b in (build_schema(v, depth + 1) for v in variants) if b]
        if alts:
            first = alts[0]
            schema.properties = first.properties
            schema.required = first.required
            schema.items = first.items
            schema.enum = first.enum
            if first.type not in ("object",):
                schema.type = first.type
            names = [a.ref_name or a.type for a in alts]
            note = f"variantes possibles : {' | '.join(names)}"
            schema.description = (schema.description + " — " if schema.description else "") + note

    if isinstance(node.get("properties"), dict):
        schema.type = "object" if schema.type not in ("array",) else schema.type
        schema.properties = {
            str(k): build_schema(v, depth + 1) for k, v in node["properties"].items()
        }
    if isinstance(node.get("items"), (dict, bool)):
        schema.items = build_schema(node["items"], depth + 1)
    additional = node.get("additionalProperties")
    if isinstance(additional, dict):
        schema.additional_properties = build_schema(additional, depth + 1)
    elif additional is True:
        schema.additional_properties = SchemaNode(type="any")

    return schema


def build_parameter_v3(raw: dict) -> Optional[Parameter]:
    """Paramètre OpenAPI 3 (le schéma est dans raw['schema'])."""
    if not isinstance(raw, dict):
        return None
    schema_node = raw.get("schema") if isinstance(raw.get("schema"), (dict, bool)) else None
    schema = build_schema(schema_node) if schema_node is not None else None
    example = raw.get("example")
    if example is None and isinstance(raw.get("examples"), dict):
        first = next(iter(raw["examples"].values()), None)
        if isinstance(first, dict) and "value" in first:
            example = first["value"]
    return Parameter(
        name=str(raw.get("name", "")),
        location=str(raw.get("in", "query")),
        required=bool(raw.get("required", False)),
        description=clean_text(raw.get("description", "")),
        type=schema.type if schema else _infer_type(raw),
        format=schema.format if schema else str(raw.get("format", "") or ""),
        enum=schema.enum if schema else [],
        default=schema.default if schema else raw.get("default"),
        example=example if example is not None else (schema.example if schema else None),
    )


def build_parameter_v2(raw: dict) -> Optional[Parameter]:
    """Paramètre Swagger 2.0 (type/format directement sur le paramètre)."""
    if not isinstance(raw, dict):
        return None
    return Parameter(
        name=str(raw.get("name", "")),
        location=str(raw.get("in", "query")),
        required=bool(raw.get("required", False)),
        description=clean_text(raw.get("description", "")),
        type=str(raw.get("type", "string")),
        format=str(raw.get("format", "") or ""),
        enum=list(raw.get("enum", []) or []),
        default=raw.get("default"),
        example=raw.get("example"),
    )


def body_from_v2_param(raw: dict, consumes: str) -> Optional[RequestBody]:
    """Paramètre Swagger 2.0 `in: body` -> RequestBody."""
    if not isinstance(raw, dict) or raw.get("in") != "body":
        return None
    schema = build_schema(raw.get("schema"))
    if schema is None:
        return None
    return RequestBody(
        required=bool(raw.get("required", False)),
        description=clean_text(raw.get("description", "")),
        content_types={consumes: schema},
    )


def convert_security_scheme(name: str, raw: dict) -> SecurityScheme:
    """securityDefinitions (v2) et securitySchemes (v3) ont des formes proches."""
    type_ = str(raw.get("type", ""))
    scheme = SecurityScheme(
        name=str(name),
        type=type_,
        location=str(raw.get("in", "")),
        scheme=str(raw.get("scheme", "")),
        param_name=str(raw.get("name", "") or "") if type_ == "apiKey" else "",
        description=clean_text(raw.get("description", "")),
    )
    if type_ == "basic":  # v2
        scheme.type = "http"
        scheme.scheme = "basic"
    flows = raw.get("flows")
    if type_ == "oauth2" and flows:
        flow_names = ", ".join(flows.keys())
        scheme.description = (scheme.description + " " if scheme.description else "") + (
            f"(flows : {flow_names})"
        )
    return scheme


def merge_parameters(path_params: list, op_params: list) -> list[dict]:
    """Fusion des paramètres de niveau path et opération (l'opération gagne)."""
    merged: dict[tuple[str, str], dict] = {}
    for p in path_params + op_params:
        if not isinstance(p, dict):
            continue
        key = (str(p.get("name", "")), str(p.get("in", "query")))
        merged[key] = p
    return list(merged.values())
