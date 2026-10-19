"""Pure deterministic projection of verified records, with one witness per assertion."""
from collections import defaultdict
from copy import deepcopy
from app.business_version import SCOPE_ID, canonical_hash
from app.graph.contracts import GraphError, seal, resolve_pointer, graph_revision
from app.graph.registry import check_relation, SCHEMA_HASH


def project(view, limits, budget):
    nodes, edges, witnesses = {}, {}, {}
    missing = deepcopy(view['missing'])
    records = view['records']

    def node(kind, attributes, source_key):
        source = records[source_key]
        value = seal('entity', dict(scopeId=SCOPE_ID, type=kind, attributes=deepcopy(attributes),
                                    sourceKey=source_key, sourceHash=source['hash'],sourceLevel=source['level']))
        nodes[value['id']] = value
        if len(nodes) > limits.maxBuildNodes: raise GraphError('build_input_limit',422)
        return value['id']

    def relation(kind, start, end, source_key, pointer, *, qualifier=None):
        budget.check()
        check_relation(kind, nodes[start]['type'], nodes[end]['type'])
        source = records[source_key]
        edge = seal('relation', dict(scopeId=SCOPE_ID, type=kind, **{'from':start,'to':end},
                                     qualifier=deepcopy(qualifier or {}), causality='not_asserted'))
        witness = seal('evidence', dict(scopeId=SCOPE_ID, relationId=edge['id'], sourceKey=source_key,
            sourceKind=source['kind'], sourceId=source['sourceId'], sourceVersion=source['version'],
            sourceHash=source['hash'], pointer=pointer, data=resolve_pointer(source['data'],pointer),
            assertion={'from':start,'type':kind,'to':end}, sourceLevel=source['level'],
            factVersion=deepcopy(source['data'].get('factVersion') or source['data'].get('capture_context',{}).get('factVersion'))))
        edges[edge['id']] = edge; witnesses[witness['id']] = witness
        if len(edges)>limits.maxBuildRelations or len(witnesses)>limits.maxBuildWitnesses:
            raise GraphError('build_input_limit',422)

    snap_nodes, occurrence_nodes, metric_nodes = {}, {}, {}
    for snapshot in sorted(view['snapshots'], key=lambda s:s['snapshotId']):
        budget.check()
        sid = snapshot['snapshotId']; key = 'snapshot:'+sid
        version = snapshot['factVersion']['ontologyVersion']; ontology_key = 'ontology:'+version
        ontology = view['ontology'][version]; p = snapshot['payload']
        snap_nodes[sid] = node('Snapshot', dict(snapshotId=sid, factVersion=snapshot['factVersion'],
                                              payloadHash=snapshot['payloadHash'], historical=True), key)
        bindings = {c['metricBinding']['metricKey']:c for c in ontology['concepts'] if c.get('metricBinding')}
        for metric_key, concept in bindings.items():
            metric_nodes[(version,metric_key)] = node('Metric', dict(conceptId=concept['id'],
                ontologyVersion=version, metricKey=metric_key, name=concept['name']), ontology_key)
        for index,row in enumerate(p['rawSeries']):
            metric = metric_nodes.get((version,row['metric_key']))
            if metric is None:
                missing.append(dict(sourceId=sid,reason='metric_not_registered',metricKey=row['metric_key']));continue
            observation = node('MetricObservation', dict(snapshotId=sid, rowIndex=index,
                               rowHash=canonical_hash(row), row=row, historical=True), key)
            pointer = f'/payload/rawSeries/{index}'
            relation('observed_as',metric,observation,key,pointer)
            relation('captured_in',observation,snap_nodes[sid],key,pointer)
        for index,insight in enumerate(p['factInsights']):
            occurrence = node('InsightOccurrence', dict(occurrenceId=insight['occurrenceId'],
                              insightTypeId=insight['id'], judgment=insight, historical=True),key)
            occurrence_nodes[(sid,insight['occurrenceId'])] = occurrence
            pointer = f'/payload/factInsights/{index}'
            relation('supported_by',occurrence,snap_nodes[sid],key,pointer)
            # Only the margin/p1 rule mapping has been reviewed in A01.
            if insight['id']=='p1':
                rule = next((c for c in ontology['concepts'] if c['id']=='rule.margin-low'),None)
                if rule:
                    rule_key='rule:'+canonical_hash([version,snapshot['factVersion']['ruleVersion']])
                    rule_node = node('Rule',dict(conceptId=rule['id'],ruleVersion=snapshot['factVersion']['ruleVersion'],
                        ontologyVersion=version,effectiveRules=p['effectiveRules']),rule_key)
                    relation('produced_occurrence',rule_node,occurrence,key,pointer)
                    relation('applies_to',rule_node,metric_nodes[(version,'margin')],key,'/payload/effectiveRules')
            else:
                missing.append(dict(sourceId=insight['occurrenceId'],reason='rule_mapping_not_reviewed'))

    cases = {}
    grouped = defaultdict(list)
    for b in view['bindings']:
        if b['source_kind']=='action_case': grouped[b['source_instance_id']].append(b)
    for instance, bindings in sorted(grouped.items()):
        first = min(bindings,key=lambda b:(b['owner_kind']!='action_open',b['recorded_at'],b['binding_id']))
        cases[instance] = node('ActionCase',dict(caseInstanceId=instance,caseId=first['owner_public_id'],historical=True),
                               'binding:'+first['binding_id'])
    for binding in view['bindings']:
        budget.check()
        key='binding:'+binding['binding_id']; sid=binding['snapshot_id']; kind=binding['owner_kind']
        if sid not in snap_nodes:
            missing.append(dict(sourceId=binding['binding_id'],reason='snapshot_not_captured'));continue
        qualifier=dict(bindingId=binding['binding_id'])
        occurrence=occurrence_nodes.get((sid,binding['occurrence_id']))
        if kind in {'action_open','action_verification'}:
            case=cases[binding['source_instance_id']]
            relation('opened_with' if kind=='action_open' else 'verified_with',case,snap_nodes[sid],key,'',qualifier=qualifier)
            if kind=='action_open' and occurrence:
                relation('opened_from',case,occurrence,key,'',qualifier=qualifier)
        elif kind=='watch_event':
            event=node('WatchEvent',dict(eventInstanceId=binding['owner_instance_id'],bindingId=binding['binding_id'],
                                        event=binding['source_record'],historical=True),key)
            relation('event_evidenced_by',event,snap_nodes[sid],key,'',qualifier=qualifier)
            if occurrence:relation('event_matched',event,occurrence,key,'',qualifier=qualifier)
            target=binding['source_record'].get('target') or {}; intent=target.get('intent') or {}
            metric_key=intent.get('metric_key'); version=records['snapshot:'+sid]['data']['factVersion']['ontologyVersion']
            if intent and (version,metric_key) in metric_nodes:
                target_node=node('WatchTarget',dict(bindingId=binding['binding_id'],
                    targetInstanceId=binding['source_instance_id'],intentHash=binding['capture_context'].get('intentHash'),
                    capturedTarget=target,historical=True),key)
                relation('emitted',target_node,event,key,'/source_record/target',qualifier=qualifier)
                relation('monitors',target_node,metric_nodes[(version,metric_key)],key,'/source_record/target/intent',qualifier=qualifier)
            else:missing.append(dict(sourceId=binding['binding_id'],reason='watch_intent_not_captured'))

    for doc in view['documents']:
        if doc['status']!='reviewed' or doc.get('schema_version')!=2:continue
        origin=doc.get('governance',{}).get('origin') or {}
        refs=origin.get('snapshot',{}).get('history_refs') or {}
        instance=refs.get('caseInstanceId'); key=f"document:{doc['id']}@{doc['version']}"
        if not instance or instance not in cases:
            if origin:missing.append(dict(sourceId=doc['id'],reason='lesson_history_not_captured'))
            continue
        ids={b['binding_id'] for b in grouped[instance]}
        requested=[refs.get('openingBindingId'),*refs.get('verificationBindingIds',[])]
        if not all(b in ids for b in requested if b): raise GraphError('source_integrity_error')
        # Only an actual archived lesson, rather than a generic case card, is a Lesson.
        if origin.get('snapshot',{}).get('entry_type')!='lesson':continue
        lesson=node('Lesson',dict(documentId=doc['id'],documentVersion=doc['version'],
                    sourceVersionHash=records[key]['version'],caseInstanceId=instance,historical=True),key)
        relation('lesson_from',lesson,cases[instance],key,'/governance/origin/snapshot/history_refs')

    result=dict(nodes=sorted(nodes.values(),key=lambda r:r['id']),relations=sorted(edges.values(),key=lambda r:r['id']),
                evidence=sorted(witnesses.values(),key=lambda r:r['id']),
                missingEvidence=sorted(missing,key=canonical_hash),sourceVector=deepcopy(view['vector']))
    result['graphRevision']=graph_revision(result)
    budget.check()
    return result
