"""Repository-local harness entrypoint; no implicit next-task execution."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import projects


def _selection(arguments, *, forward=False):
    """Consume only harness selectors, leaving upstream arguments untouched."""
    remaining = list(arguments)
    project = None
    at = None
    if remaining and not remaining[0].startswith('-'):
        project = remaining.pop(0)
    if remaining and (remaining[0] == '--at' or remaining[0].startswith('--at=')):
        option = remaining.pop(0)
        if option == '--at':
            if not remaining or remaining[0].startswith('-'):
                raise ValueError('--at requires a repository-relative directory')
            at = remaining.pop(0)
        else:
            at = option.removeprefix('--at=')
        if not at:
            raise ValueError('--at requires a repository-relative directory')
        if project is not None:
            raise ValueError('select --at or a legacy project ID, not both')
        if remaining and (remaining[0] == '--at' or remaining[0].startswith('--at=')):
            raise ValueError('select one OpenSpec directory with --at')
    if remaining[:1] == ['--']:
        remaining = remaining[1:]
    if not forward and remaining:
        raise ValueError('project accepts --at DIRECTORY or one legacy project ID')
    return project, ({'at': at} if at is not None else {}), remaining


def main(argv=None):
    raw_arguments = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['project', 'openspec', 'plans', 'coordination', 'source', 'remote', 'dispatch', 'intake'])
    parser.add_argument('arguments', nargs=argparse.REMAINDER)
    args = parser.parse_args(raw_arguments)
    try:
        if args.command == 'intake':
            import intake
            print(json.dumps(intake.validate_intake(json.loads(Path(args.arguments[0]).read_text()), projects.ROOT), indent=2))
        elif args.command == 'project':
            project, selection, _ = _selection(args.arguments)
            print(json.dumps(projects.resolve(project, **selection), indent=2))
        elif args.command == 'openspec':
            # argparse removes the separator before REMAINDER. Keep the original
            # spelling so a sole project's `-- list` is not parsed as project=list.
            forwarded = raw_arguments[raw_arguments.index('openspec') + 1:]
            project, selection, command = _selection(forwarded, forward=True)
            return projects.openspec(project, command, **selection)
        elif args.command == 'plans':
            import plan_runtime
            return plan_runtime.main(args.arguments)
        elif args.command == 'coordination':
            import coordination
            return coordination.main(args.arguments)
        elif args.command == 'dispatch':
            import dispatch
            return dispatch.main(args.arguments)
        elif args.command == 'source':
            import evidence
            operation, filename = args.arguments
            request = json.loads(Path(filename).read_text())
            for key in ('worktree', 'destination', 'bundle'):
                if key in request:
                    request[key] = Path(request[key])
            result = evidence.materialize(**request) if operation == 'capture' else evidence.verify(**request) if operation == 'verify' else None
            if result is None:
                raise ValueError('source operation must be capture or verify')
            print(json.dumps(result, indent=2))
        else:
            import lifecycle
            operation, filename = args.arguments
            request = json.loads(Path(filename).read_text())
            journal = lifecycle.Journal(Path(request.pop('journal')))
            if operation == 'prepare':
                result = journal.prepare(**request)
            elif operation == 'grant':
                result = journal.grant(**request)
            elif operation in {'execute', 'reconcile'}:
                remote = lifecycle.GhRemote(Path(request.pop('worktree')))
                result = getattr(journal, operation)(remote=remote, **request)
            else:
                raise ValueError('remote operation must be prepare, grant, execute or reconcile')
            print(json.dumps(result, indent=2))
        return 0
    except (ValueError, KeyError, TypeError, OSError) as exc:
        print(json.dumps({'status': 'blocked', 'reason': str(exc)}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
