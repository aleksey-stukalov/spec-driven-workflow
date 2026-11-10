#!/usr/bin/env python3
"""Build the offline HTML handbook from installed sources; never change settings.

Normal mode writes only index.html. --check validates inputs and compares the
expected page without writing files. No provider, network or native adapter is
invoked. Markdown and plans.yaml remain the maintained process sources.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import math
import os
import re
import sys
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

# A check in a freshly installed package must not create import cache files.
sys.dont_write_bytecode = True
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

import yaml
from markdown_it import MarkdownIt
import plan_runtime

HARNESS = Path(__file__).resolve().parents[1]
MARKDOWN = MarkdownIt("commonmark", {"html": False}).enable("table")
ID = re.compile(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*\Z")
REQUIRED_SECTIONS = {
    "workflow": "procedures/pipeline.md", "start": "README.md",
    "reading": "policies/README.md", "plans": "policies/plans.md",
    "scope": "policies/repository.md", "development": "policies/development.md",
    "openspec": "policies/openspec.md", "execution": "procedures/execute.md",
    "design": "procedures/harden-change.md", "review": "procedures/review-impl.md",
    "evidence": "policies/execution.md", "roles": "roles/runtime.md",
}
REQUIRED_EDGES = {
    ("intake", "queue"), ("queue", "worktree"), ("worktree", "spec-author"),
    ("spec-author", "spec-contract-review"), ("spec-author", "spec-runtime-review"),
    ("spec-contract-review", "design-gate"), ("spec-runtime-review", "design-gate"),
    ("design-gate", "design-fix"), ("design-gate", "wave-plan"), ("wave-plan", "implementation"),
    ("implementation", "behavior-review"), ("implementation", "runtime-review"),
    ("behavior-review", "code-gate"), ("runtime-review", "code-gate"),
    ("code-gate", "code-fix"), ("code-gate", "final-verification"),
    ("design-fix", "spec-contract-review"), ("design-fix", "spec-runtime-review"),
    ("code-fix", "behavior-review"), ("code-fix", "runtime-review"),
    ("design-gate", "blocked"), ("code-gate", "blocked"),
    ("final-verification", "blocked"), ("final-verification", "code-fix"),
    ("final-verification", "pr-ready"), ("human-review", "code-fix"),
    ("pr-ready", "human-review"), ("human-review", "merge-authorization"),
    ("merge-authorization", "merge"), ("merge", "cleanup"),
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def fields(value, required, optional=()):
    require(isinstance(value, dict), "expected a mapping")
    require(set(required) <= value.keys() <= set(required) | set(optional),
            "missing or unknown fields: " + ", ".join(map(str, value)))


class UniqueLoader(yaml.SafeLoader):
    pass


def unique_mapping(loader, node, deep=False):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        require(isinstance(key, str), "YAML keys must be strings")
        require(key not in result, f"duplicate YAML key: {key}")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, unique_mapping)


def package_file(harness: Path, name: str) -> Path:
    """Inputs must be ordinary installed package files, never consumer files."""
    relative = Path(name)
    require(not relative.is_absolute() and ".." not in relative.parts,
            f"input outside the installed package: {name}")
    path = harness / relative
    require(path.is_file() and not any(p.is_symlink() for p in (path, *path.parents)
                                      if p != harness and p.is_relative_to(harness)),
            f"missing or symlinked package input: {name}")
    require(path.resolve().is_relative_to(harness.resolve()), f"input outside package: {name}")
    return path


def load_handbook(harness: Path = HARNESS) -> dict:
    data = yaml.load(package_file(harness, "handbook.yaml").read_text(), Loader=UniqueLoader)
    fields(data, ("schema_version", "sections", "graph"))
    require(type(data["schema_version"]) is int and data["schema_version"] == 1,
            "handbook.yaml: expected schema_version 1")
    sections = data["sections"]
    require(isinstance(sections, list), "handbook sections must be a list")
    for section in sections:
        fields(section, ("id", "path", "title"))
        require(all(isinstance(v, str) and v.strip() for v in section.values()), "invalid section")
        require(ID.fullmatch(section["id"]), "invalid section ID")
        package_file(harness, section["path"])
    require(len(sections) == len(REQUIRED_SECTIONS)
            and {s["id"]: s["path"] for s in sections} == REQUIRED_SECTIONS,
            "handbook must contain each canonical section ID/path exactly once")
    validate_graph(data["graph"])
    return data


def validate_graph(graph: dict) -> None:
    fields(graph, ("nodes", "edges"))
    nodes, edges = graph["nodes"], graph["edges"]
    require(isinstance(nodes, list) and isinstance(edges, list), "graph inventories must be lists")
    for node in nodes:
        fields(node, ("id", "role", "label", "details"))
        require(isinstance(node["id"], str) and ID.fullmatch(node["id"]), "invalid graph node ID")
        require(node["role"] in {"human", "lead", "spec-author", "coder", "spec-reviewer",
                                 "runtime-reviewer", "behavior-reviewer"}, "invalid graph role")
        require(isinstance(node["label"], str) and node["label"].strip(), "empty graph node label")
        require(isinstance(node["details"], list)
                and all(isinstance(s, str) and s.strip() for s in node["details"]), "invalid node details")
    ids = {node["id"] for node in nodes}
    require(len(ids) == len(nodes), "graph requires unique node IDs")
    for edge in edges:
        fields(edge, ("id", "from", "to", "kind", "condition"), ("caption",))
        require(all(isinstance(edge[k], str) and edge[k].strip()
                    for k in ("id", "from", "to", "kind", "condition")), "invalid graph edge")
        require(ID.fullmatch(edge["id"]), "invalid graph edge ID")
        require(edge["kind"] in {"forward", "fix", "blocked"}, "invalid edge kind")
        require(isinstance(edge.get("caption", []), list)
                and all(isinstance(s, str) and s.strip() for s in edge.get("caption", [])),
                "invalid edge caption")
    pairs = {(e["from"], e["to"]) for e in edges}
    require(len({e["id"] for e in edges}) == len(edges) == len(pairs), "duplicate graph edge")
    require(REQUIRED_EDGES <= pairs and all(a in ids and b in ids for a, b in pairs),
            "graph has a missing gate, fix loop or invalid endpoint")
    require(not any(a == "blocked" for a, _ in pairs), "blocked must remain terminal")

    def reachable(start, omitted=frozenset()):
        visited = {start} - omitted
        while True:
            expanded = visited | {b for a, b in pairs if a in visited and b not in omitted}
            if expanded == visited:
                return visited
            visited = expanded

    require(reachable("intake") == ids, "graph contains unreachable nodes")
    design_reviews = {"spec-contract-review", "spec-runtime-review"}
    code_reviews = {"behavior-review", "runtime-review"}
    design_gates = [design_reviews, {"design-gate"}, {"implementation"}]
    code_gates = [code_reviews, {"code-gate"}, {"final-verification"}]
    merge_gates = [{"pr-ready"}, {"human-review"}, {"merge-authorization"}]
    paths = [
        ("intake", "pr-ready", [{"queue"}, {"worktree"}, {"spec-author"},
                                 {"wave-plan"}] + design_gates + code_gates),
        ("intake", "merge", merge_gates),
        ("intake", "cleanup", [{"merge"}]),
        ("design-fix", "pr-ready", design_gates + code_gates),
        ("code-fix", "pr-ready", code_gates),
        ("design-fix", "merge", design_gates + code_gates + merge_gates),
        ("code-fix", "merge", code_gates + merge_gates),
    ]
    for start, target, gates in paths:
        for gate in gates:
            require(target not in reachable(start, gate),
                    f"graph bypasses required gate {','.join(sorted(gate))}: {start} -> {target}")
    # Color and captions must not turn a failure or repair into an accepted path.
    for edge in edges:
        repair = edge["from"] in {"design-fix", "code-fix"} or edge["to"] in {"design-fix", "code-fix"}
        expected = "blocked" if edge["to"] == "blocked" else "fix" if repair else "forward"
        require(edge["kind"] == expected, f"graph edge kind contradicts topology: {edge['id']}")


def layout_attributes(attrs, *, box=False):
    required = {"class", "x", "y", "width", "height", "rx"} if box else {"class", "x", "y"}
    fields(attrs, required, () if box else ("text-anchor",))
    require(isinstance(attrs["class"], str) and re.fullmatch(r"[a-z][a-z -]*", attrs["class"]),
            "invalid SVG class")
    if "text-anchor" in attrs:
        require(attrs["text-anchor"] in {"start", "middle", "end"}, "invalid text anchor")
    for key in required - {"class"}:
        value = attrs[key]
        require(isinstance(value, (str, int, float)) and not isinstance(value, bool)
                and re.fullmatch(r"-?(?:\d+(?:\.\d+)?|\.\d+)", str(value))
                and math.isfinite(float(value)) and float(value) >= 0, "invalid SVG geometry")
    return {k: str(v) for k, v in attrs.items()}


def svg_graph(handbook: dict, harness: Path = HARNESS) -> str:
    frame = package_file(harness, "templates/diagram-frame.svg").read_text()
    require(frame.count("<!-- GRAPH -->") == 1, "SVG frame needs exactly one graph placeholder")
    require(not re.search(r"<!DOCTYPE|<!ENTITY", frame, re.I), "unsupported SVG declaration")
    parsed = ET.fromstring(frame)
    require(parsed.tag == "svg", "SVG frame requires an svg root")
    for element in parsed.iter():
        require(element.tag in {"svg", "title", "desc", "defs", "marker", "path", "rect", "text"},
                "unsupported SVG frame element")
        require(not any(k.lower().startswith("on") or k in {"href", "src", "style"}
                        or ":" in k or k.startswith("{") for k in element.attrib),
                "unsupported SVG frame attribute")
    layout = yaml.load(package_file(harness, "templates/graph-layout.yaml").read_text(), Loader=UniqueLoader)
    fields(layout, ("nodes", "edges"))
    require(isinstance(layout["nodes"], dict) and isinstance(layout["edges"], dict), "invalid graph layout")
    require(set(layout["nodes"]) == {n["id"] for n in handbook["graph"]["nodes"]}
            and set(layout["edges"]) == {e["id"] for e in handbook["graph"]["edges"]},
            "graph layout inventory differs from handbook")
    nodes, edges = [], []
    for node in handbook["graph"]["nodes"]:
        position = layout["nodes"][node["id"]]
        fields(position, ("box", "text_positions"))
        require(isinstance(position["text_positions"], list)
                and len(position["text_positions"]) == len(node["details"]) + 1,
                "node label layout differs from handbook")
        group = ET.Element("g", {"data-node": node["id"], "data-role": node["role"]})
        ET.SubElement(group, "rect", layout_attributes(position["box"], box=True))
        for text, attrs in zip([node["label"], *node["details"]], position["text_positions"], strict=True):
            ET.SubElement(group, "text", layout_attributes(attrs)).text = text
        nodes.append(ET.tostring(group, encoding="unicode"))
    for edge in handbook["graph"]["edges"]:
        position = layout["edges"][edge["id"]]
        fields(position, ("path", "caption_positions"))
        require(isinstance(position["path"], str)
                and re.fullmatch(r"[MmLlHhVvCcSsQqTtAaZz0-9., +\-]+", position["path"]), "invalid SVG path data")
        css = "edge" + {"forward": "", "fix": " loop-edge", "blocked": " stop-edge"}[edge["kind"]]
        el = ET.Element("path", {"class": css, "data-edge": edge["id"], "data-from": edge["from"],
                                "data-to": edge["to"], "data-condition": edge["condition"], "d": position["path"]})
        ET.SubElement(el, "title").text = edge["condition"]
        edges.append(ET.tostring(el, encoding="unicode"))
        require(isinstance(position["caption_positions"], list)
                and len(edge.get("caption", [])) == len(position["caption_positions"]),
                "edge caption layout differs from handbook")
        for caption, attrs in zip(edge.get("caption", []), position["caption_positions"], strict=True):
            label = ET.Element("text", layout_attributes(attrs))
            label.text = caption
            edges.append(ET.tostring(label, encoding="unicode"))
    return frame.replace("<!-- GRAPH -->", "\n".join(nodes + edges))


def slug(value: str) -> str:
    value = re.sub(r"<[^>]*>", "", value).lower()
    return re.sub(r"[^\w\- ]", "", value).replace(" ", "-") or "section"


def heading_ids(tokens):
    """Use visible inline text and stable suffixes, including duplicate headings."""
    used = set()
    result = {}
    for i, token in enumerate(tokens):
        if token.type != "heading_open":
            continue
        inline = tokens[i + 1]
        visible = "".join(child.content for child in inline.children or []
                          if child.type in {"text", "code_inline", "image", "html_inline"})
        base = slug(visible or inline.content)
        anchor, suffix = base, 0
        while anchor in used:
            suffix += 1
            anchor = f"{base}-{suffix}"
        used.add(anchor)
        result[i] = anchor
    return result


def headings(source: str) -> set[str]:
    return set(heading_ids(MARKDOWN.parse(source)).values())


class HTMLReferences(HTMLParser):
    """Collect anchors and links; reject active content or automatic resources."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hrefs = []
        self.anchors = set()
        self.h1_count = 0

    def handle_starttag(self, tag, attrs):
        require(tag not in {"script", "link", "img", "iframe", "object", "embed", "audio", "video", "source", "base"},
                f"handbook must be self-contained: unsupported {tag} element")
        values = dict(attrs)
        require(not any(k.startswith("on") or k in {"src", "srcset", "xlink:href"} for k in values),
                "handbook must not load resources or run scripts")
        require(not (tag == "meta" and "http-equiv" in values), "unsupported automatic navigation")
        if values.get("href") is not None:
            require(tag == "a", "only ordinary anchor links may have href")
            require(urlsplit(values["href"]).scheme.lower() in {"", "http", "https", "mailto"},
                    "unsupported link protocol")
            self.hrefs.append(values["href"])
        if tag == "h1":
            self.h1_count += 1
        for key in ("id", "name"):
            if values.get(key):
                require(values[key] not in self.anchors, f"duplicate HTML anchor: {values[key]}")
                self.anchors.add(values[key])


def validate_html_links(root: Path, documents: dict[Path, str]) -> None:
    """Resolve references against virtual output first, including first builds."""
    root = root.resolve()
    virtual = {p.resolve(): body for p, body in documents.items()}
    for path, text in virtual.items():
        if path.suffix.lower() not in {".html", ".htm"}:
            continue
        parser = HTMLReferences()
        parser.feed(text)
        for href in parser.hrefs:
            url = urlsplit(href)
            if url.scheme or url.netloc:
                continue
            target = (path.parent / unquote(url.path)).resolve() if url.path else path
            require(target.is_relative_to(root) and (target in virtual or target.exists()),
                    f"broken local HTML link: {href}")
            if not url.fragment:
                continue
            body = virtual.get(target)
            if body is None and target.suffix.lower() in {".md", ".html", ".htm"}:
                body = target.read_text()
            if target.suffix.lower() == ".md":
                anchors = headings(body or "")
            elif target.suffix.lower() in {".html", ".htm"}:
                target_parser = HTMLReferences()
                target_parser.feed(body or "")
                anchors = target_parser.anchors
            else:
                anchors = set()
            require(unquote(url.fragment) in anchors, f"broken local HTML fragment: {href}")


def table(headers, rows, *, table_id):
    cell = lambda value: html.escape(str(value))
    head = "".join(f'<th scope="col">{cell(value)}</th>' for value in headers)
    body = "".join("<tr>" + "".join(f"<td>{cell(value)}</td>" for value in row) + "</tr>" for row in rows)
    return f'<div class="table-scroll"><table id="{table_id}"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def catalog_tables(catalog):
    """Render exact validated routes and allowances, not a second role catalog."""
    plans = list(catalog["plans"])
    headers = ["Role / workflow step"] + [p + (" — default" if p == catalog["default"] else "") for p in plans]
    rows = []
    for step in catalog["steps"]:
        row = [step["label"]]
        for name in plans:
            rule = catalog["plans"][name]["steps"][step["id"]]
            if step["id"] == "human":
                row.append("Human decision; no model or attempt allowance")
            else:
                routes = "; ".join(f"{provider.title()}: {route['model']} / {route['effort']}"
                                   for provider, route in rule["routes"].items())
                row.append(f"{routes}; minimum {rule['minimum']}, maximum {rule['maximum']}; count: {step['scope']}")
        rows.append(row)
    result = '<h3 id="catalog-routes">Model routes and attempt allowances</h3>' + table(headers, rows, table_id="plan-routes")
    result += table(["Plan", "Complete clean review rounds"],
                    [(name, plan["clean_rounds"]) for name, plan in catalog["plans"].items()], table_id="plan-clean-rounds")
    result += '<h3 id="catalog-context">Context targets</h3>' + table(
        ["Profile", "Initial packet", "Working input", "Result", "Handoff", "Scoped authority"],
        [(name, *(profile[k] for k in ("initial_tokens", "working_tokens", "result_tokens", "handoff_tokens")),
          "Required" if profile["requires_authority"] else "Ordinary assignment")
         for name, profile in catalog["profiles"].items()], table_id="context-profiles")
    roles = '<h3 id="catalog-roles">Responsibilities and permitted writes</h3>' + table(
        ["Step", "Count scope", "Context profile", "Permitted writes", "Boundary"],
        [(step["label"], step["scope"], step["context_profile"], step["permitted_writes"], step["boundary"])
         for step in catalog["steps"]], table_id="role-boundaries")
    return result, roles


def fingerprint(harness, sources):
    names = {"handbook.yaml", "plans.yaml", "templates/handbook.css", "templates/diagram-frame.svg",
             "templates/graph-layout.yaml", "tools/build.py", "tools/plan_runtime.py", "uv.lock"}
    inputs = {name: package_file(harness, name).read_bytes() for name in names}
    inputs.update({p.relative_to(harness.resolve()).as_posix(): text.encode("utf-8") for p, text in sources.items()})
    digest = hashlib.sha256()
    for name, body in sorted(inputs.items()):
        digest.update(name.encode("utf-8") + b"\0" + str(len(body)).encode("ascii") + b"\0" + body)
    return digest.hexdigest()


def render_html(handbook: dict, sources: dict[Path, str], catalog: dict, harness: Path = HARNESS) -> str:
    section_map = {(harness / s["path"]).resolve(): s["id"] for s in handbook["sections"]}
    graph = svg_graph(handbook, harness)
    plan_tables, role_tables = catalog_tables(catalog)
    sections = []
    for section in handbook["sections"]:
        path = (harness / section["path"]).resolve()
        tokens = MARKDOWN.parse(sources[path])
        anchors = heading_ids(tokens)
        for i, token in enumerate(tokens):
            if token.type in {"heading_open", "heading_close"}:
                level = int(token.tag[1:])
                # HTML has six levels; preserve deeper source levels accessibly.
                token.tag = "h" + str(min(level + 1, 6))
                if token.type == "heading_open":
                    token.attrSet("id", section["id"] + "--" + anchors[i])
                    if level == 6:
                        token.attrSet("aria-level", "7")
            for child in token.children or []:
                require(child.type != "image", "handbook images require a reviewed inline presentation template")
                if child.type != "link_open":
                    continue
                href = child.attrGet("href")
                url = urlsplit(href)
                if url.scheme or url.netloc:
                    continue
                target = (path.parent / unquote(url.path)).resolve() if url.path else path
                if target in section_map:
                    anchor = section_map[target] + ("--" + unquote(url.fragment) if url.fragment else "")
                    child.attrSet("href", "#" + quote(anchor))
                else:
                    local = Path(os.path.relpath(target, harness)).as_posix()
                    child.attrSet("href", quote(local) + ("?" + url.query if url.query else "")
                                  + ("#" + url.fragment if url.fragment else ""))
        rendered = MARKDOWN.renderer.render(tokens, MARKDOWN.options, {})
        rendered = rendered.replace("<table>", '<div class="table-scroll"><table>').replace("</table>", "</table></div>")
        if section["id"] == "workflow":
            figure = ('<figure><div class="diagram-wrap" role="region" tabindex="0" '
                      'aria-label="Development flow: scroll horizontally">' + graph + '</div>'
                      '<figcaption>One complete implementation change. Review-only requests stop within their authorized phase; '
                      'the arrows do not grant publication or merge authority.</figcaption></figure>')
            rendered = rendered.replace("</h2>", "</h2>" + figure, 1)
        if section["id"] == "plans":
            rendered += plan_tables
        if section["id"] == "roles":
            rendered += role_tables
        sections.append(f'<section id="{section["id"]}">{rendered}</section>')
    css = package_file(harness, "templates/handbook.css").read_text()
    require("</style" not in css.lower() and not re.search(r"@import|@font-face", css, re.I),
            "CSS must remain inline and self-contained")
    require(all(re.fullmatch(r"#[a-zA-Z][\w-]*", value.strip(" \"'"))
                for value in re.findall(r"url\s*\(([^)]*)\)", css, re.I)), "external CSS resource")
    nav = "".join(f'<a href="#{s["id"]}">{html.escape(s["title"])}</a>' for s in handbook["sections"])
    plans = " · ".join(name + (" (default)" if name == catalog["default"] else "") for name in catalog["plans"])
    source_hash = fingerprint(harness, sources)
    return f'''<!doctype html>
<!-- Generated by tools/build.py; edit Markdown, plans.yaml, handbook.yaml and templates. Source SHA256: {source_hash} -->
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Spec-driven workflow handbook</title><style>{css}</style></head>
<body><main class="page"><header><p class="eyebrow">Spec-driven workflow / Development handbook</p>
<h1>How a task becomes<br>a verified change.</h1>
<p class="status">PLANS: {html.escape(plans)}</p>
<p>Runtime: {html.escape(catalog['policy_version'])}. At most {catalog['max_workers']} workers; nested delegation is {'enabled' if catalog['nested_delegation'] else 'disabled'}.</p>
<p class="lede">Markdown is the agent entrypoint. This offline handbook is generated from the same policies, procedures and plan catalog.</p>
<p><a href="#reading">Agent reading map</a> · <a href="plans.yaml">Plan catalog</a> · <a href="handbook.yaml">Diagram and section sources</a></p></header>
<nav aria-label="Handbook sections">{nav}</nav>{''.join(sections)}
<footer>Generated from installed Markdown, plans.yaml, handbook.yaml and presentation templates. Mutable run state and original evidence stay outside versioned documentation.</footer>
</main></body></html>
'''


def expected_outputs(harness: Path = HARNESS) -> dict[Path, str]:
    harness = Path(harness).resolve()
    handbook = load_handbook(harness)
    catalog = plan_runtime.load_catalog(package_file(harness, "plans.yaml"))
    sources = {package_file(harness, s["path"]).resolve(): package_file(harness, s["path"]).read_text()
               for s in handbook["sections"]}
    output = harness / "index.html"
    require(not output.is_symlink(), "index.html must not be a symlink")
    document = render_html(handbook, sources, catalog, harness)
    parser = HTMLReferences()
    parser.feed(document)
    require(parser.h1_count == 1, "handbook must have exactly one page H1")
    validate_html_links(harness, {**sources, output: document})
    return {output: document}


def main(argv=None, *, harness=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="read-only: reject stale or missing index.html")
    args = parser.parse_args(argv)
    try:
        outputs = expected_outputs(Path(harness) if harness is not None else HARNESS)
        stale = [p for p, text in outputs.items() if not p.is_file() or p.read_bytes() != text.encode("utf-8")]
        require(not args.check or not stale, "stale or missing generated handbook: index.html; run tools/build.py")
        if not args.check:
            for path in stale:
                path.write_bytes(outputs[path].encode("utf-8"))
        print("handbook " + ("verified" if args.check else "generated") + ": index.html")
        return 0
    except (ValueError, KeyError, TypeError, OSError, yaml.YAMLError, ET.ParseError) as exc:
        print(f"handbook: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
