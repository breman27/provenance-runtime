"""Trusted container entry point. Never run candidate code on the host."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import unittest


def main():
    suite_name = sys.argv[1]
    if suite_name not in ('targeted_tests', 'full_suite'):
        raise ValueError('unknown test suite')
    source = Path('/candidate/clamp.py')
    tests = Path('/trusted/test_clamp.py')
    hash_of = lambda path: 'sha256:' + hashlib.sha256(path.read_bytes()).hexdigest()
    source_hash, tests_hash = hash_of(source), hash_of(tests)
    sys.path.insert(0, '/candidate')
    spec = importlib.util.spec_from_file_location('trusted_clamp_tests', tests)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromTestCase(module.ClampTests) if suite_name == 'full_suite' else loader.loadTestsFromName('ClampTests.test_above_upper', module)
    result = unittest.TextTestRunner(stream=sys.stderr, verbosity=2).run(suite)
    successful = result.wasSuccessful() and result.testsRun > 0
    print(json.dumps(dict(suite=suite_name, tests_run=result.testsRun, failures=len(result.failures),
                         errors=len(result.errors), successful=successful,
                         candidate_hash=source_hash, tests_hash=tests_hash)))
    return 0 if successful else 1


if __name__ == '__main__':
    raise SystemExit(main())
