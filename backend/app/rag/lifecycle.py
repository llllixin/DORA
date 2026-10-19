"""Pure lifecycle selection; cached active flags are not authoritative."""
from datetime import date


def select_versions(documents, *, on_date, barriers):
    latest = {}; reasons = {}; blocked = []
    for doc in documents:
        if doc['status'] == 'draft' or date.fromisoformat(doc['valid_from']) > on_date: continue
        if doc['id'] not in latest or doc['version'] > latest[doc['id']]['version']:
            latest[doc['id']] = doc
    eligible = []
    for identity, doc in sorted(latest.items()):
        reason = None
        if doc['version'] <= barriers.get(identity, 0): reason = 'removed'
        elif doc['status'] != 'reviewed': reason = 'retired'
        elif doc.get('valid_to') and date.fromisoformat(doc['valid_to']) < on_date: reason = 'expired'
        if reason: blocked.append(doc); reasons[identity] = reason
        else: eligible.append(doc)
    return {'eligible': eligible, 'blocked': blocked, 'reasons': reasons}


def merge_removal_barriers(previous_manifest, source_documents, *, mode):
    barriers = dict(previous_manifest.get('barriers', {}))
    if mode == 'full':
        present = {(d['id'], d['version']) for d in source_documents}
        for doc in previous_manifest.get('versions', {}).values():
            if doc['status'] != 'draft' and (doc['id'], doc['version']) not in present:
                barriers[doc['id']] = max(barriers.get(doc['id'], 0), doc['version'])
    return barriers
