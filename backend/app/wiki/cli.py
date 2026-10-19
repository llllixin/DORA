"""Trusted local governance CLI; actor is an audit label, not authentication."""
import argparse
import json
from pathlib import Path
from app.rag.contracts import KNOWLEDGE_ROOT, RagContractError, validate_document
from app.wiki.contracts import approve, retire, require
from app.wiki.publication import publish_batch, render
from app.wiki.candidates import CandidateService
from app.repository import DataSourceUnavailableError


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['validate','approve','publish','retire','render','candidate-list','candidate-get','candidate-collect','candidate-review','candidate-export','candidate-publish','candidate-revise'])
    parser.add_argument('--input',type=Path);parser.add_argument('--output',type=Path)
    parser.add_argument('--source',type=Path,default=KNOWLEDGE_ROOT/'documents.json')
    parser.add_argument('--wiki-dir',type=Path);parser.add_argument('--actor');parser.add_argument('--reason')
    parser.add_argument('--base-version',type=int);parser.add_argument('--candidate-id')
    parser.add_argument('--decision',choices=['approve','reject','retire'],default='approve')
    args=parser.parse_args(argv)
    try:
        action=args.action
        if action.startswith('candidate-'):
            service=CandidateService()
            if action=='candidate-list':out={'candidates':service.list()}
            elif action=='candidate-collect':out=service.collect()
            else:
                require(bool(args.candidate_id),'candidate-id required')
                if action=='candidate-get':out=service.get(args.candidate_id);require(out is not None,'candidate not found')
                elif action=='candidate-review':out=service.review(args.candidate_id,actor=args.actor,reason=args.reason,decision=args.decision,base_version=args.base_version)
                elif action=='candidate-export':out=service.export(args.candidate_id)
                elif action=='candidate-publish':out=service.publish(args.candidate_id,args.source,render_dir=args.wiki_dir)
                else:
                    require(args.input is not None,'input required');out=service.revise(args.candidate_id,json.loads(args.input.read_text()))
        elif action=='render':
            require(args.wiki_dir is not None,'wiki-dir required');out=render(args.source,args.wiki_dir)
        else:
            require(args.input is not None,'input required');rows=json.loads(args.input.read_text())
            if isinstance(rows,dict):rows=[rows]
            require(isinstance(rows,list) and bool(rows),'input must contain documents')
            if action=='validate':out={'ok':True,'documents':len([validate_document(d) for d in rows])}
            elif action=='approve':out=[approve(d,actor=args.actor,reason=args.reason,base_version=args.base_version if args.base_version is not None else d['version']-1) for d in rows]
            elif action=='retire':out=[retire(d,actor=args.actor,reason=args.reason,base_version=args.base_version if args.base_version is not None else d['version']) for d in rows]
            else:out=publish_batch(rows,args.source,render_dir=args.wiki_dir)
        if args.output:
            args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
        else:print(json.dumps(out,ensure_ascii=False,indent=2))
        return 0
    except (RagContractError,ValueError,OSError,DataSourceUnavailableError) as exc:
        print(json.dumps({'ok':False,'error':str(exc)},ensure_ascii=False));return 2

if __name__=='__main__':raise SystemExit(main())
