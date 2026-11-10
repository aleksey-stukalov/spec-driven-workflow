"""Published package guidance must remain reachable after extraction."""
from pathlib import Path
from urllib.parse import unquote, urlsplit

from markdown_it import MarkdownIt


ROOT = Path(__file__).resolve().parents[1]


def test_authored_markdown_links_resolve():
    paths = list(ROOT.glob("*.md"))
    for folder in ("docs", "agentic_harness/policies", "agentic_harness/procedures", "agentic_harness/roles", "openspec"):
        paths.extend((ROOT / folder).rglob("*.md"))
    paths.append(ROOT / "agentic_harness/README.md")
    parser = MarkdownIt()
    broken = []
    for path in paths:
        for token in parser.parse(path.read_text()):
            for child in token.children or []:
                if child.type not in {"link_open", "image"}:
                    continue
                href = child.attrGet("href" if child.type == "link_open" else "src")
                parts = urlsplit(href or "")
                if parts.scheme or parts.netloc or not parts.path:
                    continue
                target = path.parent / unquote(parts.path)
                if not target.exists():
                    broken.append(f"{path.relative_to(ROOT)}: {href}")
    assert not broken, "\n".join(broken)
