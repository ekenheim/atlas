"""Fetch public pinned source for inspection; no credentials."""
from pathlib import Path
from urllib.request import urlopen
from concurrent.futures import ThreadPoolExecutor
ROOT=Path(__file__).parent/'upstream'
ROOT.mkdir(exist_ok=True)
COMMIT='5fc4ce20917b916240cef27c212c387a177f115b'
PATHS=['hindsight-api-slim/hindsight_api/engine/consolidation/consolidator.py',
       'hindsight-api-slim/tests/test_consolidation_reschedule_after_round.py',
       'hindsight-api-slim/tests/test_consolidation_write_scopes.py',
       'hindsight-api-slim/hindsight_api/engine/memory_engine.py']
def fetch(path):
    with urlopen('https://raw.githubusercontent.com/vectorize-io/hindsight/'+COMMIT+'/'+path, timeout=40) as r:
        content=r.read()
    (ROOT/path.rsplit('/',1)[-1]).write_bytes(content)
    return path,len(content)
with ThreadPoolExecutor(max_workers=3) as p:
    for path,size in p.map(fetch,PATHS): print(path,size)
