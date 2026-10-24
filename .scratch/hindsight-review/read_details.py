"""Read-only operation details and pinned public upstream source inventory."""
import json, tomllib
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from concurrent.futures import ThreadPoolExecutor

OUT = Path(__file__).parent
config = tomllib.loads(Path.home().joinpath('.hindsight/config').read_text())
base = config['api_url'].rstrip('/')
def get(path):
    with urlopen(Request(base+path, headers={'Authorization':'Bearer '+config['api_key']}, method='GET'), timeout=40) as r:
        return json.load(r)
bank = '/v1/default/banks/atlas-ai-infrastructure'
paths = {'consolidations':bank+'/operations?type=consolidation&limit=12',
         'observations':bank+'/memories/list?type=observation&limit=100',
         'stats':bank+'/stats?refresh=true'}
with ThreadPoolExecutor(max_workers=3) as pool:
    data = dict(zip(paths, pool.map(get, paths.values())))
data['time_utc'] = datetime.now(timezone.utc).isoformat()
ops = data['consolidations']['operations']
data['operation_details'] = [get(bank+'/operations/'+o['id']) for o in ops[:4]]
with urlopen('https://atlas.ekenhome.se/api/v1/memory/health',timeout=40) as r:
    data['atlas_health'] = json.load(r)
(OUT/'production-details.json').write_text(json.dumps(data,indent=2))
print(json.dumps({k:data[k] for k in ['time_utc','stats','consolidations','operation_details']},indent=2))
print('Atlas consolidation:', json.dumps(data['atlas_health'].get('consolidation',{}),indent=2))
commit='5fc4ce20917b916240cef27c212c387a177f115b'
with urlopen('https://api.github.com/repos/vectorize-io/hindsight/git/trees/'+commit+'?recursive=1',timeout=40) as r:
    tree = json.load(r)
paths = [i['path'] for i in tree['tree'] if ('consolidat' in i['path'] or 'observation' in i['path']) and i['path'].endswith('.py')]
(OUT/'upstream-paths.json').write_text(json.dumps(paths,indent=2))
print('PINNED SOURCE PATHS:', json.dumps(paths,indent=2))
