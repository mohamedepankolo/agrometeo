"""Génère la documentation à remettre aux développeurs front-end, à partir du code lui-même :

    python scripts/export_docs.py     (depuis le dossier backend)

Produit  docs/openapi.json  (importable dans Postman, Insomnia, Swagger, openapi-generator…)
et       docs/API_REFERENCE.md  (référence lisible : chaque route, ses paramètres, ses champs, son accès).
Les routes de développement (/dev/*) sont exclues.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

os.environ.setdefault("ENV", "test")
os.environ.setdefault("JWT_SECRET", "docs-only-" + "x" * 40)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from app.main import app  # noqa: E402

DOCS = Path(__file__).resolve().parents[1] / "docs"
EXCLUDED_TAG = "Développement"
METHOD_ORDER = {"get": 0, "post": 1, "put": 2, "patch": 3, "delete": 4}


def resolve(spec: dict, schema: dict) -> dict:
    if "$ref" in schema:
        node = spec
        for part in schema["$ref"].lstrip("#/").split("/"):
            node = node[part]
        return node
    return schema


def type_of(spec: dict, schema: dict | bool) -> str:
    if isinstance(schema, bool) or not schema:
        return "quelconque"
    if "$ref" in schema:
        return schema["$ref"].split("/")[-1]
    if "anyOf" in schema:
        parts = [type_of(spec, s) for s in schema["anyOf"] if s.get("type") != "null"]
        return " ou ".join(parts) + (" (facultatif)" if any(s.get("type") == "null" for s in schema["anyOf"]) else "")
    if schema.get("enum"):
        return " \\| ".join(f"`{v}`" for v in schema["enum"])
    if schema.get("type") == "array":
        return f"liste de {type_of(spec, schema.get('items', {}))}"
    if schema.get("type") == "object" and "additionalProperties" in schema:
        return f"dictionnaire de {type_of(spec, schema['additionalProperties'])}"
    t = schema.get("type", "objet")
    return f"{t} ({schema['format']})" if schema.get("format") else t


def fields_table(spec: dict, schema: dict) -> list[str]:
    schema = resolve(spec, schema)
    if schema.get("type") == "array":
        return [f"Liste de : {type_of(spec, schema['items'])}"] + fields_table(spec, schema["items"])
    props = schema.get("properties")
    if not props:
        return []
    required = set(schema.get("required", []))
    rows = ["", "| Champ | Type | Obligatoire | Description |", "|---|---|---|---|"]
    for name, prop in props.items():
        desc = (prop.get("description") or "").replace("\n", " ")
        rows.append(f"| `{name}` | {type_of(spec, prop)} | {'oui' if name in required else ''} | {desc} |")
    return rows


def build_markdown(spec: dict) -> str:
    out = [f"# {spec['info']['title']} - référence des routes", "", spec["info"].get("description", "").strip(), "",
           "> Document généré automatiquement depuis le code (`python scripts/export_docs.py`). "
           "Le fichier `openapi.json` contient la même information dans un format importable par les outils.", ""]
    by_tag: dict[str, list] = {}
    for path, ops in spec["paths"].items():
        for method, op in ops.items():
            tag = (op.get("tags") or ["Autres"])[0]
            if tag.startswith(EXCLUDED_TAG):
                continue
            by_tag.setdefault(tag, []).append((path, method, op))
    order = [t["name"] for t in spec.get("tags", [])]
    for tag in sorted(by_tag, key=lambda t: order.index(t) if t in order else 99):
        desc = next((t["description"] for t in spec.get("tags", []) if t["name"] == tag), "")
        out += [f"## {tag}", "", desc, ""]
        for path, method, op in sorted(by_tag[tag], key=lambda x: (x[0], METHOD_ORDER.get(x[1], 9))):
            out += [f"### `{method.upper()} {path}`", "", (op.get("description") or op.get("summary") or "").strip(), ""]
            params = [resolve(spec, p) for p in op.get("parameters", [])]
            if params:
                out += ["**Paramètres**", "", "| Nom | Où | Obligatoire | Type | Description |", "|---|---|---|---|---|"]
                for p in params:
                    out.append(f"| `{p['name']}` | {p['in']} | {'oui' if p.get('required') else ''} | "
                               f"{type_of(spec, p.get('schema', {}))} | {(p.get('description') or '').replace(chr(10), ' ')} |")
                out.append("")
            body = op.get("requestBody", {}).get("content", {})
            if "application/json" in body:
                out += ["**Corps de la requête (JSON)**"] + fields_table(spec, body["application/json"]["schema"]) + [""]
            elif "multipart/form-data" in body:
                out += ["**Corps de la requête (multipart/form-data)**"] + fields_table(spec, body["multipart/form-data"]["schema"]) + [""]
            responses = []
            for code, resp in op.get("responses", {}).items():
                if code == "422":
                    continue
                schema = resp.get("content", {}).get("application/json", {}).get("schema")
                responses.append((code, schema, resp.get("description", "")))
            for code, schema, rdesc in responses:
                label = type_of(spec, schema) if schema else "aucun contenu"
                out += [f"**Réponse {code}** : {label}"]
                if schema:
                    out += fields_table(spec, schema)
                out += [""]
    enums = {name: sch["enum"] for name, sch in spec.get("components", {}).get("schemas", {}).items() if "enum" in sch}
    if enums:
        out += ["## Valeurs possibles (énumérations)", "", "| Type | Valeurs |", "|---|---|"]
        out += [f"| `{name}` | " + ", ".join(f"`{v}`" for v in values) + " |" for name, values in sorted(enums.items())]
        out.append("")
    return "\n".join(out)


def main() -> None:
    spec = app.openapi()
    spec["paths"] = {p: {m: op for m, op in ops.items() if not (op.get("tags") or [""])[0].startswith(EXCLUDED_TAG)}
                     for p, ops in spec["paths"].items()}
    spec["paths"] = {p: ops for p, ops in spec["paths"].items() if ops}
    DOCS.mkdir(exist_ok=True)
    (DOCS / "openapi.json").write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
    (DOCS / "API_REFERENCE.md").write_text(build_markdown(spec), encoding="utf-8")
    n = sum(len(ops) for ops in spec["paths"].values())
    print(f"{n} routes documentées -> {DOCS / 'openapi.json'} et {DOCS / 'API_REFERENCE.md'}")


if __name__ == "__main__":
    main()
