import unittest
from tests.evidence_gate import validate_environment,safe_environment

class GateGuards(unittest.TestCase):
    def test_only_explicit_disposable_environment(self):
        for env in ({},{'DATABASE_URL':'postgresql+psycopg://dora:dora@localhost:5432/dora'},
                    {'DATABASE_URL':'postgresql+psycopg://dora_a05:dora_a05@127.0.0.1:55457/dora_a05','DORA_API_BASE':'http://127.0.0.1:8000/api'}):
            with self.assertRaises(ValueError):validate_environment(env)
        good={'DATABASE_URL':'postgresql+psycopg://dora_a05:dora_a05@127.0.0.1:55457/dora_a05','DORA_API_BASE':'http://127.0.0.1:8057/api'}
        self.assertEqual(validate_environment(good)[1],8057)
    def test_external_providers_disabled(self):
        env=safe_environment();self.assertEqual(env['DORA_MODEL_EXTERNAL_ENABLED'],'false')
        for key in ('DORA_LLM_API_KEY','DORA_RAG_OPENAI_API_KEY','OPENAI_API_KEY'):self.assertEqual(env[key],'')

if __name__=='__main__':unittest.main()
