"""Validate bounded local intake and risk; never read or mutate remote services.

Ticket evidence is an external original JSON observation with schema_version=1,
kind='observed-ticket', verified=true, observed_at=<timezone-aware ISO timestamp>
and ticket=<the exact selected ticket payload, excluding its evidence locator>.
An evidence hash binds that original; it does not authenticate a remote server or
prove no newer remote edit exists. The caller supplies the current observation.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
import re

import yaml

import projects

ACTIONS = frozenset({"planning", "review", "implementation", "writer", "publish", "merge", "cleanup", "escalate"})
FLAGS = frozenset({"documentation", "mechanical", "recovery", "schema", "security",
                   "external_mutation", "concurrency", "data_migration", "uncertain"})
HIGH_FLAGS = FLAGS - {"documentation", "mechanical"}
CHANGE = re.compile(r"\d{2}-\d{2}-\d{2}-\d{3}-[a-z0-9]+(?:-[a-z0-9]+)*\Z")
TICKET_FIELDS = {"id", "revision", "problem", "outcome", "scope", "acceptance", "project", "change",
                 "spec_links", "dependencies", "relationships"}


def _text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label}: nonempty string required")
    return value


def _strings(value, label, *, empty=False):
    if not isinstance(value, list) or (not value and not empty):
        raise ValueError(f"{label}: {'possibly empty' if empty else 'nonempty'} list required")
    for item in value:
        _text(item, label)
    if len(set(value)) != len(value):
        raise ValueError(f"{label}: duplicate entries")
    return list(value)


def _paths(value, label, root=None, *, allow_root=False):
    result = _strings(value, label)
    for item in result:
        path = Path(item)
        if allow_root and item == ".":
            continue
        if path.is_absolute() or "\\" in item or "\0" in item or any(part in ("", ".", "..") for part in item.split("/")):
            raise ValueError(f"{label}: canonical repository-relative paths required")
        if root is not None:
            absolute = root / path
            if not absolute.resolve().is_relative_to(root) or any(root.joinpath(*path.parts[:n]).is_symlink()
                                                                for n in range(1, len(path.parts) + 1)):
                raise ValueError(f"{label}: aliased or escaped path")
    return sorted(result)


def classify_risk(paths, declared_flags=None):
    """Classify concrete scope without waiving independent lenses or upgrading models."""
    paths = _paths(paths, "risk paths", allow_root=True)
    flags = _strings([] if declared_flags is None else declared_flags, "declared_flags", empty=True)
    if set(flags) - FLAGS:
        raise ValueError(f"unknown risk flags: {sorted(set(flags) - FLAGS)}")
    inferred, reasons = set(flags), []
    vocabulary = {"recover": "recovery", "recovery": "recovery", "coordination": "concurrency",
                  "claim": "concurrency", "claims": "concurrency", "schema": "schema",
                  "migration": "data_migration", "migrations": "data_migration", "security": "security",
                  "auth": "security", "authorization": "security", "credentials": "security",
                  "permissions": "security", "lifecycle": "external_mutation"}
    for path in paths:
        tokens = set(re.split(r"[/_.-]+", path.lower()))
        matched = sorted({flag for token, flag in vocabulary.items() if token in tokens})
        for flag in matched:
            inferred.add(flag)
            reasons.append(f"{path}: {flag} path")
    if inferred & HIGH_FLAGS:
        category = "high"
    elif all(Path(path).suffix.lower() in {".md", ".rst", ".txt"} for path in paths) or "mechanical" in inferred:
        category = "low"
        inferred.add("documentation" if "mechanical" not in inferred else "mechanical")
        reasons.append("bounded document or explicitly declared mechanical scope")
    else:
        category = "standard"
        reasons.append("application behavior or development tooling scope")
    return {"category": category, "flags": sorted(inferred), "reasons": sorted(set(reasons)),
            "required_reviewers": 2, "fresh_review_identities_required": True,
            "automatic_model_upgrade": False, "escalation_requires_explicit_authority": True}


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate original evidence key: {key}")
        result[key] = value
    return result


def skips_specs(directory: Path) -> bool:
    """Read an explicit no-behavior-change declaration without inferring one."""
    metadata = directory / ".openspec.yaml"
    if directory.is_symlink() or metadata.is_symlink():
        raise ValueError("change metadata must not use a symlink")
    if not metadata.exists():
        return False
    try:
        policy = yaml.load(metadata.read_text(), Loader=projects.UniqueLoader)
    except yaml.YAMLError as exc:
        raise ValueError(f"invalid change metadata: {exc}") from exc
    if not isinstance(policy, dict) or ("skip_specs" in policy and type(policy["skip_specs"]) is not bool):
        raise ValueError("change metadata requires a boolean skip_specs declaration")
    return policy.get("skip_specs", False)


def _ticket(ticket, request, project, change, scope, root):
    if (not isinstance(ticket, dict) or set(ticket) - {"verified"} != TICKET_FIELDS | {"evidence"}
            or ("verified" in ticket and ticket["verified"] is not True)):
        raise ValueError("implementation requires a complete verified selected bounded ticket")
    for field in ("id", "revision", "problem", "outcome", "project", "change"):
        _text(ticket[field], f"ticket.{field}")
    if (ticket["project"], ticket["change"]) != (project, change):
        raise ValueError("selected ticket project/change mismatch")
    if ticket["problem"] != request["problem"] or ticket["outcome"] != request["outcome"]:
        raise ValueError("selected ticket problem/outcome is stale for current intake")
    if _paths(ticket["scope"], "ticket.scope", root, allow_root=True) != scope:
        raise ValueError("selected ticket scope mismatch")
    if _strings(ticket["acceptance"], "ticket.acceptance") != request["acceptance"]:
        raise ValueError("selected ticket acceptance is stale for current intake")
    links = _paths(ticket["spec_links"], "ticket.spec_links", root)
    if root is not None:
        selected = projects.resolve(project, root)
        change_path = Path(selected["root"]) / "openspec/changes" / change
        if not all(any(projects.scope_contains(area, path) for area in projects.editable_areas(selected)) for path in scope):
            raise ValueError("selected ticket scope exceeds registered project areas")
    else:
        suffix = ("openspec", "changes", change, "proposal.md")
        proposals = [Path(path) for path in links if Path(path).parts[-4:] == suffix]
        if len(proposals) != 1:
            raise ValueError("ticket requires exact owning change proposal link")
        change_path = proposals[0].parent
    proposal = (change_path / "proposal.md").as_posix()
    if proposal not in links:
        raise ValueError("ticket requires exact owning change proposal link")
    for path in links:
        if not Path(path).is_relative_to(change_path):
            raise ValueError("ticket spec link belongs to another change")
        if root is not None and not (root / path).is_file():
            raise ValueError(f"ticket spec link missing: {path}")
    skipped = root is not None and skips_specs(root / change_path)
    deltas = list((root / change_path / "specs").glob("*/spec.md")) if root is not None else []
    capability_links = [path for path in links if Path(path).is_relative_to(change_path / "specs") and Path(path).name == "spec.md"]
    if skipped:
        if deltas or capability_links:
            raise ValueError("skip_specs contradicts capability deltas")
        if (change_path / ".openspec.yaml").as_posix() not in links:
            raise ValueError("no-behavior-change ticket requires its skip_specs metadata link")
    elif not capability_links:
        raise ValueError("ticket requires owning capability specification links")
    for dependency in _strings(ticket["dependencies"], "ticket.dependencies", empty=True):
        parts = dependency.split(":")
        if len(parts) != 2 or not re.fullmatch(r"[a-z][a-z0-9_-]*", parts[0]) or not CHANGE.fullmatch(parts[1]):
            raise ValueError("ticket dependencies require project-qualified full change IDs")
    _strings(ticket["relationships"], "ticket.relationships", empty=True)
    locator = ticket["evidence"]
    if not isinstance(locator, dict) or set(locator) != {"path", "sha256"}:
        raise ValueError("ticket evidence requires original path and sha256")
    path = Path(_text(locator["path"], "ticket.evidence.path"))
    sha = _text(locator["sha256"], "ticket.evidence.sha256")
    if not re.fullmatch(r"[a-f0-9]{64}", sha) or not path.is_absolute() or path.is_symlink() or path.absolute() != path.resolve():
        raise ValueError("ticket evidence requires canonical absolute path and SHA-256")
    if root is not None and path.resolve().is_relative_to(root):
        raise ValueError("ticket original evidence must remain outside repository content")
    try:
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != sha:
            raise ValueError("ticket original evidence hash mismatch")
        observation = json.loads(data, object_pairs_hook=_unique_object)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"ticket original evidence unavailable or invalid: {exc}") from exc
    if not isinstance(observation, dict) or set(observation) != {"schema_version", "kind", "verified", "observed_at", "ticket"}:
        raise ValueError("ticket original observation schema invalid")
    if type(observation["schema_version"]) is not int or observation["schema_version"] != 1 or observation["kind"] != "observed-ticket" or observation["verified"] is not True:
        raise ValueError("ticket original observation is not verified")
    try:
        observed_at = datetime.fromisoformat(observation["observed_at"])
        if observed_at.tzinfo is None:
            raise ValueError("timezone missing")
    except (ValueError, TypeError) as exc:
        raise ValueError("ticket observation requires a timezone-aware timestamp") from exc
    payload = {**{field: ticket[field] for field in TICKET_FIELDS}, "scope": scope, "spec_links": links}
    original = observation["ticket"]
    if not isinstance(original, dict) or set(original) != TICKET_FIELDS:
        raise ValueError("selected ticket differs from original observed evidence (stale or mismatched)")
    canonical_original = {**original, "scope": _paths(original["scope"], "observed ticket.scope", root, allow_root=True),
                          "spec_links": _paths(original["spec_links"], "observed ticket.spec_links", root)}
    if canonical_original != payload:
        raise ValueError("selected ticket differs from original observed evidence (stale or mismatched)")
    return {**payload, "evidence": dict(locator), "verified": True}


def _validate_intake(record, repository_root=None):
    """Return normalized mode/allowed_actions; all malformed inputs raise ValueError.

    Action grants apply only to their exact project/change and bounded paths.
    Writer permission is derived from explicit implementation authority plus a
    verified selected ticket. Issue IDs and branch names establish no authority.
    """
    if not isinstance(record, dict):
        raise ValueError("intake record must be an object")
    required = {"schema_version", "mode", "project", "change", "scope", "request", "authorities", "ticket"}
    optional = {"declared_flags", "review_policy", "risk", "allowed_actions"}
    if not required <= set(record) or set(record) - required - optional:
        raise ValueError("intake schema missing required or contains unknown fields")
    if type(record["schema_version"]) is not int or record["schema_version"] != 1:
        raise ValueError("intake schema_version must be 1")
    mode, project, change = record["mode"], record["project"], record["change"]
    if mode not in ("planning", "review", "implementation"):
        raise ValueError("intake mode must be planning, review or implementation")
    if not isinstance(project, str) or not re.fullmatch(r"[a-z][a-z0-9_-]*", project):
        raise ValueError("invalid project ID")
    if not isinstance(change, str) or not CHANGE.fullmatch(change):
        raise ValueError("full stable change ID required")
    root = Path(repository_root).resolve() if repository_root is not None else None
    if root is not None and not root.is_dir():
        raise ValueError("repository root missing")
    scope = _paths(record["scope"], "scope", root, allow_root=True)
    request = record["request"]
    if not isinstance(request, dict) or set(request) != {"problem", "outcome", "acceptance"}:
        raise ValueError("request requires problem, outcome and acceptance")
    request = {"problem": _text(request["problem"], "request.problem"),
               "outcome": _text(request["outcome"], "request.outcome"),
               "acceptance": _strings(request["acceptance"], "request.acceptance")}
    if not isinstance(record["authorities"], list) or not record["authorities"]:
        raise ValueError("explicit action authority sources required")
    grants, authorities = set(), []
    for authority in record["authorities"]:
        if not isinstance(authority, dict) or set(authority) != {"source", "project", "change", "scope", "actions"}:
            raise ValueError("authority requires source, project/change, scope and actions")
        source = _text(authority["source"], "authority.source")
        if (re.fullmatch(r"#?\d+|main|master|develop|development", source, re.I)
                or re.match(r"(?:issue|branch|feat|fix|origin|refs)[/:#]", source, re.I)
                or re.match(r"https?://[^/]+/.+/(?:issues|pull)/\d+(?:[/?#].*)?$", source, re.I)):
            raise ValueError("issue numbers, issue URLs and branch names are context, not action authority")
        if (authority["project"], authority["change"]) != (project, change):
            raise ValueError("authority project/change mismatch")
        authorized_scope = _paths(authority["scope"], "authority.scope", root, allow_root=True)
        actions = _strings(authority["actions"], "authority.actions")
        if set(actions) - ACTIONS:
            raise ValueError("unknown authority action")
        if not all(any(projects.scope_contains(owned, path) for owned in authorized_scope) for path in scope):
            raise ValueError("authority does not cover bounded intake scope")
        grants.update(actions)
        authorities.append({**authority, "scope": authorized_scope, "actions": sorted(actions)})
    if mode not in grants:
        raise ValueError(f"{mode} action requires explicit matching authority")
    ticket = record["ticket"]
    if mode == "implementation" or ticket is not None:
        ticket = _ticket(ticket, request, project, change, scope, root)
    allowed = grants - {"writer", "implementation"}
    if mode == "implementation":
        allowed.update({"implementation", "writer"})
    elif mode == "planning":
        allowed.discard("review")
    review_policy = record.get("review_policy", {"required_reviewers": 2, "fresh_review_identities_required": True})
    if (not isinstance(review_policy, dict) or set(review_policy) != {"required_reviewers", "fresh_review_identities_required"}
            or type(review_policy["required_reviewers"]) is not int or review_policy["required_reviewers"] != 2
            or review_policy["fresh_review_identities_required"] is not True):
        raise ValueError("risk never exempts two fresh independent review identities")
    flags = record.get("declared_flags", [])
    risk = classify_risk(scope, flags)
    allowed = sorted(allowed)
    if "risk" in record and record["risk"] != risk:
        raise ValueError("supplied risk classification differs from computed scope")
    if "allowed_actions" in record and record["allowed_actions"] != allowed:
        raise ValueError("supplied allowed_actions differs from verified authority")
    return {"schema_version": 1, "mode": mode, "project": project, "change": change, "scope": scope,
            "request": request, "authorities": authorities, "ticket": ticket,
            "declared_flags": list(flags), "review_policy": dict(review_policy), "risk": risk, "allowed_actions": allowed}


def validate_intake(record, repository_root=None):
    """Strict intake validation; malformed records and unavailable evidence raise ValueError."""
    try:
        return _validate_intake(record, repository_root)
    except (OSError, TypeError, RuntimeError) as exc:
        raise ValueError(f"intake evidence or path validation failed: {exc}") from exc
