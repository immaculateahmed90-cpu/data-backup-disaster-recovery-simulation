"""Recovery Vault v3 archive: AES-256-GCM + scrypt; no password persistence.

RVENC003 | salt(16) | nonce(12) | ciphertext | GCM tag(16).
The entire header is authenticated. Decrypted payload is uint64 little-endian
manifest length, UTF-8 JSON manifest, then file bytes in sorted path order.
Fixed per-version KDF parameters avoid attacker-controlled resource costs.
"""
from pathlib import Path
import hashlib
import json
import os
import shutil
import struct
import tempfile
import time
import uuid
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
import backup_engine as engine

MAGIC = b'RVENC003'
HEADER_SIZE = 36
MAX_PAYLOAD = 32 * 1024**3
MAX_MANIFEST = 8 * 1024**2
CHUNK = 1024**2


def _key(password, salt):
    if not isinstance(password,str) or not password or len(password.encode('utf-8')) > 1024:
        raise ValueError('Enter a password of 1–1024 UTF-8 bytes.')
    return Scrypt(salt=salt,length=32,n=2**17,r=8,p=1).derive(password.encode('utf-8'))


def _decrypt_to(archive, password, sink, progress=lambda n,text:None):
    """Never parse or publish sink contents until authentication succeeds."""
    with archive.open('rb') as src:
        length = os.fstat(src.fileno()).st_size
        if length < HEADER_SIZE+16 or length-HEADER_SIZE-16 > MAX_PAYLOAD:
            raise ValueError('Invalid or unsupported encrypted archive size (32 GiB maximum payload).')
        header = src.read(HEADER_SIZE)
        if header[:8] != MAGIC:
            raise ValueError('Unsupported encrypted archive format.')
        src.seek(-16,os.SEEK_END)
        tag = src.read(16)
        src.seek(HEADER_SIZE)
        decryptor = Cipher(algorithms.AES(_key(password,header[8:24])),modes.GCM(header[24:],tag)).decryptor()
        decryptor.authenticate_additional_data(header)
        remaining = length-HEADER_SIZE-16
        total = remaining
        try:
            while remaining:
                block = src.read(min(CHUNK,remaining))
                if not block:
                    raise ValueError('Encrypted archive is truncated.')
                sink(decryptor.update(block))
                remaining -= len(block)
                progress(int(80*(total-remaining)/max(1,total)),'Authenticating encrypted archive')
            sink(decryptor.finalize())
        except InvalidTag:
            raise ValueError('Wrong password or damaged encrypted archive. No files were restored.') from None


def export_encrypted(snapshot, output, password, progress=lambda n,text:None):
    started = time.perf_counter()
    if len(password) < 12:
        raise ValueError('Use a password of at least 12 characters; a long unique passphrase is recommended.')
    snapshot, output = engine.clean_path(snapshot), engine.clean_path(output)
    m = engine.verify_backup(snapshot)
    if engine.overlap(snapshot,output) or engine.overlap(Path(m['source']).resolve(),output):
        raise ValueError('Save the encrypted archive outside the original source and selected snapshot.')
    if output.exists():
        raise ValueError('Choose a new archive filename; existing files are never overwritten.')
    payload = json.dumps(m,sort_keys=True,ensure_ascii=False).encode('utf-8')
    if len(payload) > MAX_MANIFEST or 8+len(payload)+sum(v['size'] for v in m['files'].values()) > MAX_PAYLOAD:
        raise ValueError('Snapshot exceeds the archive limit: 32 GiB payload or 8 MiB manifest.')
    output.parent.mkdir(parents=True,exist_ok=True)
    salt,nonce = os.urandom(16),os.urandom(12)
    header = MAGIC+salt+nonce
    encryptor = Cipher(algorithms.AES(_key(password,salt)),modes.GCM(nonce)).encryptor()
    encryptor.authenticate_additional_data(header)
    temp = None
    try:
        with tempfile.NamedTemporaryFile(prefix='.encrypted-partial-',dir=output.parent,delete=False) as dst:
            temp = Path(dst.name)
            dst.write(header)
            dst.write(encryptor.update(struct.pack('<Q',len(payload))+payload))
            for i,(name,meta) in enumerate(sorted(m['files'].items())):
                digest = hashlib.sha256()
                count = 0
                with engine.clean_path(snapshot/'data'/engine.safe_relative(name)).open('rb') as src:
                    for block in iter(lambda:src.read(CHUNK),b''):
                        count += len(block)
                        if count > meta['size']:
                            raise ValueError('Backup file changed during encryption: '+name)
                        digest.update(block)
                        dst.write(encryptor.update(block))
                if count != meta['size'] or digest.hexdigest() != meta['sha256']:
                    raise ValueError('Backup file changed during encryption: '+name)
                progress(int(70*(i+1)/max(1,len(m['files']))),'Encrypting '+name)
            dst.write(encryptor.finalize())
            dst.write(encryptor.tag)
            dst.flush()
            os.fsync(dst.fileno())
        # Re-read and authenticate the entire export before publishing it.
        _decrypt_to(temp,password,lambda block:None)
        if os.name == 'nt':
            temp.rename(output)  # Windows rename fails if the target exists.
        else:
            os.link(temp,output)  # Exclusive publication on POSIX; no clobber.
            temp.unlink()
        progress(100,'Encrypted archive created and authenticated')
        return {'kind':'encrypted_export','archive':str(output),'snapshot_id':m['id'],
                'files':len(m['files']),'archive_bytes':output.stat().st_size,
                'duration_seconds':time.perf_counter()-started,'encryption':'AES-256-GCM',
                'key_derivation':'scrypt N=131072, r=8, p=1; 16-byte random salt',
                'authentication':'PASS','note':'Only this archive is encrypted. Original source and ordinary backup folders remain plaintext.'}
    finally:
        if temp is not None and temp.exists():
            temp.unlink()


def restore_encrypted(archive, destination, password, progress=lambda n,text:None):
    started = time.perf_counter()
    archive,destination = engine.clean_path(archive),engine.clean_path(destination)
    staging = None
    try:
        # Windows uses an OS-created temporary file removed when closed. It can
        # contain plaintext while authenticating, but is never parsed before finalization.
        with tempfile.TemporaryFile() as plain:
            _decrypt_to(archive,password,plain.write,progress)
            plain.seek(0)
            length = plain.read(8)
            if len(length) != 8:
                raise ValueError('Invalid encrypted payload.')
            length = struct.unpack('<Q',length)[0]
            if not 0 < length <= MAX_MANIFEST:
                raise ValueError('Invalid encrypted manifest length.')
            manifest = plain.read(length)
            if len(manifest) != length:
                raise ValueError('Truncated encrypted manifest.')
            m = engine.validate_manifest(json.loads(manifest.decode('utf-8')))
            if engine.overlap(destination,Path(m['source']).resolve()):
                raise ValueError('Choose a restore destination separate from the original source.')
            expected = 8+length+sum(v['size'] for v in m['files'].values())
            if plain.seek(0,os.SEEK_END) != expected:
                raise ValueError('Encrypted payload length does not match manifest.')
            plain.seek(8+length)
            destination.mkdir(parents=True,exist_ok=True)
            staging = Path(tempfile.mkdtemp(prefix='.restore-encrypted-partial-',dir=destination))
            for name in m.get('directories',[]):
                (staging/engine.safe_relative(name)).mkdir(parents=True,exist_ok=True)
            for i,(name,meta) in enumerate(sorted(m['files'].items())):
                target = staging/engine.safe_relative(name)
                target.parent.mkdir(parents=True,exist_ok=True)
                digest = hashlib.sha256()
                remaining = meta['size']
                with target.open('xb') as dst:
                    while remaining:
                        block = plain.read(min(CHUNK,remaining))
                        if not block:
                            raise ValueError('Truncated file in archive.')
                        dst.write(block)
                        digest.update(block)
                        remaining -= len(block)
                if digest.hexdigest() != meta['sha256'] or engine.sha(target) != meta['sha256']:
                    raise ValueError('Restored file integrity verification failed: '+name)
                progress(80+int(20*(i+1)/max(1,len(m['files']))),'Restoring '+name)
        output = destination/('Restored-encrypted-'+m['id']+'-'+uuid.uuid4().hex[:12])
        if output.exists():
            raise ValueError('Restore folder already exists. Retry to create a new folder.')
        staging.rename(output)
        progress(100,'Encrypted restore authenticated and verified')
        return {'kind':'encrypted_restore','output':str(output),'files':len(m['files']),
                'snapshot_id':m['id'],'integrity':'PASS','authentication':'PASS',
                'restore_seconds':time.perf_counter()-started,
                'scope':'Includes password derivation, authentication/decryption, file writing and SHA-256 verification; excludes operator response and service startup.'}
    except Exception:
        if staging is not None and staging.exists():
            shutil.rmtree(staging)
        raise


def copy_verified_archive(archive, destination, password, progress=lambda n,text:None):
    """Publish a new copy only after authenticating the destination bytes."""
    archive = engine.clean_path(archive)
    destination = engine.clean_path(destination)
    output = destination / archive.name
    if not destination.is_dir() or output.exists():
        raise ValueError('Choose an existing destination folder without an archive of the same name.')
    if archive.stat().st_size > HEADER_SIZE + MAX_PAYLOAD + 16:
        raise ValueError('Archive exceeds the supported size.')
    staging = None
    try:
        with tempfile.NamedTemporaryFile(prefix='.archive-copy-',dir=destination,delete=False) as dst:
            staging = Path(dst.name)
            with archive.open('rb') as src:
                remaining = HEADER_SIZE + MAX_PAYLOAD + 16
                for block in iter(lambda: src.read(CHUNK),b''):
                    remaining -= len(block)
                    if remaining < 0:
                        raise ValueError('Archive exceeds the supported size.')
                    dst.write(block)
            dst.flush()
            os.fsync(dst.fileno())
        _decrypt_to(staging,password,lambda block: None,progress)
        if os.name == 'nt':
            staging.rename(output)
        else:
            os.link(staging,output)
        progress(100,'Destination archive authenticated')
        return {'kind':'verified_archive_copy','archive':str(output),'authentication':'PASS',
                'archive_bytes':output.stat().st_size,
                'placement':'User-selected destination. Physical separation and retention are operator-managed.'}
    finally:
        if staging is not None:
            staging.unlink(missing_ok=True)


def archive_drill(archive, destination, password, target_seconds, progress=lambda n,text:None):
    result = restore_encrypted(archive,destination,password,progress)
    result.update(kind='archive_drill', archive=str(archive), target_seconds=target_seconds,
                  target_met=result['restore_seconds'] <= target_seconds,
                  scope='Archive-only file restore and verification. Media placement and primary availability are recorded by the operator.')
    report = Path(destination)/('Archive-drill-'+uuid.uuid4().hex+'.json')
    try:
        with report.open('x',encoding='utf-8') as stream:
            json.dump(result,stream,indent=2)
        result['report_path'] = str(report)
    except OSError as exc:
        result['report_save_error'] = str(exc)
    return result
