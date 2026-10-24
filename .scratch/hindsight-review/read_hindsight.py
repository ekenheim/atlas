"""Read-only GET diagnostics. Never emits credentials or request headers."""
import json
import tomllib
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from urllib.parse import urlsplit
from concurrent.futures import ThreadPoolExecutor

OUT = Path(__file__).parent
config = tomllib.loads(Path.home().joinpath('.hindsight/config').read_text())
base = config['api_url'].rstrip('/')
headers = {'Authorization': 'Bearer ' + config['api_key']}
def get(path):
    try:
        with urlopen(Request(base + path, headers=headers, method='GET'), timeout=40) as response:
            return json.load(response)
    except HTTPError as e:
        return {'http_status':e.code}

bank = '/v1/default/banks/atlas-ai-infrastructure'
paths = {'version':'/version', 'stats':bank+'/stats', 'scopes':bank+'/observations/scopes',
         'operations':bank+'/operations?limit=12', 'config':bank+'/config',
         'llm_stats':bank+'/llm-requests/stats?period=1d'}
def safe(value):
    if isinstance(value,dict):
        return {k: ('<REDACTED>' if any(t in k.lower() for t in ('api_key','password','secret','authorization','access_token')) else safe(v)) for k,v in value.items()}
    if isinstance(value,list):
        return [safe(v) for v in value]
    return value
with ThreadPoolExecutor(max_workers=3) as pool:
    data = dict(zip(paths, pool.map(get, paths.values())))
data = safe(data)
data['time_utc'] = datetime.now(timezone.utc).isoformat()
data['endpoint'] = {'host':urlsplit(base).hostname, 'path':urlsplit(base).path}
(OUT/'production-state.json').write_text(json.dumps(data, indent=2))
print(json.dumps(data, indent=2))
