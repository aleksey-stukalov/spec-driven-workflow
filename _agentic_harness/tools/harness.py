"""Repository-local harness entrypoint; no implicit next-task execution."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import projects


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
            if len(args.arguments) > 1:
                raise ValueError('project accepts at most one registered project ID')
            print(json.dumps(projects.resolve(args.arguments[0] if args.arguments else None), indent=2))
        elif args.command == 'openspec':
            # argparse removes the separator before REMAINDER. Keep the original
            # spelling so a sole project's `-- list` is not parsed as project=list.
            forwarded = raw_arguments[raw_arguments.index('openspec') + 1:]
            project = forwarded[0] if forwarded and not forwarded[0].startswith('-') else None
            command = forwarded[1:] if project is not None else forwarded
            if command[:1] == ['--']:
                command = command[1:]
            return projects.openspec(project, command)
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
