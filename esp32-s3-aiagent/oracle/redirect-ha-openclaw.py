import json
import os
import shutil
import subprocess
from pathlib import Path

path = Path('/DATA/AppData/big-bear-home-assistant/config/.storage/core.config_entries')
source = Path('/DATA/AppData/big-bear-openclaw/config/openclaw.json')
subprocess.run(['docker', 'stop', '--timeout', '30', 'big-bear-home-assistant'], check=True)
try:
    data = json.loads(path.read_text())
    matches = [entry for entry in data['data']['entries']
               if entry['domain'] == 'extended_openai_conversation' and entry['title'] == 'OpenClaw']
    if len(matches) != 1:
        raise RuntimeError('Expected exactly one existing OpenClaw entry')
    shutil.copy2(path, path.with_name('core.config_entries.before-oracle-openclaw'))
    entry = matches[0]
    entry['data']['base_url'] = 'http://100.92.183.123:18789/v1'
    entry['data']['api_key'] = json.loads(source.read_text())['gateway']['auth']['token']
    temporary = path.with_name('core.config_entries.oracle.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False) + '\n')
    os.chmod(temporary, path.stat().st_mode & 0o777)
    os.replace(temporary, path)
    print('Updated only the existing OpenClaw endpoint; credentials not displayed.')
finally:
    subprocess.run(['docker', 'start', 'big-bear-home-assistant'], check=True)
subprocess.run(['docker', 'update', '--restart=no', 'big-bear-openclaw'], check=True)