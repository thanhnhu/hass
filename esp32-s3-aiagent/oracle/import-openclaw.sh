#!/usr/bin/env bash
set -euo pipefail
umask 077
install -d -m 700 /opt/openclaw /opt/openclaw/metadata
test ! -e /opt/openclaw/config/openclaw.json
tar -xzf /tmp/openclaw-migration.tar.gz -C /opt/openclaw
tar -xzf /tmp/openclaw-metadata.tar.gz -C /opt/openclaw/metadata
python3 - <<'PY'
import json
import os
from pathlib import Path

root = Path('/opt/openclaw')
container = json.loads((root / 'metadata/container.json').read_text())[0]
image = json.loads((root / 'metadata/image.json').read_text())[0]
image_ref = next(iter(image.get('RepoDigests', [])), container['Config']['Image'])
config_path = root / 'config/openclaw.json'
config = json.loads(config_path.read_text())
config['mcp']['servers']['homeassistant']['url'] = 'http://100.78.12.116:8123/api/mcp'
providers = config['models']['providers']
providers['ollama'] = {
    'baseUrl': 'http://host.docker.internal:11434',
    'apiKey': 'ollama', 'api': 'ollama', 'timeoutSeconds': 10,
    'models': [{'id': 'qwen3:1.7b', 'name': 'Qwen3 1.7B Oracle',
                'reasoning': False, 'input': ['text'],
                'contextWindow': 8192, 'contextTokens': 8192, 'maxTokens': 256,
                'params': {'think': False, 'num_ctx': 8192, 'keep_alive': '15m'}}],
}
google_models = providers['google']['models']
if not any(model['id'] == 'gemini-3.5-flash-lite' for model in google_models):
    google_models.append({'id': 'gemini-3.5-flash-lite', 'name': 'Gemini Flash Lite fallback',
                          'reasoning': False, 'input': ['text'],
                          'contextWindow': 1048576, 'maxTokens': 512})
defaults = config['agents']['defaults']
defaults['model'] = {'primary': 'ollama/qwen3:1.7b',
                     'fallbacks': ['google/gemini-3.5-flash-lite']}
defaults['utilityModel'] = 'ollama/qwen3:1.7b'
defaults['bootstrapTotalMaxChars'] = 1024
allow = defaults.get('modelPolicy', {}).get('allow')
if isinstance(allow, list):
    for model in ('ollama/qwen3:1.7b', 'google/gemini-3.5-flash-lite'):
        if model not in allow:
            allow.append(model)
config['gateway']['controlUi']['allowedOrigins'] = [
    'http://100.92.183.123:18789', 'http://localhost:18789', 'http://127.0.0.1:18789']
config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + '\n')
env = dict(value.split('=', 1) for value in container['Config']['Env'])
env.update({'OPENAI_BASE_URL': 'http://host.docker.internal:11434/v1',
            'OPENAI_MODEL': 'qwen3:1.7b', 'OPENAI_API_KEY': 'ollama',
            'NODE_OPTIONS': '--max-old-space-size=1536'})
compose = {'services': {'openclaw': {
    'image': image_ref, 'container_name': 'oracle-openclaw',
    'restart': 'unless-stopped', 'init': True,
    'environment': env,
    'command': container['Config']['Cmd'],
    'extra_hosts': ['host.docker.internal:host-gateway'],
    'ports': ['100.92.183.123:18789:18789', '100.92.183.123:18790:18790'],
    'volumes': ['/opt/openclaw/config:/home/node/.openclaw',
                '/opt/openclaw/workspace:/home/node/.openclaw/workspace'],
    'mem_limit': '2g',
}}}
(root / 'compose.json').write_text(json.dumps(compose, indent=2) + '\n')
os.chmod(root / 'compose.json', 0o600)
os.chmod(config_path, 0o600)
print('Pinned image:', image_ref)
print('Primary: ollama/qwen3:1.7b; fallback: google/gemini-3.5-flash-lite')
PY
chown -R 1000:1000 /opt/openclaw/config /opt/openclaw/workspace
docker compose -f /opt/openclaw/compose.json config --quiet
docker compose -f /opt/openclaw/compose.json up -d
docker inspect -f 'Oracle OpenClaw running={{.State.Running}}' oracle-openclaw