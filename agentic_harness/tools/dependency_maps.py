"""Pure ordered dependency-document parsing, independent of execution readiness."""
from __future__ import annotations

import re

import yaml


class _Loader(yaml.SafeLoader):
    pass


def _mapping(loader, node, deep=False):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if not isinstance(key, str) or key in result:
            raise ValueError("invalid or duplicate queue key")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_Loader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)


def parse(text: str, *, label: str) -> list[dict]:
    """Validate document order and shape, without consulting changes or archives.

    Keep historical installer identifiers supported. Coordination separately
    requires full change IDs and checks active/archived directory readiness.
    """
    try:
        if any(isinstance(token, (yaml.tokens.AliasToken, yaml.tokens.AnchorToken))
               for token in yaml.scan(text)):
            raise ValueError("YAML aliases are unsupported")
        value = yaml.load(text, Loader=_Loader)
        if not isinstance(value, dict) or set(value) != {"queue"} or not isinstance(value["queue"], list):
            raise ValueError("queue schema requires exactly a queue list")
        seen = set()
        for entry in value["queue"]:
            if not isinstance(entry, dict) or set(entry) != {"change", "depends_on"}:
                raise ValueError("queue entry requires exactly change and depends_on")
            name, deps = entry["change"], entry["depends_on"]
            if not isinstance(name, str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]*", name):
                raise ValueError("invalid change identifier")
            if name in seen:
                raise ValueError(f"duplicate full ID: {name}")
            if not isinstance(deps, list):
                raise ValueError(f"{name}: depends_on must be a list")
            if any(not isinstance(dep, str) for dep in deps):
                raise ValueError(f"{name}: invalid dependency identifier")
            if len(set(deps)) != len(deps):
                raise ValueError(f"{name}: duplicate dependency")
            if any(dep not in seen for dep in deps):
                raise ValueError(f"{name}: dependency missing, cyclic or out of order")
            seen.add(name)
        return value["queue"]
    except (yaml.YAMLError, ValueError) as exc:
        raise ValueError(f"invalid dependency map {label}: {exc}") from exc
