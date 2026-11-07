from pathlib import Path
import json
import os
import struct
import tempfile
import unittest
from unittest.mock import patch
from cryptography.hazmat.primitives.ciphers import Cipher,algorithms,modes
import backup_engine as engine
import encrypted_backup as enc


PASSWORD = 'Test-only-passphrase-123!'


class EncryptedBackupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root/'source'
        self.source.mkdir()
        (self.source/'empty').mkdir()
        (self.source/'private-name.txt').write_text('Confidential sample message',encoding='utf-8')
        (self.source/'unicode-é.txt').write_bytes(bytes(range(256))*8192)
        self.vault = self.root/'backups'
        self.m = engine.create_backup(self.source,self.vault)
        self.snapshot = self.vault/self.m['id']
        self.archive = self.root/'protected.rvault'

    def export(self):
        return enc.export_encrypted(self.snapshot,self.archive,PASSWORD)

    def assert_no_restore(self,path=None,password=PASSWORD):
        destination = self.root/'recovered'
        with self.assertRaises((ValueError,OSError)):
            enc.restore_encrypted(path or self.archive,destination,password)
        self.assertFalse(destination.exists())

    def test_round_trip_binary_unicode_empty_directory_and_plaintext_visibility(self):
        report = self.export()
        self.assertEqual(report['authentication'],'PASS')
        raw = self.archive.read_bytes()
        self.assertNotIn(b'private-name.txt',raw)
        self.assertNotIn(b'Confidential sample message',raw)
        self.assertNotIn(str(self.source).encode(),raw)
        result = enc.restore_encrypted(self.archive,self.root/'recovered',PASSWORD)
        self.assertEqual(result['authentication'],'PASS')
        self.assertEqual(result['integrity'],'PASS')
        restored = Path(result['output'])
        for name in self.m['files']:
            self.assertEqual((restored/name).read_bytes(),(self.source/name).read_bytes())
        self.assertTrue((restored/'empty').is_dir())
        self.assertGreater(result['restore_seconds'],0)
        # Ordinary snapshots remain usable and are not silently encrypted/deleted.
        engine.verify_backup(self.snapshot)

    def test_wrong_password_publishes_nothing(self):
        self.export()
        self.assert_no_restore(password='wrong password')

    def test_ciphertext_header_nonce_and_tag_tampering_rejected(self):
        self.export()
        raw = self.archive.read_bytes()
        for offset in [8,24,enc.HEADER_SIZE+32,len(raw)-1]:
            with self.subTest(offset=offset):
                tampered = bytearray(raw)
                tampered[offset] ^= 1
                self.archive.write_bytes(tampered)
                self.assert_no_restore()

    def test_truncation_and_appending_rejected(self):
        self.export()
        raw = self.archive.read_bytes()
        for altered in [b'',raw[:51],raw[:-16],raw+b'extra']:
            self.archive.write_bytes(altered)
            self.assert_no_restore()

    def test_random_salt_and_nonce_produce_different_exports(self):
        self.export()
        other = self.root/'second.rvault'
        enc.export_encrypted(self.snapshot,other,PASSWORD)
        self.assertNotEqual(self.archive.read_bytes(),other.read_bytes())

    def test_existing_archive_is_preserved(self):
        self.archive.write_bytes(b'existing file')
        with self.assertRaises(ValueError):
            self.export()
        self.assertEqual(self.archive.read_bytes(),b'existing file')

    def test_export_rejects_source_location_and_short_password(self):
        with self.assertRaises(ValueError):
            enc.export_encrypted(self.snapshot,self.source/'out.rvault',PASSWORD)
        with self.assertRaises(ValueError):
            enc.export_encrypted(self.snapshot,self.archive,'short')
        self.assertFalse(self.archive.exists())

    def test_restores_are_unique_and_leave_existing_files(self):
        self.export()
        dest = self.root/'recovered'
        dest.mkdir()
        (dest/'keep.txt').write_bytes(b'keep')
        a = enc.restore_encrypted(self.archive,dest,PASSWORD)
        b = enc.restore_encrypted(self.archive,dest,PASSWORD)
        self.assertNotEqual(a['output'],b['output'])
        self.assertEqual((dest/'keep.txt').read_bytes(),b'keep')

    def forged_archive(self, manifest, contents=b''):
        raw = json.dumps(manifest).encode('utf-8')
        plaintext = struct.pack('<Q',len(raw))+raw+contents
        salt,nonce = os.urandom(16),os.urandom(12)
        header = enc.MAGIC+salt+nonce
        c = Cipher(algorithms.AES(enc._key(PASSWORD,salt)),modes.GCM(nonce)).encryptor()
        c.authenticate_additional_data(header)
        data = c.update(plaintext)+c.finalize()
        self.archive.write_bytes(header+data+c.tag)

    def test_authenticated_malicious_manifest_paths_rejected(self):
        for attack in ['identifier','filename']:
            m = json.loads(json.dumps(self.m))
            if attack == 'identifier':
                m['id'] = '../../escape'
            else:
                m['files']['../../escape'] = m['files'].pop('private-name.txt')
            self.forged_archive(m)
            self.assert_no_restore()
        self.assertFalse((self.root/'escape').exists())

    def test_authenticated_payload_length_mismatch_rejected(self):
        self.forged_archive(self.m,b'short')
        self.assert_no_restore()

    def test_hash_mismatch_cleans_partial_restoration(self):
        contents = b''.join((self.source/name).read_bytes() for name in sorted(self.m['files']))
        self.forged_archive(self.m,b'x'+contents[1:])
        destination = self.root/'recovered'
        with self.assertRaisesRegex(ValueError,'integrity'):
            enc.restore_encrypted(self.archive,destination,PASSWORD)
        self.assertEqual(list(destination.iterdir()),[])

    def test_snapshot_change_aborts_export_and_removes_partial(self):
        original = enc._key
        def change_after_verification(password,salt):
            (self.snapshot/'data'/'private-name.txt').write_text('changed snapshot')
            return original(password,salt)
        with patch('encrypted_backup._key',side_effect=change_after_verification):
            with self.assertRaisesRegex(ValueError,'changed'):
                self.export()
        self.assertFalse(self.archive.exists())
        self.assertEqual(list(self.root.glob('.encrypted-partial-*')),[])

    def test_restore_does_not_write_into_original_source(self):
        self.export()
        with self.assertRaises(ValueError):
            enc.restore_encrypted(self.archive,self.source,PASSWORD)
        self.assertEqual(len(list(self.source.iterdir())),3)


if __name__ == '__main__':
    unittest.main()
