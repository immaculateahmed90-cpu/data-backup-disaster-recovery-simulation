"""Real, local full-snapshot backups. Standard library only."""
from pathlib import Path, PurePosixPath
from datetime import datetime, timezone
import hashlib
import json
import os
import re
import shutil
import stat
import time
import uuid


def linked(path):
    s = path.lstat()
    return stat.S_ISLNK(s.st_mode) or bool(getattr(s, 'st_file_attributes', 0) & 0x400)


def clean_path(value):
    p = Path(value).absolute()
    for part in [p, *p.parents]:
        if part.exists() and linked(part):
            raise ValueError('Symbolic links and Windows junctions are not supported.')
    return p.resolve()


def overlap(a, b):
    return a == b or a in b.parents or b in a.parents


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def safe_relative(name):
    if not isinstance(name, str) or not name or '\\' in name or ':' in name:
        raise ValueError('Unsafe path in backup manifest.')
    p = PurePosixPath(name)
    if p.is_absolute() or any(x in ('', '.', '..') for x in name.split('/')):
        raise ValueError('Unsafe path in backup manifest.')
    if any(x.endswith((' ', '.')) or x.split('.')[0].upper() in
           {'CON', 'PRN', 'AUX', 'NUL', *['COM'+str(i) for i in range(1,10)],
            *['LPT'+str(i) for i in range(1,10)]} for x in p.parts):
        raise ValueError('Unsupported Windows filename in manifest.')
    return Path(*p.parts)


def read_manifest(snapshot):
    snapshot = clean_path(snapshot)
    m = json.loads(clean_path(snapshot / 'manifest.json').read_text(encoding='utf-8'))
    if m.get('format') != 1 or not isinstance(m.get('files'), dict):
        raise ValueError('Unsupported backup manifest.')
    if not isinstance(m.get('id'),str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',m['id']):
        raise ValueError('Invalid snapshot identifier.')
    if not isinstance(m.get('source'),str) or not Path(m['source']).is_absolute():
        raise ValueError('Invalid source path in manifest.')
    if not isinstance(m.get('directories',[]),list):
        raise ValueError('Invalid directory list.')
    seen = set()
    for name, meta in m['files'].items():
        safe_relative(name)
        if name.casefold() in seen:
            raise ValueError('Conflicting filenames in manifest.')
        seen.add(name.casefold())
        if not isinstance(meta,dict) or not isinstance(meta.get('sha256'), str) or not re.fullmatch(r'[0-9a-f]{64}',meta['sha256']):
            raise ValueError('Invalid file checksum.')
        if not isinstance(meta.get('size'),int) or isinstance(meta['size'],bool) or meta['size'] < 0:
            raise ValueError('Invalid file size.')
    for name in m.get('directories', []):
        safe_relative(name)
    return m


def create_backup(source, vault, progress=lambda n, text: None):
    start = time.perf_counter()
    capture_started = datetime.now(timezone.utc).isoformat()
    source, vault = clean_path(source), clean_path(vault)
    if not source.is_dir():
        raise ValueError('Choose an existing source folder.')
    if overlap(source, vault):
        raise ValueError('Source and backup storage must be separate, non-overlapping folders.')
    vault.mkdir(parents=True, exist_ok=True)
    ident = datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8]
    staging = vault / ('.partial-' + ident)
    staging.mkdir()
    try:
        data = staging / 'data'
        data.mkdir()
        entries, directories = [], []
        def fail_scan(error):
            raise error
        for root, dirs, files in os.walk(source, followlinks=False, onerror=fail_scan):
            for name in dirs + files:
                p = Path(root) / name
                if linked(p):
                    raise ValueError('Backup stopped: link or junction encountered: ' + str(p))
            for name in dirs:
                rel = (Path(root) / name).relative_to(source).as_posix()
                safe_relative(rel)
                directories.append(rel)
            for name in files:
                p = Path(root) / name
                if not p.is_file():
                    raise ValueError('Unsupported file: ' + str(p))
                entries.append(p)
        records = {}
        for directory in directories:
            (data / directory).mkdir(parents=True, exist_ok=True)
        for i, src in enumerate(entries):
            rel = src.relative_to(source).as_posix()
            safe_relative(rel)
            before = src.stat()
            dest = data / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            copied_hash = sha(dest)
            source_hash = sha(src)
            after = src.stat()
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns) or copied_hash != source_hash:
                raise ValueError('File changed while backing up: ' + rel + '. Close editing apps and retry.')
            records[rel] = {'size': after.st_size, 'sha256': copied_hash}
            progress(int((i+1)*100/max(1,len(entries))), rel)
        result = {'format': 1, 'id': ident, 'created': datetime.now(timezone.utc).isoformat(),
                  'source': str(source), 'capture_started': capture_started,
                  'type': 'Full snapshot', 'files': records,
                  'directories': directories, 'bytes': sum(x['size'] for x in records.values()),
                  'duration_seconds': round(time.perf_counter()-start, 3)}
        (staging / 'manifest.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
        staging.rename(vault / ident)
        progress(100, 'Backup complete and verified')
        return result
    except Exception:
        shutil.rmtree(staging)
        raise


def verify_backup(snapshot, progress=lambda n, text: None):
    snapshot = clean_path(snapshot)
    m = read_manifest(snapshot)
    for i, (name, meta) in enumerate(m['files'].items()):
        p = clean_path(snapshot / 'data' / safe_relative(name))
        if not p.is_file() or p.stat().st_size != meta['size'] or sha(p) != meta['sha256']:
            raise ValueError('Integrity verification failed: ' + name)
        progress(int((i+1)*100/max(1,len(m['files']))), name)
    for name in m.get('directories', []):
        if not clean_path(snapshot / 'data' / safe_relative(name)).is_dir():
            raise ValueError('Missing backup directory: ' + name)
    progress(100, 'All backup files verified')
    return m


def restore_backup(snapshot, destination, progress=lambda n, text: None):
    started = time.perf_counter()
    snapshot, destination = clean_path(snapshot), clean_path(destination)
    m = verify_backup(snapshot)
    if overlap(destination, snapshot.parent):
        raise ValueError('Restore destination must be outside the backup storage folder.')
    if overlap(destination, Path(m['source']).resolve()):
        raise ValueError('Choose a restore destination separate from the original source.')
    destination.mkdir(parents=True, exist_ok=True)
    output = destination / ('Restored-' + m['id'] + '-' + uuid.uuid4().hex[:6])
    output.mkdir()
    try:
        for name in m.get('directories', []):
            (output / safe_relative(name)).mkdir(parents=True, exist_ok=True)
        for i, (name, meta) in enumerate(m['files'].items()):
            src = clean_path(snapshot / 'data' / safe_relative(name))
            dst = output / safe_relative(name)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            if sha(dst) != meta['sha256']:
                raise ValueError('Restored file verification failed: ' + name)
            progress(int((i+1)*100/max(1,len(m['files']))), name)
        progress(100, 'Restore complete and verified')
        return {'output': str(output), 'files': len(m['files']),
                'restore_seconds': time.perf_counter() - started,
                'integrity': 'PASS', 'snapshot_id': m['id']}
    except Exception:
        shutil.rmtree(output)
        raise


def history(vault):
    vault = clean_path(vault)
    items = []
    if vault.is_dir():
        for p in vault.iterdir():
            if not linked(p) and p.is_dir() and not p.name.startswith('.') and (p/'manifest.json').is_file():
                try:
                    m = read_manifest(p)
                    m['snapshot_path'] = str(p)
                    items.append(m)
                except (ValueError, OSError, KeyError):
                    continue
    return sorted(items, key=lambda x: x['created'], reverse=True)
