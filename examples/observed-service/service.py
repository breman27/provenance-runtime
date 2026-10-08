"""Process one batch of sensor readings and emit operational JSON logs."""
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

READINGS = (12, -8, 50, 100, 125, 200)


def main():
    source_directory = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / 'src'
    revision = sys.argv[2] if len(sys.argv) > 2 else 'local-working-tree'
    source_hash = 'sha256:' + hashlib.sha256((source_directory / 'clamp.py').read_bytes()).hexdigest()
    sys.path.insert(0, str(source_directory))
    from clamp import clamp
    readings = json.loads(sys.argv[3]) if len(sys.argv) > 3 else READINGS
    if (not isinstance(readings, (tuple, list)) or not 1 <= len(readings) <= 64
            or any(type(value) is not int or abs(value) > 1000000 for value in readings)):
        raise ValueError('invalid reading batch')
    for index, value in enumerate(readings):
        print(json.dumps({'event': 'reading_processed', 'sequence': index,
                          'timestamp': datetime.now(timezone.utc).isoformat(),
                          'revision': revision, 'source_hash': source_hash,
                          'input': value, 'lower': 0, 'upper': 100, 'output': clamp(value, 0, 100)}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
