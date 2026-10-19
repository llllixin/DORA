"""Local administrative projection commands, no arbitrary graph writes."""
import argparse
import json
from app.graph.service import GraphService
from app.graph.contracts import GraphError


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['sync','rebuild','reconcile'])
    args=parser.parse_args(argv)
    service=GraphService()
    try:
        result=service.reconcile() if args.command=='reconcile' else service.sync(rebuild=args.command=='rebuild')
    except GraphError as exc:
        print(json.dumps({'ok':False,'reasonCode':exc.code}));return 1
    print(json.dumps(result,ensure_ascii=False));return int(result.get('ok') is False)


if __name__=='__main__':raise SystemExit(main())
