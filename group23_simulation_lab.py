"""CYB201 Group 23: deterministic, in-memory backup and recovery lab.

Uses synthetic data only. No user files are read, changed, or deleted.
"""
from dataclasses import dataclass
import hashlib
import json


def digest(data):
    return hashlib.sha256(data).hexdigest()


@dataclass
class Backup:
    kind: str
    minute: int
    parent: str | None
    payload: dict
    deleted: tuple
    manifest: dict

    @property
    def identity(self):
        metadata = [self.kind, self.minute, self.parent, self.deleted,
                    self.manifest]
        return digest(json.dumps(metadata, sort_keys=True).encode())


def restore(chain):
    """Restore an ordered dependency chain and verify every resulting snapshot."""
    if not chain or chain[0].kind != 'full':
        raise ValueError('Recovery requires a full backup first')
    state = {}
    previous = None
    for backup in chain:
        if backup.kind not in ('full', 'incremental', 'differential'):
            raise ValueError('Unknown backup kind')
        if backup.parent != previous:
            raise ValueError('Missing or out-of-order backup dependency')
        if backup.kind == 'full':
            state = {}
        for name in backup.deleted:
            state.pop(name, None)
        state.update(backup.payload)
        if {name: digest(data) for name, data in state.items()} != backup.manifest:
            raise ValueError('Backup integrity check failed')
        previous = backup.identity
    return state


def take_backup(state, minute, kind='full', base_chain=()):
    if kind not in ('full', 'incremental', 'differential'):
        raise ValueError('Unknown backup kind')
    if minute < 0:
        raise ValueError('Minute must be nonnegative')
    if kind == 'full':
        baseline, parent = {}, None
    else:
        if not base_chain:
            raise ValueError('A baseline is required')
        if kind == 'differential' and len(base_chain) != 1:
            raise ValueError('Differential baseline must be the full backup only')
        baseline = restore(base_chain)
        if minute <= base_chain[-1].minute:
            raise ValueError('Backup time must follow baseline')
        parent = base_chain[-1].identity
    payload = {name: data for name, data in state.items()
               if baseline.get(name) != data}
    return Backup(kind, minute, parent, payload,
                  tuple(sorted(set(baseline) - set(state))),
                  {name: digest(data) for name, data in state.items()})


def run_demo():
    original = {'students.csv': b'id,name\n1,Ada\n',
                'notes.txt': b'CYB201 backup lab', 'old.txt': b'obsolete'}
    day1 = dict(original)
    day1['students.csv'] += b'2,Musa\n'
    del day1['old.txt']
    day2 = dict(day1, **{'notes.txt': b'Updated recovery plan'})
    full = take_backup(original, 0)
    inc1 = take_backup(day1, 60, 'incremental', [full])
    inc2 = take_backup(day2, 120, 'incremental', [full, inc1])
    diff = take_backup(day2, 120, 'differential', [full])
    latest_full = take_backup(day2, 120)
    # Synthetic event at minute 150 destroys the modeled primary dataset.
    primary = dict(day2, **{'unsaved.txt': b'Created after latest backup'})
    primary.clear()
    results = []
    for strategy, chain in [('Full', [latest_full]),
                            ('Incremental', [full, inc1, inc2]),
                            ('Differential', [full, diff])]:
        recovered = restore(chain)
        if recovered != day2:
            raise ValueError('Recovered snapshot differs from expected data')
        transferred = sum(sum(map(len, b.payload.values())) for b in chain)
        results.append({'strategy': strategy, 'integrity': 'PASS',
                        'restore_sets': len(chain), 'payload_bytes': transferred,
                        'modeled_data_loss_window_minutes': 150 - chain[-1].minute,
                        'modeled_restore_seconds': round(len(chain) * 2 + transferred / 1024, 3)})
    return results


def main():
    print('CYB201 Group 23 - Backup and Disaster Recovery Simulation')
    print('Synthetic in-memory lab; no user files are modified.')
    print('Timing and data-loss windows are MODELED, not measured benchmarks.')
    print('Restore model: 2 seconds/set + payload bytes / 1024 bytes/second.')
    print('Disaster: minute 150; last backup: minute 120; unsaved.txt is lost.')
    print(json.dumps(run_demo(), indent=2))


if __name__ == '__main__':
    main()
