"""Compiled client profiles; files and model output cannot supply policies."""
from ...errors import fail
from ...runtime import Policy


def authority_policy(mode: str) -> Policy:
    if mode not in ('manual', 'auto'):
        fail('APPROVAL_MODE', 'approval mode must be manual or auto')
    return Policy('observed-service-manual-v1' if mode == 'manual' else 'observed-service-v1',
                  'observed-service', ('collector',),
                  {'tester': ('targeted_tests', 'full_suite')},
                  ('human-operator',) if mode == 'manual' else ('issuer',), ('controller',),
                  {'repo.repair.simulated': ('targeted_tests', 'full_suite')})


def profile_name(mode):
    authority_policy(mode)
    return 'observed-service-' + mode + '-v1'
