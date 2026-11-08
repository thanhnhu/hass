import json
import shutil
from pathlib import Path

root = Path('/home/ubuntu/agent-maintenance')
root.mkdir(parents=True, exist_ok=True)
config = json.loads(Path('/opt/openclaw/config/openclaw.json').read_text())
profile = {
    'default_model': config['agents']['defaults']['model'],
    'bootstrapTotalMaxChars': config['agents']['defaults'].get('bootstrapTotalMaxChars'),
    'providers': {
        name: {'api': provider.get('api'), 'timeoutSeconds': provider.get('timeoutSeconds'),
               'models': provider.get('models', [])}
        for name, provider in config['models']['providers'].items()
    },
}
(root / 'openclaw-profile.json').write_text(json.dumps(profile, indent=2) + '\n')
shutil.copy2('/opt/voice-router/router.py', root / 'router.py')
if Path('/tmp/test_router.py').exists():
    shutil.copy2('/tmp/test_router.py', root / 'test_router.py')
print('Prepared a secret-free maintenance copy and model profile.')