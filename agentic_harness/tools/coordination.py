"""Host-local queue/workspace coordination, independent of historical budget-v1.

CLI: ``coordination.py ACTION --repository PATH --request request.json``.
Requests use the keyword arguments of the public functions below. Registered
project resolution supplies ``project_id``, ``root``, ``queue_path`` and the
optional ``environment`` policy; a project with no locks is valid.
This module never selects an ambiguous project or infers action authority.
SQLite lives under the resolved Git common directory, not in tracked files.
Separate clones/machines are outside this exclusion domain. Pins are the hook
for source bundles, original evidence, imports, configurations and environments.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import sqlite3
import subprocess
import time
import uuid

import yaml
from dependency_maps import parse as parse_dependency_map


class CoordinationError(ValueError):
    """A specific conservative blocker; no conflicting operation was authorized."""


def require(value, label):
    if not isinstance(value, str) or not value.strip():
        raise CoordinationError(f"{label}: nonempty reference required")
    return value


def git(repository, *args):
    result = subprocess.run(["git", "-C", str(repository), *map(str, args)],
                            capture_output=True, check=False)
    if result.returncode:
        raise CoordinationError(f"git {args[0]}: {result.stderr.decode(errors='replace').strip()}")
    return result.stdout.decode(errors="surrogateescape").strip()


def common_dir(repository):
    return Path(git(repository, "rev-parse", "--path-format=absolute", "--git-common-dir")).resolve()


def pinned_commit(repository, revision):
    require(revision, "base_revision")
    resolved = git(repository, "rev-parse", "--verify", f"{revision}^{{commit}}")
    if resolved != revision:
        raise CoordinationError("base_revision must be a full immutable commit ID")
    return resolved


CHANGE = re.compile(r"\d{2}-\d{2}-\d{2}-\d{3}-[a-z0-9]+(?:-[a-z0-9]+)*\Z")


def environment_policy(value=None):
    """Normalize declared target-project dependencies without invoking tools."""
    if value is None:
        value = {}
    if not isinstance(value, dict) or set(value) - {"lockfiles", "prepare"}:
        raise CoordinationError("environment requires lockfiles and prepare only")
    locks, commands = value.get("lockfiles", []), value.get("prepare", [])
    if not isinstance(locks, list) or any(not isinstance(p, str) or not p for p in locks):
        raise CoordinationError("environment lockfiles must be explicit repository-relative files")
    if len(set(locks)) != len(locks):
        raise CoordinationError("environment lockfiles contain duplicates")
    for relative in locks:
        if (Path(relative).is_absolute() or "\\" in relative or "\0" in relative
                or any(part in {"", ".", "..", ".git"} for part in relative.split("/"))):
            raise CoordinationError("environment lockfiles must be canonical repository-relative files")
    if (not isinstance(commands, list)
            or any(not isinstance(command, list) or not command
                   or any(not isinstance(arg, str) or not arg or "\0" in arg for arg in command)
                   for command in commands)):
        raise CoordinationError("environment prepare commands must be nonempty argv arrays")
    return {"lockfiles": sorted(locks), "prepare": [list(command) for command in commands]}


def lock_inventory(root, policy):
    """Fingerprint each declared file; absence is a recorded state, never a skip.

    This detects additions, deletions and edits of declared locks. It never
    guesses a package manager from files in the tree or executes prepare commands.
    """
    root = Path(root).resolve()
    result = {}
    for relative in environment_policy(policy)["lockfiles"]:
        path = root / relative
        if (not path.resolve().is_relative_to(root)
                or any(root.joinpath(*Path(relative).parts[:n]).is_symlink()
                       for n in range(1, len(Path(relative).parts) + 1))):
            raise CoordinationError(f"dependency lock is aliased or outside workspace: {relative}")
        if not path.exists():
            result[relative] = None
            continue
        if not path.is_file():
            raise CoordinationError(f"dependency lock must be a regular owned file: {relative}")
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, "rb") as stream:
            before = os.fstat(stream.fileno())
            content = stream.read()
            after = os.fstat(stream.fileno())
            current = path.stat(follow_symlinks=False)
        identity = lambda info: (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_mode)
        if identity(before) != identity(after) or identity(current) != identity(before):
            raise CoordinationError(f"dependency lock changed during fingerprint: {relative}")
        result[relative] = hashlib.sha256(content).hexdigest()
    return result


def _claim_environment(claim):
    if "environment_policy" not in claim:
        raise CoordinationError("historical environment policy requires its original runtime")
    return environment_policy(claim["environment_policy"])


def _base_locks(repository, base, policy):
    """Reject non-file locks in the pinned base before creating a worktree."""
    for relative in environment_policy(policy)["lockfiles"]:
        parts = Path(relative).parts
        for length in range(1, len(parts) + 1):
            prefix = Path(*parts[:length]).as_posix()
            raw = subprocess.check_output(
                ["git", "-C", str(repository), "ls-tree", "-z", base, "--", prefix])
            entries = [entry for entry in raw.split(b"\0") if entry]
            if not entries:
                break
            header, name = entries[0].split(b"\t", 1)
            mode, kind, _ = header.decode().split()
            expected_kind = "blob" if length == len(parts) else "tree"
            if (len(entries) != 1 or name.decode() != prefix or kind != expected_kind
                    or (expected_kind == "blob" and mode not in {"100644", "100755"})):
                raise CoordinationError(f"declared dependency lock is not a regular file in base: {relative}")


@dataclass(frozen=True)
class Project:
    project_id: str
    root: Path
    queue_path: Path
    environment: dict | None = None

    def __post_init__(self):
        if not re.fullmatch(r"[a-z][a-z0-9_-]*", self.project_id):
            raise CoordinationError("invalid project_id")
        root, queue = Path(self.root).resolve(), Path(self.queue_path).resolve()
        if not root.is_dir() or not queue.is_file() or not queue.is_relative_to(root):
            raise CoordinationError("registered project root/queue missing or outside root")
        object.__setattr__(self, "root", root)
        object.__setattr__(self, "queue_path", queue)
        object.__setattr__(self, "environment", environment_policy(self.environment))
        common_dir(root)  # Reject a registration that is not in a repository.

    @property
    def changes(self):
        return self.queue_path.parent / "changes"

    def qualified(self, change):
        if not isinstance(change, str) or not CHANGE.fullmatch(change):
            raise CoordinationError(f"invalid full change ID: {change!r}")
        return f"{self.project_id}:{change}"


class _UniqueLoader(yaml.SafeLoader):
    """Strict metadata loader; dependency documents use the shared parser."""


def _mapping(loader, node, deep=False):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if not isinstance(key, str) or key in result:
            raise CoordinationError(f"invalid or duplicate queue key: {key!r}")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)


def validate_queue(project):
    """Validate ordered syntax, then separately require execution-ready changes."""
    try:
        document = parse_dependency_map(project.queue_path.read_text(), label=str(project.queue_path))
    except (ValueError, UnicodeError) as exc:
        raise CoordinationError(str(exc)) from exc
    seen, entries = set(), []
    for item in document:
        name, deps = item["change"], item["depends_on"]
        qualified = project.qualified(name)
        for dep in deps:
            project.qualified(dep)
        active = project.changes / name
        archived = list((project.changes / "archive").glob(f"????-??-??-{name}"))
        archived = [path for path in archived if path.is_dir()]
        if int(active.is_dir()) + len(archived) != 1:
            raise CoordinationError(f"{qualified}: missing or ambiguous change directory")
        entries.append({**item, "id": qualified, "status": "active" if active.is_dir() else "archived"})
        seen.add(name)
    if not project.changes.is_dir():
        raise CoordinationError("missing project changes directory")
    unlisted = sorted(p.name for p in project.changes.iterdir()
                      if p.is_dir() and p.name != "archive" and p.name not in seen)
    if unlisted:
        raise CoordinationError(f"active changes missing from queue: {unlisted}")
    return entries


def _accepted(project, base_revision):
    top = Path(git(project.root, "rev-parse", "--show-toplevel"))
    archive = (project.changes / "archive").relative_to(top).as_posix()
    paths = git(project.root, "ls-tree", "-r", "--name-only", base_revision, "--", archive).splitlines()
    # Require actual committed proposal bytes, not a mutable archived directory.
    return {match.group(1) for path in paths
            if (match := re.fullmatch(re.escape(archive) + r"/\d{4}-\d{2}-\d{2}-(.+)/proposal\.md", path))}


def planning_readiness(project, change):
    directory = project.changes / change
    blockers = [f"missing {name}" for name in ("proposal.md", "design.md", "tasks.md")
                if not (directory / name).is_file()]
    tasks = (directory / "tasks.md").read_text() if (directory / "tasks.md").is_file() else ""
    total = len(re.findall(r"^\s*- \[[ xX]\] .+", tasks, re.M))
    if not total:
        blockers.append("empty task list")
    metadata_file = directory / '.openspec.yaml'
    metadata = yaml.load(metadata_file.read_text(), Loader=_UniqueLoader) if metadata_file.is_file() else {}
    skipped = isinstance(metadata, dict) and metadata.get('skip_specs') is True
    proposal = (directory / 'proposal.md').read_text() if (directory / 'proposal.md').is_file() else ''
    declared = re.search(r'(?ms)^### New Capabilities\s*\n(.*?)(?=^### |^## |\Z)', proposal)
    if skipped and declared and declared.group(1).strip().lower() not in {'none', 'none.', ''}:
        blockers.append('skip_specs cannot omit a declared new capability')
    if not skipped and not any((directory / "specs").glob("*/spec.md")):
        blockers.append("missing capability deltas")
    return {"planning_ready": not blockers, "blockers": blockers, "tasks": total,
            "specs_skipped": skipped,
            "implemented": False, "verified": False, "accepted": False}


def select_next(project, base_revision, explicit=None, store=None):
    """Read-only selection. Claimed/unready candidates block; they are not skipped."""
    entries = validate_queue(project)
    pinned_commit(project.root, base_revision)
    accepted = _accepted(project, base_revision)
    if explicit is not None:
        project.qualified(explicit)
        if explicit not in {e["change"] for e in entries}:
            raise CoordinationError("explicit change missing from queue")
    skipped = []
    for entry in entries:
        if explicit is not None and entry["change"] != explicit:
            continue
        if entry["status"] == "archived":
            if explicit:
                return {"candidate": entry["id"], "ready": False, "blockers": ["already archived"], "skipped": []}
            continue
        missing = [d for d in entry["depends_on"] if d not in accepted]
        if missing:
            detail = {"id": entry["id"], "blockers": [f"dependency absent from pinned base: {d}" for d in missing]}
            if explicit:
                return {"candidate": entry["id"], "ready": False, **detail, "skipped": []}
            skipped.append(detail)
            continue
        readiness = planning_readiness(project, entry["change"])
        claim = store.get_claim(entry["id"]) if store else None
        if claim and claim["state"] not in ("released", "completed"):
            readiness["blockers"].append(f"claim {claim['state']} owned by {claim['owner']} (generation {claim['generation']})")
        return {"candidate": entry["id"], "ready": not readiness["blockers"],
                **readiness, "skipped": skipped, "claim": claim}
    return {"candidate": None, "ready": False, "blockers": [], "skipped": skipped}


def canonical_location(path, allowed_root):
    raw, allowed = Path(path).absolute(), Path(allowed_root).resolve()
    canonical = raw.resolve()
    if raw != canonical or canonical == allowed or not canonical.is_relative_to(allowed):
        raise CoordinationError("workspace alias or path outside canonical allowed location")
    return canonical


def source_state(path):
    """Content revision includes tracked and intended untracked, excludes ignored data."""
    digest = hashlib.sha256()
    head = git(path, "rev-parse", "HEAD")
    digest.update(head.encode() + b"\0")
    index = subprocess.run(["git", "-C", str(path), "ls-files", "--stage", "-z"],
                           capture_output=True, check=True).stdout
    digest.update(index)
    listed = subprocess.run(["git", "-C", str(path), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                            capture_output=True, check=True).stdout
    names = listed.decode(errors="surrogateescape").split("\0")
    for name in sorted(set(filter(None, names))):
        file = Path(path) / name
        digest.update(name.encode(errors="surrogateescape") + b"\0")
        if any((Path(path).joinpath(*Path(name).parts[:n])).is_symlink()
               for n in range(1, len(Path(name).parts))):
            digest.update(b"missing")
        elif file.is_symlink():
            digest.update(b"link\0" + os.readlink(file).encode())
        elif file.is_file():
            digest.update(b"file\0" + str(file.stat().st_mode & 0o777).encode() + b"\0" + file.read_bytes())
        else:
            digest.update(b"missing")
    if git(path, "rev-parse", "HEAD") != head:
        raise CoordinationError("source HEAD changed during revision capture")
    return {"head": head, "content_revision": digest.hexdigest(),
            "dirty": bool(git(path, "status", "--porcelain", "--untracked-files=all"))}


class CoordinationStore:
    """All mutations serialize on BEGIN IMMEDIATE; reads never create state."""
    def __init__(self, repository):
        self.repository = Path(repository).resolve()
        self.repository_id = str(common_dir(repository))
        self.path = Path(self.repository_id) / "agentic-harness" / "coordination.sqlite3"

    @contextmanager
    def transaction(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("CREATE TABLE IF NOT EXISTS records(kind TEXT, key TEXT, data TEXT, PRIMARY KEY(kind,key))")
            connection.execute("CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY, at REAL, kind TEXT, key TEXT, data TEXT)")
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def records(self, kind):
        if not self.path.exists():
            return []
        connection = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True, timeout=30)
        try:
            return [json.loads(row[0]) for row in connection.execute("SELECT data FROM records WHERE kind=?", (kind,))]
        finally:
            connection.close()

    @staticmethod
    def _all(db, kind):
        return [json.loads(r[0]) for r in db.execute("SELECT data FROM records WHERE kind=?", (kind,))]

    @staticmethod
    def _get(db, kind, key):
        row = db.execute("SELECT data FROM records WHERE kind=? AND key=?", (kind, key)).fetchone()
        return json.loads(row[0]) if row else None

    @staticmethod
    def _put(db, kind, key, data):
        payload = json.dumps(data, sort_keys=True)
        db.execute("INSERT OR REPLACE INTO records VALUES (?,?,?)", (kind, key, payload))
        db.execute("INSERT INTO events(at,kind,key,data) VALUES (?,?,?,?)", (time.time(), kind, key, payload))
        return data

    def get_claim(self, qualified):
        return next((r for r in self.records("claim") if r["id"] == qualified), None)

    def claim(self, project, change, run, session, owner, branch, worktree,
              base_revision, authorization, lease_seconds=300, pid=None):
        for name, value in locals().copy().items():
            if name in ("run", "session", "owner", "branch", "authorization"):
                require(value, name)
        if str(common_dir(project.root)) != self.repository_id:
            raise CoordinationError("project belongs to another repository")
        selected = select_next(project, base_revision, explicit=change)
        if not selected["ready"]:
            raise CoordinationError(f"change not executable: {selected['blockers']}")
        key = project.qualified(change)
        with self.transaction() as db:
            old = self._get(db, "claim", key)
            if old and old["state"] not in ("released", "completed"):
                raise CoordinationError(f"existing claim: {json.dumps(old, sort_keys=True)}")
            record = dict(id=key, project=project.project_id, change=change, claim_id=uuid.uuid4().hex,
                          repository_id=self.repository_id, generation=(old or {}).get("generation", 0) + 1,
                          run=run, session=session, owner=owner, branch=branch,
                          worktree=str(Path(worktree).resolve()), base_revision=base_revision,
                          authorization=authorization, input_revision=base_revision, state="claimed", host=socket.gethostname(),
                          pid=os.getpid() if pid is None else pid, heartbeat_at=time.time(),
                          lease_expires_at=time.time() + lease_seconds, recovery={},
                          environment_policy=environment_policy(project.environment))
            return self._put(db, "claim", key, record)

    def _owned(self, db, qualified, generation, session):
        record = self._get(db, "claim", qualified)
        if not record or record["generation"] != generation or record["session"] != session:
            raise CoordinationError("claim generation/session compare-and-set conflict")
        if record["state"] in ("released", "completed"):
            raise CoordinationError("claim is already settled")
        return record

    def transition(self, qualified, generation, session, state, authorization, recovery=None):
        require(authorization, "authorization")
        if state not in ("running", "blocked", "released", "completed"):
            raise CoordinationError("invalid claim transition")
        with self.transaction() as db:
            record = self._owned(db, qualified, generation, session)
            if state in ("released", "completed") and any(
                a["claim"] == qualified and a["state"] != "released" for a in self._all(db, "assignment")
            ):
                raise CoordinationError("assignment reservations must settle and release first")
            record.update(state=state, generation=generation + 1, heartbeat_at=time.time(),
                          authorization=authorization)
            if recovery is not None:
                record["recovery"] = recovery
            return self._put(db, "claim", qualified, record)

    def pin(self, path, kind, reference, authorization):
        """Explicit pins: import, resume, evidence, source, environment or external use."""
        for label, value in (("kind", kind), ("reference", reference), ("authorization", authorization)):
            require(value, label)
        record = {"id": uuid.uuid4().hex, "path": str(Path(path).resolve()), "kind": kind,
                  "reference": reference, "authorization": authorization, "active": True}
        with self.transaction() as db:
            return self._put(db, "pin", record["id"], record)

    def unpin(self, pin_id, authorization):
        require(authorization, "authorization")
        with self.transaction() as db:
            record = self._get(db, "pin", pin_id)
            if not record:
                raise CoordinationError("unknown pin")
            record.update(active=False, released_by=authorization)
            return self._put(db, "pin", pin_id, record)

    def reserve(self, qualified, generation, session, assignment_id, run, files,
                input_revision, tests, output, authorization, mode="writer", capacity=1):
        for label, value in (("assignment_id", assignment_id), ("run", run),
                             ("input_revision", input_revision), ("output", output), ("authorization", authorization)):
            require(value, label)
        if mode not in ("writer", "reviewer") or type(capacity) is not int or capacity not in (1, 2):
            raise CoordinationError("invalid assignment mode/capacity")
        if not isinstance(files, list) or not files or not isinstance(tests, list) or not tests:
            raise CoordinationError("assignment requires exclusive files and tests")
        with self.transaction() as db:
            claim = self._owned(db, qualified, generation, session)
            if run != claim["run"]:
                raise CoordinationError("assignment run differs from stable claim run")
            workspace = self._get(db, "workspace", claim["worktree"])
            if not workspace:
                raise CoordinationError("owned workspace required")
            import projects
            paths = []
            for relative in files:
                try:
                    path = projects.assignment_path(Path(claim["worktree"]), relative)
                except ValueError as exc:
                    # A reviewer may reserve an immutable deleted original below
                    # a newly linked discovery directory. Writers never may.
                    import evidence
                    if mode != "reviewer" or evidence._lexical_exists(Path(claim["worktree"]), relative):
                        raise CoordinationError(f"invalid assignment path: {exc}") from exc
                    try:
                        evidence._tree(self.repository_id, claim["base_revision"], relative)
                    except ValueError as original_error:
                        raise CoordinationError(f"invalid deleted review path: {original_error}") from original_error
                    path = Path(claim["worktree"]) / relative
                paths.append(str(path))
            current = source_state(claim["worktree"])
            if current["content_revision"] != input_revision:
                raise CoordinationError("assignment source revision changed")
            active = [a for a in self._all(db, "assignment") if a["state"] != "released"]
            if self._get(db, "assignment", assignment_id):
                raise CoordinationError("assignment identity already used; reconcile or use fresh identity")
            if sum(a["capacity"] for a in active if a["run"] == run) + capacity > 2:
                raise CoordinationError("aggregate two-worker reservation exceeded")
            if mode == "reviewer" and Path(output).resolve().is_relative_to(claim["worktree"]):
                raise CoordinationError("reviewer outputs must use separately owned scratch space")
            if any(_related_paths(Path(output).resolve(), a["output"]) for a in active):
                raise CoordinationError("assignment output already reserved")
            if mode == "writer":
                if any(f["path"] == claim["worktree"] and f["active"] for f in self._all(db, "freeze")):
                    raise CoordinationError("source frozen for review")
                for other in active:
                    if other["mode"] == "writer" and any(
                        Path(a).is_relative_to(b) or Path(b).is_relative_to(a)
                        for a in paths for b in other["files"]
                    ):
                        raise CoordinationError("overlapping writer assignment")
            elif not any(f["path"] == claim["worktree"] and f["active"] and
                         f["revision"] == input_revision for f in self._all(db, "freeze")):
                raise CoordinationError("review requires frozen source revision")
            record = dict(id=assignment_id, claim=qualified, run=run, files=paths,
                          input_revision=input_revision, tests=tests, output=str(Path(output).resolve()),
                          authorization=authorization, mode=mode, capacity=capacity, state="running")
            return self._put(db, "assignment", assignment_id, record)

    def settle(self, assignment_id, result_reference, authorization):
        require(result_reference, "complete original result_reference")
        require(authorization, "authorization")
        with self.transaction() as db:
            record = self._get(db, "assignment", assignment_id)
            if not record or record["state"] != "running":
                raise CoordinationError("assignment is not running")
            record.update(state="settled", result_reference=result_reference, settled_by=authorization)
            return self._put(db, "assignment", assignment_id, record)

    def release_assignments(self, run, authorization):
        require(authorization, "authorization")
        with self.transaction() as db:
            records = [a for a in self._all(db, "assignment") if a["run"] == run and a["state"] != "released"]
            if any(a["state"] != "settled" for a in records):
                raise CoordinationError("all launched siblings must settle before releasing reservations")
            for record in records:
                record.update(state="released", released_by=authorization)
                self._put(db, "assignment", record["id"], record)
            return records

    def freeze(self, path, expected_revision, authorization):
        require(authorization, "authorization")
        path = str(Path(path).resolve())
        with self.transaction() as db:
            if not self._get(db, "workspace", path):
                raise CoordinationError("unowned workspace")
            if any(a["mode"] == "writer" and a["state"] != "released" and
                   any(Path(f).is_relative_to(path) for f in a["files"]) for a in self._all(db, "assignment")):
                raise CoordinationError("writers must settle before freezing")
            if source_state(path)["content_revision"] != expected_revision:
                raise CoordinationError("review source revision changed")
            old = self._get(db, "freeze", path)
            if old and old["active"]:
                raise CoordinationError("review interval already frozen")
            return self._put(db, "freeze", path, dict(path=path, revision=expected_revision,
                                                    active=True, authorization=authorization))

    def thaw(self, path, authorization):
        require(authorization, "authorization")
        path = str(Path(path).resolve())
        with self.transaction() as db:
            record = self._get(db, "freeze", path)
            if not record or not record["active"]:
                raise CoordinationError("no frozen review interval")
            if any(a["mode"] == "reviewer" and a["state"] != "released" and
                   a["input_revision"] == record["revision"] for a in self._all(db, "assignment")):
                raise CoordinationError("review assignments have not settled/released")
            record.update(active=False, valid=source_state(path)["content_revision"] == record["revision"])
            return self._put(db, "freeze", path, record)


def _workspace_record(store, db, qualified, generation, session, path, allowed_root,
                      environment, configuration, authorization, create):
    require(authorization, "authorization")
    require(configuration, "configuration ownership reference")
    path = canonical_location(path, allowed_root)
    environment = canonical_location(environment, path)
    claim = store._owned(db, qualified, generation, session)
    if claim["worktree"] != str(path):
        raise CoordinationError("claim bound to a different workspace")
    if store._get(db, "workspace", str(path)):
        raise CoordinationError("workspace already owned; use resume")
    if create:
        if path.exists():
            raise CoordinationError("workspace path exists; adoption must be explicit")
        # Git refuses branches already checked out, without altering the shared tree.
        git(store.repository, "check-ref-format", "--branch", claim["branch"])
        git(store.repository, "worktree", "add", "-b", claim["branch"], path, claim["base_revision"])
    if str(common_dir(path)) != store.repository_id:
        raise CoordinationError("workspace belongs to another repository")
    if git(path, "symbolic-ref", "--short", "HEAD") != claim["branch"]:
        raise CoordinationError("workspace branch mismatch")
    if Path(git(path, "rev-parse", "--show-toplevel")).resolve() != path:
        raise CoordinationError("workspace path is not a worktree root")
    # Adoption does not silently bless arbitrary ancestor branches.
    if not create and git(path, "rev-parse", "HEAD") != claim["base_revision"]:
        raise CoordinationError("adoption requires exact pinned base HEAD")
    state = source_state(path)
    if state["dirty"]:
        raise CoordinationError("unowned dirty workspace cannot be adopted")
    policy = _claim_environment(claim)
    locks = lock_inventory(path, policy)
    record = dict(path=str(path), allowed_root=str(Path(allowed_root).resolve()),
                  claim=qualified, repository_id=store.repository_id, branch=claim["branch"],
                  base_revision=claim["base_revision"], owner=claim["owner"], run=claim["run"],
                  environment=str(environment), configuration=configuration,
                  environment_policy=policy, lockfiles=locks, authorization=authorization,
                  expected_source=state, recovery={}, state="owned")
    return store._put(db, "workspace", str(path), record)


def create_workspace(store, qualified, generation, session, path, allowed_root,
                     environment, configuration, authorization):
    """Create only a separate worktree, preserving shared dirty/runtime state."""
    # Persist intent before invoking Git, so a crash after Git succeeds cannot
    # erase knowledge of the attempted mutation. An exact clean checkout can
    # then be explicitly adopted; no automatic replay or deletion is attempted.
    require(authorization, "authorization")
    require(configuration, "configuration ownership reference")
    canonical = canonical_location(path, allowed_root)
    canonical_location(environment, canonical)
    with store.transaction() as db:
        claim = store._owned(db, qualified, generation, session)
        if claim["worktree"] != str(canonical):
            raise CoordinationError("claim bound to a different workspace")
        if canonical.exists() or store._get(db, "workspace", str(canonical)):
            raise CoordinationError("workspace path exists or already owned; use adopt/resume")
        # Never put a development tree inside another checkout.
        for line in git(store.repository, "worktree", "list", "--porcelain").splitlines():
            if line.startswith("worktree ") and _related_paths(canonical, Path(line[9:]).resolve()):
                raise CoordinationError("workspace location overlaps an existing worktree")
        # Validate declared dependencies before Git can create a checkout.
        # Missing declared locks are bound as absent, including an empty set.
        policy = _claim_environment(claim)
        _base_locks(store.repository, claim['base_revision'], policy)
        store._put(db, "workspace-intent", str(canonical), dict(
            path=str(canonical), claim=qualified, generation=generation,
            branch=claim["branch"], base_revision=claim["base_revision"],
            environment=str(Path(environment).resolve()), configuration=configuration,
            environment_policy=policy,
            authorization=authorization, state="attempted"))
    with store.transaction() as db:
        result = _workspace_record(store, db, qualified, generation, session, path, allowed_root,
                                   environment, configuration, authorization, True)
        intent = store._get(db, "workspace-intent", str(canonical))
        intent["state"] = "completed"
        store._put(db, "workspace-intent", str(canonical), intent)
        return result


def adopt_workspace(store, qualified, generation, session, path, allowed_root,
                    environment, configuration, authorization):
    with store.transaction() as db:
        return _workspace_record(store, db, qualified, generation, session, path, allowed_root,
                                 environment, configuration, authorization, False)


def _inspect_workspace(store, record, *, check_lock=True):
    path = canonical_location(record["path"], record["allowed_root"])
    if str(common_dir(path)) != record["repository_id"]:
        raise CoordinationError("workspace repository identity changed")
    if git(path, "symbolic-ref", "--short", "HEAD") != record["branch"]:
        raise CoordinationError("workspace branch changed")
    pinned_commit(path, record["base_revision"])
    # Base must still be an ancestor even when owned commits have advanced HEAD.
    git(path, "merge-base", "--is-ancestor", record["base_revision"], "HEAD")
    if "environment_policy" not in record or "lockfiles" not in record:
        raise CoordinationError("historical environment binding requires its original runtime")
    if check_lock and lock_inventory(path, record["environment_policy"]) != record["lockfiles"]:
        raise CoordinationError("dependency lock changed; reconcile environment explicitly")
    return source_state(path)



def validate_workspace_binding(store, qualified, generation, session, path, project, change, run, base_revision):
    """Read-only validation of the exact execution checkout, never merely its bytes."""
    canonical = Path(path).absolute()
    if canonical != canonical.resolve() or not store.path.is_file():
        raise CoordinationError("dispatch workspace is aliased or has no ownership record")
    db = sqlite3.connect(f"file:{store.path}?mode=ro", uri=True, timeout=30)
    try:
        db.execute("BEGIN")
        claim = store._owned(db, qualified, generation, session)
        expected = dict(id=f"{project}:{change}", project=project, change=change, run=run,
                        worktree=str(canonical), base_revision=base_revision, repository_id=store.repository_id)
        if any(claim.get(key) != value for key, value in expected.items()):
            raise CoordinationError("dispatch scope/root/base differs from exact owned claim")
        if claim["state"] not in ("claimed", "running"):
            raise CoordinationError("dispatch claim is blocked pending reconciliation")
        record = store._get(db, "workspace", str(canonical))
        if not record or record.get("state") != "owned" or record.get("claim") != qualified:
            raise CoordinationError("dispatch workspace ownership is unresolved")
        for field in ("branch", "base_revision", "run", "owner", "repository_id"):
            if record.get(field) != claim.get(field):
                raise CoordinationError(f"dispatch workspace/claim {field} mismatch")
        if record.get("path") != str(canonical):
            raise CoordinationError("dispatch workspace canonical root mismatch")
        if record.get("environment_policy") != _claim_environment(claim):
            raise CoordinationError("dispatch workspace environment policy differs from owned claim")
        source = _inspect_workspace(store, record)
        return {"claim": claim, "workspace": record, "source": source}
    finally:
        db.close()


def resume_workspace(store, qualified, generation, session, authorization,
                     expected_source=None, reconciliation=None):
    """Dirty/changed sources require a concrete reconciliation; never reset them.

    Reconciliation retains opaque references to the run's ledger, decisions,
    original results and mutation receipts. It does not mark them successful.
    """
    require(authorization, "authorization")
    with store.transaction() as db:
        claim = store._owned(db, qualified, generation, session)
        record = store._get(db, "workspace", claim["worktree"])
        if not record or record["claim"] != qualified:
            raise CoordinationError("unresolved workspace ownership")
        for field in ("branch", "base_revision", "run", "owner"):
            if record[field] != claim[field]:
                raise CoordinationError(f"workspace/claim {field} ownership mismatch")
        actual = _inspect_workspace(store, record)
        if any(a["claim"] == qualified and a["state"] != "released" for a in store._all(db, "assignment")):
            raise CoordinationError("assignments require reconciliation before resume")
        if any(p["active"] and p["kind"] in ("import", "environment", "live") and
               _related_paths(p["path"], record["path"]) for p in store._all(db, "pin")):
            raise CoordinationError("live import/environment ownership prevents resume")
        if actual != record["expected_source"] or actual["dirty"]:
            if expected_source != actual or not isinstance(reconciliation, dict):
                raise CoordinationError(f"dirty/changed source requires exact reconciliation: {json.dumps(actual)}")
            for field in ("original_results", "budget_ledger", "decisions", "operation_receipts"):
                require(reconciliation.get(field), f"reconciliation.{field}")
            record["recovery"] = reconciliation
        record["expected_source"] = actual
        record["resumed_by"] = authorization
        return store._put(db, "workspace", record["path"], record)


def _alive(pid, host):
    if host != socket.gethostname() or type(pid) is not int or pid <= 0:
        return None
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except (PermissionError, OSError):
        return None


def recover_claim(store, qualified, generation, session, new_session, new_owner,
                  authorization, expected_source, reconciliation):
    """Explicit CAS recovery only after stopped owner and full source reconciliation.

    Lease expiry is deliberately not consulted. Unknown liveness blocks recovery.
    The run ID, consumed budget references and original history survive takeover.
    """
    for field, value in (("new_session", new_session), ("new_owner", new_owner), ("authorization", authorization)):
        require(value, field)
    if not isinstance(reconciliation, dict):
        raise CoordinationError("reconciliation record required")
    for field in ("original_results", "budget_ledger", "decisions", "operation_receipts"):
        require(reconciliation.get(field), f"reconciliation.{field}")
    with store.transaction() as db:
        claim = store._owned(db, qualified, generation, session)
        if _alive(claim["pid"], claim["host"]) is not False:
            raise CoordinationError("former owner live or liveness unknown; expiry does not transfer ownership")
        if any(a["claim"] == qualified and a["state"] != "released" for a in store._all(db, "assignment")):
            raise CoordinationError("unfinished assignments prevent takeover")
        workspace = store._get(db, "workspace", claim["worktree"])
        if not workspace:
            raise CoordinationError("workspace ownership unavailable for recovery")
        actual = _inspect_workspace(store, workspace)
        if expected_source != actual:
            raise CoordinationError("recovery source revision differs from reconciled input")
        if any(p["active"] and p["kind"] in ("import", "environment", "live") and
               _related_paths(p["path"], workspace["path"]) for p in store._all(db, "pin")):
            raise CoordinationError("import/environment ownership prevents takeover")
        workspace.update(expected_source=actual, recovery=reconciliation, owner=new_owner)
        store._put(db, "workspace", workspace["path"], workspace)
        claim.update(session=new_session, owner=new_owner, pid=os.getpid(), host=socket.gethostname(),
                     generation=generation + 1, state="blocked", recovery=reconciliation,
                     authorization=authorization, heartbeat_at=time.time())
        return store._put(db, "claim", qualified, claim)



def rebind_environment(store, qualified, generation, session, authority, expected_source, preparation):
    """Explicitly accept a verified preparation of an owned workspace environment.

    This records a new binding, never prepares/replaces an environment or resets
    a claim, logical run, assignment history or budget ledger. The external JSON
    observation attests the caller's completed local preparation; no provider or
    package manager is invoked here.
    """
    fields = {"source", "project", "change", "run", "session", "actions"}
    if not isinstance(authority, dict) or set(authority) != fields:
        raise CoordinationError("environment rebind requires scoped current authority")
    require(authority["source"], "authority.source")
    if authority["actions"] != ["rebind-environment"]:
        raise CoordinationError("authority must explicitly permit rebind-environment")
    if not isinstance(preparation, dict) or set(preparation) != {"path", "sha256"}:
        raise CoordinationError("preparation requires an external original path and hash")
    receipt_path = Path(require(preparation["path"], "preparation.path"))
    if not receipt_path.is_absolute() or receipt_path != receipt_path.resolve() or receipt_path.is_symlink():
        raise CoordinationError("preparation receipt must be canonical and external")
    expected_hash = require(preparation["sha256"], "preparation.sha256")
    if not re.fullmatch(r"[a-f0-9]{64}", expected_hash):
        raise CoordinationError("preparation requires SHA-256")
    try:
        original = receipt_path.read_bytes()
        if hashlib.sha256(original).hexdigest() != expected_hash:
            raise CoordinationError("preparation original hash mismatch")
        receipt = json.loads(original, object_pairs_hook=_unique_receipt)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CoordinationError(f"preparation original unavailable or invalid: {exc}") from exc
    required = {"schema_version", "kind", "receipt_id", "verified", "repository_id", "project", "change", "run",
                "session", "worktree", "branch", "base_revision", "environment", "environment_policy", "lockfiles", "expected_source"}
    if not isinstance(receipt, dict) or set(receipt) != required:
        raise CoordinationError("environment preparation receipt schema invalid")
    if (type(receipt["schema_version"]) is not int or receipt["schema_version"] != 2
            or receipt["kind"] != "environment-preparation" or receipt["verified"] is not True):
        raise CoordinationError("environment preparation must be verified schema 2")
    require(receipt["receipt_id"], "preparation.receipt_id")
    if not isinstance(expected_source, dict) or set(expected_source) != {"head", "content_revision", "dirty"}:
        raise CoordinationError("exact expected_source required")
    with store.transaction() as db:
        claim = store._owned(db, qualified, generation, session)
        for field in ("project", "change", "run", "session"):
            if authority[field] != claim[field] or receipt[field] != claim[field]:
                raise CoordinationError(f"environment preparation authority/claim {field} mismatch")
        record = store._get(db, "workspace", claim["worktree"])
        if not record or record.get("state") != "owned" or record.get("claim") != qualified:
            raise CoordinationError("environment rebind workspace ownership unresolved")
        for field in ("branch", "base_revision", "run", "owner", "repository_id"):
            if record.get(field) != claim.get(field):
                raise CoordinationError(f"environment rebind workspace/claim {field} mismatch")
        if (receipt["environment_policy"] != record.get("environment_policy")
                or record.get("environment_policy") != claim.get("environment_policy")):
            raise CoordinationError("environment preparation differs from pinned project policy")
        path = canonical_location(record["path"], record["allowed_root"])
        if str(path) != claim["worktree"] or receipt_path.is_relative_to(path):
            raise CoordinationError("preparation original must survive owned worktree removal")
        for entry in git(path, "worktree", "list", "--porcelain", "-z").split("\0"):
            if entry.startswith("worktree ") and receipt_path.is_relative_to(Path(entry[9:]).resolve()):
                raise CoordinationError("preparation original must remain external to every linked worktree")
        for field, value in (("worktree", str(path)), ("repository_id", store.repository_id),
                             ("branch", claim["branch"]), ("base_revision", claim["base_revision"])):
            if receipt[field] != value:
                raise CoordinationError(f"environment preparation {field} mismatch")
        if any(a["run"] == claim["run"] and a["state"] != "released" for a in store._all(db, "assignment")):
            raise CoordinationError("all assignments must settle and release before environment rebind")
        if any(f["path"] == str(path) and f["active"] for f in store._all(db, "freeze")):
            raise CoordinationError("frozen review prevents environment rebind")
        if any(p["active"] and p["kind"] in ("import", "live", "environment", "resume")
               and _related_paths(p["path"], path) for p in store._all(db, "pin")):
            raise CoordinationError("active import/live/environment/resume pin prevents environment rebind")
        actual = _inspect_workspace(store, record, check_lock=False)
        if actual != expected_source or receipt["expected_source"] != actual:
            raise CoordinationError("environment preparation source is stale or mismatched")
        locks = lock_inventory(path, record["environment_policy"])
        if receipt["lockfiles"] != locks:
            raise CoordinationError("environment preparation dependency lock fingerprints mismatch")
        environment = canonical_location(receipt["environment"], path)
        if not environment.is_dir():
            raise CoordinationError("prepared environment directory missing")
        identity = dict(qualified=qualified, generation=generation, session=session, authority=authority,
                        expected_source=expected_source, preparation=preparation)
        old = store._get(db, "environment-rebind", receipt["receipt_id"])
        if old:
            if old["request"] != identity or record["environment"] != str(environment) or record["lockfiles"] != locks:
                raise CoordinationError("environment receipt identity conflicts or binding is stale")
            return {**old, "replayed": True}
        result = dict(receipt_id=receipt["receipt_id"], request=identity,
                      prior={"environment": record["environment"], "lockfiles": record["lockfiles"]},
                      current={"environment": str(environment), "lockfiles": locks}, preparation=preparation)
        record.update(environment=str(environment), lockfiles=locks, expected_source=actual)
        record.setdefault("environment_history", []).append(result)
        store._put(db, "workspace", str(path), record)
        store._put(db, "environment-rebind", receipt["receipt_id"], result)
        return {**result, "replayed": False}


def _unique_receipt(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise CoordinationError(f"duplicate preparation receipt key: {key}")
        result[key] = value
    return result


def _related_paths(left, right):
    left, right = Path(left), Path(right)
    return left.is_relative_to(right) or right.is_relative_to(left)


def _linked_worktrees(store):
    return tuple(Path(entry[9:]).resolve() for entry in
                 git(store.repository_id, "worktree", "list", "--porcelain", "-z").split("\0")
                 if entry.startswith("worktree "))


def _evidence_dependencies(store, db, recoverability):
    """Index known evidence in both directions before any worktree is removed.

    A source worktree cannot authorize deleting another worktree that happens
    to hold its retained originals. Settled assignments remain evidence owners.
    Supplied and previously retained bundle references also protect their host.
    """
    dependencies = set()

    def add(value, owner):
        if isinstance(value, str) and value and Path(value).is_absolute():
            dependencies.add((str(Path(value).resolve()), owner))

    def retention(reference, owner):
        if not isinstance(reference, dict):
            return
        add(reference.get("bundle"), owner + " retained bundle")
        originals = reference.get("originals", [])
        if isinstance(originals, list):
            for original in originals:
                if isinstance(original, dict):
                    add(original.get("path"), owner + " retained original")

    for assignment in store._all(db, "assignment"):
        owner = "assignment " + assignment["id"]
        add(assignment.get("output"), owner + " output")
        add(assignment.get("result_reference"), owner + " original")
    for path, reference in recoverability.items():
        retention(reference, "workspace " + path)
    for workspace in store._all(db, "workspace"):
        retention(workspace.get("recoverability"), "workspace " + workspace["path"])
    for cleanup in store._all(db, "cleanup"):
        retention(cleanup.get("recoverability"), "prior cleanup " + cleanup["path"])
    return sorted(dependencies)


def _retained(store, db, path, record, reference, linked_worktrees):
    """Verify recoverable source and original-result files before removal."""
    if not isinstance(reference, dict) or set(reference) != {'bundle', 'originals'} or not isinstance(reference['originals'], list):
        return 'retained source/evidence recoverability reference required'
    try:
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import evidence
        bundle = Path(reference['bundle'])
        if not bundle.is_absolute() or any(bundle.resolve().is_relative_to(root) for root in linked_worktrees):
            return 'retention bundle must remain outside every linked worktree'
        manifest = evidence.verify(bundle, Path(path), current_head_required=False)
        if manifest.get('schema_version') not in (3, 4):
            return 'cleanup requires retained source schema 3 or 4 with executable modes'
        claim = store._get(db, 'claim', record['claim'])
        if (manifest['repository'], manifest['project'], manifest['change'], manifest['run_id']) != (store.repository_id, claim['project'], claim['change'], claim['run']):
            return 'retention bundle identity differs from owned work'
        retained = set()
        for ref in reference['originals']:
            if not isinstance(ref, dict) or set(ref) != {'path', 'sha256'}:
                return 'retained original needs path and hash'
            original = Path(ref['path'])
            if (not original.is_absolute() or original.is_symlink()
                    or any(original.resolve().is_relative_to(root) for root in linked_worktrees)):
                return 'original evidence must remain outside every linked worktree'
            if hashlib.sha256(original.read_bytes()).hexdigest() != ref['sha256']:
                return 'retained original hash mismatch'
            retained.add(str(original.resolve()))
        required = {str(Path(a['result_reference']).resolve()) for a in store._all(db, 'assignment')
                    if a['claim'] == record['claim'] and a.get('result_reference')}
        if not required <= retained:
            return 'original assignment results are not all retained'
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return f'recoverability cannot be verified: {exc}'
    return None


def _inventory(store, db, paths, recoverability):
    result = []
    linked_worktrees = _linked_worktrees(store)
    dependencies = _evidence_dependencies(store, db, recoverability)
    for path in paths:
        path = str(Path(path).absolute())
        record = store._get(db, "workspace", path)
        reasons = []
        state = None
        if not record or record["state"] != "owned":
            reasons.append("unowned or removed workspace")
        else:
            try:
                state = _inspect_workspace(store, record)
                if state["dirty"]:
                    reasons.append("dirty staged/unstaged/untracked content")
            except (CoordinationError, OSError) as exc:
                reasons.append(f"identity uncertain: {exc}")
            claim = store._get(db, "claim", record["claim"])
            if not claim or claim["state"] not in ("released", "completed"):
                reasons.append("unreconciled/live claim")
            if any(a["claim"] == record["claim"] and a["state"] != "released" for a in store._all(db, "assignment")):
                reasons.append("active/reserved assignment")
            if any(f["path"] == path and f["active"] for f in store._all(db, "freeze")):
                reasons.append("frozen review dependency")
        pins = [p for p in store._all(db, "pin") if p["active"] and _related_paths(p["path"], path)]
        reasons.extend(f"{p['kind']} pin: {p['reference']}" for p in pins)
        reasons.extend(f"retained evidence dependency: {owner}: {dependency}"
                       for dependency, owner in dependencies
                       if _related_paths(Path(path).resolve(), dependency))
        retention_problem = _retained(store, db, path, record, recoverability.get(path), linked_worktrees) if record else 'retained source/evidence recoverability reference required'
        if retention_problem:
            reasons.append(retention_problem)
        result.append(dict(path=path, workspace=record, source=state, pins=pins, reasons=reasons,
                           eligible=not reasons, recoverability=recoverability.get(path),
                           retained_branch=record["branch"] if record else None))
    return result


def cleanup_inventory(store, paths, recoverability):
    """Exact dry-run inventory; the external hook pins imports/evidence before use.

    Caller must register all external process/data/environment dependencies. Git
    cannot discover arbitrary imports; absent liveness registration is never
    evidence that a known owner has stopped.
    """
    if not isinstance(paths, list) or not paths or len(set(paths)) != len(paths):
        raise CoordinationError("cleanup requires distinct exact paths")
    # Read-only dry-run: no DB/event is created or modified.
    if not store.path.exists():
        return {"items": [{"path": p, "eligible": False, "reasons": ["unowned workspace"]} for p in paths]}
    db = sqlite3.connect(f"file:{store.path}?mode=ro", uri=True, timeout=30)
    try:
        db.execute("BEGIN")
        return {"items": _inventory(store, db, paths, recoverability), "coordination_domain": store.repository_id}
    finally:
        db.close()


def apply_cleanup(store, inventory, authorization):
    """Apply only an authorized exact inventory after a protection recheck.

    Uses normal `git worktree remove`; branches and source bundles are retained.
    External callers must settle workers and register pins through this store.
    """
    require(authorization, "exact inventory cleanup authorization")
    if not isinstance(inventory, dict) or inventory.get("coordination_domain") != store.repository_id:
        raise CoordinationError("cleanup inventory belongs to another coordination domain")
    items = inventory.get("items")
    if not isinstance(items, list) or not items:
        raise CoordinationError("exact inventory required")
    results = []
    with store.transaction() as db:
        recoverability = {i["path"]: i.get("recoverability") for i in items}
        current = _inventory(store, db, [i["path"] for i in items], recoverability)
        for original, item in zip(items, current):
            # Earlier removals and filesystem changes must not invalidate the
            # source or evidence protections checked for a later item.
            refreshed = _inventory(store, db, [item["path"]], recoverability)[0]
            if refreshed != item:
                item = refreshed
            if not original["eligible"] or not item["eligible"] or original != item:
                result = {"path": item["path"], "removed": False,
                          "reasons": item["reasons"] or ["inventory/protections changed"]}
            else:
                try:
                    # The caller's checkout may be an earlier item in this
                    # batch. The shared Git directory survives its removal.
                    git(store.repository_id, "worktree", "remove", item["path"])
                    workspace = item["workspace"]
                    workspace.update(state="removed", cleanup_authorization=authorization,
                                     recoverability=item["recoverability"])
                    store._put(db, "workspace", item["path"], workspace)
                    result = {"path": item["path"], "removed": True,
                              "retained_branch": item["retained_branch"], "recoverability": item["recoverability"]}
                except CoordinationError as exc:
                    result = {"path": item["path"], "removed": False, "reasons": [str(exc)]}
            store._put(db, "cleanup", uuid.uuid4().hex, result)
            results.append(result)
    return results


ACTIONS = ("list", "next", "claim", "transition", "create-workspace", "adopt-workspace",
           "resume-workspace", "recover-claim", "rebind-environment", "reserve", "settle", "release-assignments",
           "freeze", "thaw", "pin", "unpin", "cleanup-inventory", "apply-cleanup")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=ACTIONS)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--request", required=True, help="JSON keyword arguments; '-' reads stdin")
    args = parser.parse_args(argv)
    try:
        import sys
        request = json.loads(sys.stdin.read() if args.request == "-" else Path(args.request).read_text())
        if not isinstance(request, dict):
            raise CoordinationError("request must be an object")
        store = CoordinationStore(args.repository)
        if "project" in request:
            registration = request["project"]
            repository_root = Path(git(store.repository, "rev-parse", "--show-toplevel"))
            if registration is None or isinstance(registration, str):
                import projects
                registration = projects.resolve(registration, repository_root)
            if isinstance(registration, dict) and "id" in registration:
                request["project"] = Project(
                    registration["id"], repository_root / registration["root"],
                    repository_root / registration["queue"], registration.get("environment"))
            else:
                request["project"] = Project(**registration)
            if str(common_dir(request["project"].root)) != store.repository_id:
                raise CoordinationError("project resolved outside repository")
        if args.action == "list":
            result = validate_queue(**request)
        elif args.action == "next":
            result = select_next(**request, store=store)
        elif args.action.replace("-", "_") in {
            "create_workspace", "adopt_workspace", "resume_workspace", "recover_claim", "rebind_environment",
            "cleanup_inventory", "apply_cleanup"
        }:
            result = globals()[args.action.replace("-", "_")](store, **request)
        else:
            result = getattr(store, args.action.replace("-", "_"))(**request)
        print(json.dumps({"ok": True, "result": result}, sort_keys=True))
        return 0
    except (ValueError, KeyError, OSError, TypeError, yaml.YAMLError, sqlite3.Error, subprocess.SubprocessError) as exc:
        print(json.dumps({"ok": False, "blocker": str(exc)}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
