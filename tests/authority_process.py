"""Cold operator process and explicit crash injection confined to test code."""
import os
import sys
from unittest.mock import patch

# An accidental provider import fails even if the machine has a configured key.
os.environ.pop('OPENAI_API_KEY', None)
sys.modules['provenance.clients.observed_service.agent'] = None
sys.modules['provenance.clients.repo_repair.openai_worker'] = None
from provenance.clients.authority.manager import ApprovalManager
from provenance.runtime import Runtime
from provenance.format import canonical_json


def main():
    root, command, action = sys.argv[1:4]
    manager = ApprovalManager(root)
    if command in ('deny-before-invalidate', 'deny-before-supersede', 'renew-before-supersede'):
        method = 'invalidate' if command == 'deny-before-invalidate' else 'supersede'
        with patch.object(Runtime, method, side_effect=lambda *a, **k: os._exit(91)):
            result = manager.approve(action, renew=True) if command.startswith('renew') else manager.deny(action)
    else:
        result = getattr(manager, command)(action)
    sys.stdout.buffer.write(canonical_json(result.as_dict())+b'\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
