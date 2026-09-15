"""Aides de rendu markdown : types, tables de propriétés, exemples JSON."""

from __future__ import annotations

import json
from typing import Any

from ..model import Parameter, SchemaNode

_FORMAT_EXAMPLES = {
    "date-time": "2026-01-01T12:00:00Z",
    "date": "2026-01-01",
    "time": "12:00:00Z",
    "uri": "https://example.com",
    "url": "https://example.com",
    "email": "user@example.com",
    "uuid": "00000000-0000-0000-0000-000000000000",
    "password": "********",
    "byte": "ZXhhbXBsZQ==",
    "binary": "(fichier)",
}


def md_cell(text: Any, max_len: int = 160) -> str:
    cell = " ".join(str(text if text is not None else "").split())
    if len(cell) > max_len:
        cell = cell[: max_len - 1] + "…"
    return cell.replace("|", "\\|")


def code_span(text: Any) -> str:
    return "`" + md_cell(text, 80).replace("`", "'") + "`"


def schema_type_label(schema: SchemaNode | None) -> str:
    if schema is None:
        return "any"
    base = schema.type
    if base == "array":
        inner = schema_type_label(schema.items)
        return f"array<{inner}>"
    label = base
    if schema.enum:
        shown = ", ".join(str(e) for e in schema.enum[:5])
        more = "…" if len(schema.enum) > 5 else ""
        label += f" ({shown}{more})"
    elif schema.format:
        label += f" ({schema.format})"
    return label


def param_type_label(param: Parameter) -> str:
    label = param.type
    if param.enum:
        shown = ", ".join(str(e) for e in param.enum[:5])
        more = "…" if len(param.enum) > 5 else ""
        label += f" ({shown}{more})"
    elif param.format:
        label += f" ({param.format})"
    return label


def flatten_schema(
    schema: SchemaNode | None,
    prefix: str = "",
    depth: int = 0,
    max_depth: int = 4,
) -> list[tuple[str, SchemaNode, bool]]:
    """Aplatit un schéma objet en lignes (chemins pointés pour l'imbrication)."""
    rows: list[tuple[str, SchemaNode, bool]] = []
    if schema is None or depth > max_depth:
        return rows
    if schema.type == "object" and schema.properties:
        for name, prop in schema.properties.items():
            path = f"{prefix}.{name}" if prefix else name
            rows.append((path, prop, name in schema.required))
            if prop.type == "object" and prop.properties:
                rows.extend(flatten_schema(prop, path, depth + 1, max_depth))
            elif prop.type == "array" and prop.items is not None and prop.items.properties:
                rows.extend(flatten_schema(prop.items, path + "[]", depth + 1, max_depth))
    elif schema.type == "array" and schema.items is not None:
        rows.extend(flatten_schema(schema.items, prefix + "[]", depth + 1, max_depth))
    if not prefix and schema.additional_properties is not None:
        rows.append(("*", schema.additional_properties, False))
    return rows


def example_from_schema(schema: SchemaNode | None, depth: int = 0, max_depth: int = 8) -> Any:
    """Construit un exemple JSON plausible depuis un schéma résolu."""
    if schema is None:
        return None
    if schema.example is not None:
        return schema.example
    if schema.default is not None:
        return schema.default
    if schema.enum:
        return schema.enum[0]
    if schema.type == "object":
        if depth >= max_depth:
            return {}
        names = [n for n in schema.required if n in schema.properties]
        if not names:
            names = list(schema.properties)[:6]
        return {
            n: example_from_schema(schema.properties[n], depth + 1, max_depth)
            for n in names
            if n in schema.properties
        }
    if schema.type == "array":
        if schema.items is None or depth >= max_depth:
            return []
        return [example_from_schema(schema.items, depth + 1, max_depth)]
    if schema.type == "integer":
        return 0
    if schema.type == "number":
        return 1.5
    if schema.type == "boolean":
        return True
    if schema.type == "any":
        return {}
    return _FORMAT_EXAMPLES.get(schema.format, "string")


def json_example(schema: SchemaNode | None) -> str:
    return json.dumps(example_from_schema(schema), ensure_ascii=False, indent=2)


def pick_body(route) -> tuple[str, SchemaNode] | None:
    """Choisit le content-type de body le plus pertinent pour l'exemple."""
    if route.request_body is None:
        return None
    ordered = sorted(
        route.request_body.content_types.items(),
        key=lambda kv: 0 if "json" in kv[0] else (1 if "form-urlencoded" in kv[0] else 2),
    )
    if not ordered:
        return None
    return ordered[0]
