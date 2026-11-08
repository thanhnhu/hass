import json
import shutil
from datetime import datetime
from pathlib import Path

path = Path('/opt/openclaw/config/openclaw.json')
config = json.loads(path.read_text())
timestamp = datetime.now().strftime('%Y%m%d-%H%M%S')
backup = path.with_name(f'{path.stem}.before-gemini-primary-{timestamp}{path.suffix}')
shutil.copy2(path, backup)
provider = config['models']['providers']['ollama']
provider.update(baseUrl='http://host.docker.internal:11434', api='ollama', timeoutSeconds=10)
model = next(
    (item for item in provider['models'] if item.get('id') == 'qwen3.5:4b'),
    None,
)
if model is None:
    model = {
        'id': 'qwen3.5:4b',
        'name': 'Qwen3.5 4B Oracle',
        'reasoning': False,
        'input': ['text'],
        'contextWindow': 8192,
        'maxTokens': 256,
    }
    provider['models'].append(model)
model.update(contextTokens=8192, maxTokens=256,
             params={'think': False, 'num_ctx': 8192, 'keep_alive': '15m'})
config['agents']['defaults'].get('experimental', {}).pop('localModelLean', None)
config['agents']['defaults']['skills'] = []
config['agents']['defaults']['model'] = {
    'primary': 'google/gemini-3.5-flash-lite',
    'fallbacks': ['ollama/qwen3.5:4b'],
}
tools = config.setdefault('tools', {})
tools['profile'] = 'minimal'
tools.pop('alsoAllow', None)
remove = {
    'homeassistant__GetLiveContext',
    'homeassistant__prompts_get', 'homeassistant__prompts_list',
    'homeassistant__resources_list', 'homeassistant__resources_read',
    'homeassistant__dieuhoa_bat', 'homeassistant__dieuhoa_tat',
    'homeassistant__dieuhoa_tang_nhiet', 'homeassistant__dieuhoa_giam_nhiet',
    'homeassistant__quat_tang_tocdo', 'homeassistant__quat_giam_tocdo',
}
tools['deny'] = sorted(set(tools.get('deny', [])) | remove)
config['models']['providers']['router'] = {
    'baseUrl': 'http://172.19.0.1:8787/v1',
    'apiKey': 'router-local',
    'api': 'openai-completions',
    'timeoutSeconds': 35,
    'models': [{
        'id': 'voice-router', 'name': 'Oracle Voice Router',
        'reasoning': False, 'input': ['text'], 'contextWindow': 8192,
        'maxTokens': 512, 'compat': {'supportsTools': False},
    }],
}
model_allow = config['agents']['defaults'].get('modelPolicy', {}).get('allow')
if isinstance(model_allow, list):
    for model_id in (
        'google/gemini-3.5-flash-lite',
        'ollama/qwen3:1.7b',
        'ollama/qwen3.5:4b',
    ):
        if model_id not in model_allow:
            model_allow.append(model_id)
path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + '\n')
print('Configured Gemini primary, Qwen3.5:4B Ollama fallback, and retained the minimal tool/skill profile.')