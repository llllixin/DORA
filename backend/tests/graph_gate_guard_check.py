import unittest
try:
    from tests.graph_gate import validate_environment
except ImportError:
    validate_environment=None


class GraphGateGuard(unittest.TestCase):
    def test_only_explicit_disposable_environment_admitted(self):
        self.assertIsNotNone(validate_environment,'A09 guarded verification runner missing')
        good={'DATABASE_URL':'postgresql+psycopg://dora_a09:test@127.0.0.1:55459/dora_a09','DORA_API_BASE':'http://127.0.0.1:8059/api'}
        self.assertEqual(validate_environment(good)[1],8059)
        for change in [{},{'DATABASE_URL':'postgresql+psycopg://dora:test@localhost:5432/dora'},
                       {'DATABASE_URL':good['DATABASE_URL']+'?options=unsafe'},
                       {'DORA_API_BASE':'http://127.0.0.1:8000/api'}, {'DORA_API_BASE':'https://example.com/api'}]:
            value={} if not change else {**good,**change}
            with self.subTest(value=value),self.assertRaises(ValueError):validate_environment(value)


if __name__=='__main__':unittest.main()
