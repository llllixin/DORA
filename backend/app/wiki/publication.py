"""Append reviewed source versions under a local file lock; render is rebuildable."""
from copy import deepcopy
import fcntl
import json
import os
from pathlib import Path
import tempfile
from app.rag.contracts import KNOWLEDGE_ROOT, load_documents, validate_document
from app.wiki.contracts import require, payload_hash
from app.wiki.reader import effective_documents


def render(path, outdir):
    documents=load_documents(Path(path));outdir=Path(outdir);outdir.mkdir(parents=True,exist_ok=True)
    latest={d['id']:d for d in effective_documents(documents)}
    index=['# DORA Wiki','', '由正式JSON生成；来源/审核不代表身份认证或企业成效验证。','']
    for doc in documents:
        if doc.get('schema_version')!=2 or doc['status']=='draft':continue
        category=doc['wiki_card']['card_type'];folder=outdir/category;folder.mkdir(exist_ok=True)
        text=[f"# {doc['title']}", '', f"版本：{doc['version']} · 状态：{doc['status']} · 来源：{doc['source_type']}", '', f"审核：{doc['reviewed_by']} · {doc['governance']['review']['reason']}", '', f"适用范围：{doc['governance']['applicability']}", '', f"证据等级：{doc['governance']['evidence_level']}", '', '未知项：'+'；'.join(doc['governance']['unknowns']), '', '来源：'+ '；'.join(doc['governance']['source_refs']), '', doc['content']]
        body='\n'.join(text)+'\n';(folder/f"{doc['id']}@{doc['version']}.md").write_text(body)
        if latest.get(doc['id'],{}).get('version')==doc['version']:
            (folder/f"{doc['id']}.md").write_text(body);index.append(f"- [{doc['title']}](./{category}/{doc['id']}.md) · v{doc['version']}")
    # Remove stale convenience pages; retain explicit historical @version pages.
    for page in outdir.glob('*/*.md'):
        if '@' not in page.stem and page.stem not in latest:page.unlink()
    (outdir/'index.md').write_text('\n'.join(index)+'\n')
    return {'cards':len(latest),'path':str(outdir)}


def publish_batch(documents, path=None, *, render_dir=None, candidate_guard=None):
    source=Path(path or KNOWLEDGE_ROOT/'documents.json');source.parent.mkdir(parents=True,exist_ok=True)
    batch=[validate_document(d) for d in documents]
    require(len({d['id'] for d in batch})==len(batch),'one version per topic in publication batch')
    require(all(d.get('schema_version')==2 and d['status'] in {'reviewed','retired'} for d in batch),'publication requires reviewed governance records')
    for doc in batch:
        if doc['status']=='reviewed' and doc['governance'].get('origin'):
            require(candidate_guard is not None and candidate_guard(doc),'candidate publication must recheck live source through CandidateService')
    added=0
    with source.with_suffix(source.suffix+'.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        previous=load_documents(source) if source.exists() else []
        rows=deepcopy(previous)
        for doc in batch:
            same=next((r for r in rows if r['id']==doc['id'] and r.get('schema_version')==2 and r['status']==doc['status'] and payload_hash(r)==payload_hash(doc) and r['governance']['review']['base_version']==doc['governance']['review']['base_version']),None)
            if same is not None:continue
            base=max((r['version'] for r in rows if r['id']==doc['id']),default=0)
            require(doc['governance']['review']['base_version']==base,'publication base version conflict')
            # Approved source snapshots are checked again at publication, not on historical reads.
            from app.wiki.contracts import source_file
            import hashlib
            for ref,expected in doc['governance'].get('source_hashes',{}).items():
                require(hashlib.sha256(source_file(ref).read_bytes()).hexdigest()==expected,'approved source changed')
            out=deepcopy(doc);out['version']=base+1;rows.append(out);added+=1
        if added:
            temp=None
            try:
                with tempfile.NamedTemporaryFile(mode='w',dir=source.parent,delete=False,encoding='utf-8') as file:
                    temp=Path(file.name);json.dump(rows,file,ensure_ascii=False,indent=2);file.write('\n');file.flush();os.fsync(file.fileno())
                os.replace(temp,source)
            finally:
                if temp and temp.exists():temp.unlink()
    result={'published':True,'added':added,'unchanged':len(batch)-added,'indexed':False,'rendered':False,'source':str(source)}
    if render_dir:
        try:result['projection']=render(source,render_dir);result['rendered']=True
        except (OSError,ValueError) as exc:result['renderError']=str(exc)
    return result
