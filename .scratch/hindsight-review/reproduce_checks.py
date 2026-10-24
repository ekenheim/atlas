"""Offline diagnostic. No server access; exercises production conformance predicates."""
import json
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace as NS

REPO = Path('/mnt/c/Users/ekenh/worktrees/atlas/oval-tide/atlas')
sys.path.insert(0, str(REPO / 'backend'))
from atlas.conformance.behaviours import BehaviourBank, CHECKS, run_checks

class Bank(BehaviourBank):
    def memory_documents(self):
        return self.documents

class Gateway:
    bank_id = 'offline'
    def entities(self, **kw):
        return NS(items=[NS(id='e1', canonical_name='Lumentum', mention_count=2),
                         NS(id='e2', canonical_name='Coherent', mention_count=2)], total=2)
    def entity_memories(self, entity_id, **kw):
        return [NS(document_id='cross')]
    def document_memories(self, document_id):
        if document_id == 'optics':
            return [NS(id='laser', tags=['layer:chip-laser'], text='Lumentum makes lasers.')]
        if document_id == 'cover':
            return [NS(id='filing', tags=[], text='An initial quarterly report.')]
        return [NS(id='cfo-answer', text=CFO)]
    def recall(self, *a, **kw):
        return NS(memories=[NS(id='laser', tags=['layer:chip-laser'])])

class Api:
    def text(self, path, **kw):
        return 'An initial quarterly report.' if 'cover' in path else 'Lumentum makes lasers.'

CFO = ('Casey Placeholder stated that Lumentum does not break out how much demand comes '
       'from its largest customer, but that its backlog is broad and spread across '
       'several customers. | Involving: Casey Placeholder (CFO, Lumentum); Lumentum')

items = [dict(document_id='own', tags=['company:l'], entities=[{'text':'Lumentum'}]),
         dict(document_id='other', tags=['company:c'], entities=[{'text':'Coherent'}]),
         dict(document_id='cross', tags=['company:c'], entities=[{'text':'Coherent'}, {'text':'Lumentum'}])]
bank = Bank(None, Gateway(), 'photonics', {'lumentum':'l','coherent':'c'}, {},
            lambda: items, {}, frozenset(), lambda:None, lambda *a:None)
bank.documents = [dict(document_id=i['document_id'], retain_state='completed', fact_count=1) for i in items]
checks = [replace(c, present=lambda b: True) for c in CHECKS if c.number in (2,8)]
baseline = run_checks(bank, checks)
items.append(items[-1].copy())  # same document submitted twice: retry/no-op
repeated = run_checks(bank, checks)
bank.documents = [dict(document_id='transcript', kind='transcript')]
items.append(dict(document_id='transcript', context='Company officers and analysts speak.'))
speaker = run_checks(bank, [replace(c, present=lambda b: True) for c in CHECKS if c.number == 3])
bank.api = Api()
bank.documents = [dict(document_id='optics', version_id='optics', retain_state='completed', char_start=0, char_end=21)]
layer_check = [replace(c, present=lambda b:True) for c in CHECKS if c.number == 4]
layers_baseline = run_checks(bank, layer_check)
bank.documents.append(dict(document_id='cover', version_id='cover', retain_state='completed', char_start=0, char_end=28))
layers = run_checks(bank, layer_check)
result = {'unique_submission': [r.model_dump() for r in baseline],
          'identical_document_resubmitted': [r.model_dump() for r in repeated],
          'correctly_attributed_cfo_answer': [r.model_dump() for r in speaker],
          'valid_layer_labels': [r.model_dump() for r in layers_baseline],
          'valid_layer_labels_plus_neutral_cover': [r.model_dump() for r in layers]}
Path(__file__).with_name('offline-results.json').write_text(json.dumps(result, indent=2))
for name, results in result.items():
    for r in results:
        print(f'{name}: check {r["number"]}: {r["verdict"]}: {r["reason"]}')
assert all(r.verdict == 'passed' for r in repeated + speaker + layers), 'Conformance falsely rejects unchanged state / valid CFO attribution / neutral text'
