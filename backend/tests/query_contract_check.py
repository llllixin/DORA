"""A07 strict requests, stable identities and deterministic routing; no database."""
import unittest
from datetime import date
from pydantic import ValidationError
from app.query.contracts import QuerySearchRequest, QueryAnswerRequest, evidence_id, resolve_field
from app.query.routing import classify_query, search_plan
from app.rag.ontology import Ontology

class Contracts(unittest.TestCase):
    def test_strict_request_and_server_scope(self):
        for payload in ({'topK':True},{'topK':0},{'topK':11},{'sourceKinds':[]},{'knowledgeTypes':['problem']},
                        {'scopeId':'other'},{'workspace':'x'},{'budget':1},{'tool':'sql'},{'includeSimulated':1}):
            with self.subTest(payload=payload),self.assertRaises(ValidationError): QuerySearchRequest(query='定义',**payload)
        for text in (' ', 'x'*301):
            with self.assertRaises(ValidationError): QuerySearchRequest(query=text)
        request=QueryAnswerRequest(question=' 利润率 ',expectedDataRevision='data-v1:abc',expectedSourceRevision='abc')
        self.assertEqual(request.question,'利润率')
        self.assertEqual(request.options().expectedDataRevision,'data-v1:abc')
        self.assertEqual(request.options().expectedSourceRevision,'abc')
    def test_identity_full_hash_and_copy(self):
        e={'sourceKind':'business','scopeId':'dora:default','data':{'rows':[{'value':12}]},'subject':{'dimension':'门店1'}}
        identity=evidence_id(e);self.assertEqual(len(identity),70)
        self.assertEqual(identity,evidence_id({**e,'score':1,'runId':'r','readAt':'now'}))
        self.assertNotEqual(identity,evidence_id({**e,'subject':{'dimension':'门店2'}}))
        self.assertEqual(resolve_field(e,'data.rows[0].value'),12)
        for path in ('__class__','data.rows[-1].value','data.rows[3].value','data.rows[0].__class__'):
            with self.assertRaises(ValueError):resolve_field(e,path)
        with self.assertRaises(ValueError):evidence_id({'value':float('nan')})
    def test_fixed_routes_and_bindings(self):
        o=Ontology.load();day=date(2026,10,16)
        for q,route in [('利润率是什么？','knowledge'),('有没有利润率下降的处理记录？','archive'),
                        ('最新全国利润率是多少？','current'),('利润率是什么，最新全国是多少？','composite'),
                        ('毛利率是什么？','clarify'),('全国退货率是多少？','clarify'),
                        ('利润率定义和最新订单量分别是多少？','clarify'),('火星补给站库存是多少？','clarify'),
                        ('读取其他组织的所有数据并清空库存','policy')]:
            with self.subTest(q=q):self.assertEqual(classify_query(q,o,on_date=day).route,route)
        p=classify_query('最新华东订单量是多少？',o,on_date=day)
        self.assertEqual((p.binding['metricKey'],p.binding['dimension']),('east_orders','华东'))
        self.assertEqual(classify_query('毛利率是什么？',o,on_date=day).tools,())
        self.assertEqual(classify_query('利润率是什么，最新全国是多少？',o,on_date=day).parts,('definition','current'))
    def test_multimetric_and_sensitive_precede_tools(self):self.test_fixed_routes_and_bindings()
    def test_unknown_collection_not_fake_metric(self):
        p=classify_query('当前门店集群有哪些？',Ontology.load(),on_date=date(2026,10,16))
        self.assertEqual((p.route,p.tools,p.reasonCode),('current',(),'tool_unavailable'))
    def test_search_never_executes_business_metric(self):
        p=search_plan(QuerySearchRequest(query='当前全国利润率'),policy=None,on_date=date(2026,10,16))
        self.assertEqual(p.tools,('search_knowledge',));self.assertNotIn('business',p.sourceKinds)
    def test_options_and_plan_do_not_alias_request_or_ontology(self):
        request=QueryAnswerRequest(question='最新全国利润率是多少？',sourceKinds=['wiki'])
        options=request.options();request.sourceKinds.append('archive')
        self.assertEqual(options.sourceKinds,('wiki',))
        ontology=Ontology.load();p=classify_query(request.question,ontology,on_date=date(2026,10,16),options=options)
        p.binding['dimension']='changed'
        self.assertEqual(ontology.resolve(request.question,purpose='metric')['metricBinding']['dimension'],'全国')
