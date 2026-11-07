import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import backup_engine as e


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root/'source'
        self.source.mkdir()
        (self.source/'nested').mkdir()
        (self.source/'empty').mkdir()
        (self.source/'nested'/'hello.txt').write_text('Hello, recovery!')
        (self.source/'binary.bin').write_bytes(bytes(range(256)))
        self.vault = self.root/'vault'

    def backup(self):
        m = e.create_backup(self.source,self.vault)
        return self.vault/m['id']

    def test_real_round_trip_preserves_files_and_empty_directories(self):
        snapshot = self.backup()
        (self.source/'binary.bin').unlink()
        result = e.restore_backup(snapshot,self.root/'restore')
        restored = Path(result['output'])
        self.assertEqual((restored/'binary.bin').read_bytes(),bytes(range(256)))
        self.assertTrue((restored/'empty').is_dir())
        self.assertEqual((restored/'nested'/'hello.txt').read_text(),'Hello, recovery!')

    def test_versions_are_independent(self):
        first = self.backup()
        (self.source/'binary.bin').write_bytes(b'updated')
        second = self.backup()
        self.assertEqual((first/'data'/'binary.bin').read_bytes(),bytes(range(256)))
        self.assertEqual((second/'data'/'binary.bin').read_bytes(),b'updated')
        self.assertEqual(len(e.history(self.vault)),2)

    def test_corruption_blocks_restore(self):
        p = self.backup()
        (p/'data'/'binary.bin').write_bytes(b'corrupt')
        with self.assertRaisesRegex(ValueError,'Integrity'):
            e.restore_backup(p,self.root/'restore')
        self.assertFalse((self.root/'restore').exists())

    def test_restore_never_overwrites_existing_files(self):
        p = self.backup()
        dest = self.root/'restore'
        dest.mkdir()
        (dest/'binary.bin').write_bytes(b'keep')
        a = e.restore_backup(p,dest)
        b = e.restore_backup(p,dest)
        self.assertNotEqual(a['output'],b['output'])
        self.assertEqual((dest/'binary.bin').read_bytes(),b'keep')

    def test_overlap_rejected(self):
        for vault in [self.source,self.source/'backups',self.root]:
            with self.assertRaises(ValueError):
                e.create_backup(self.source,vault)
        p = self.backup()
        for dest in [self.source,self.vault,self.source/'restore']:
            with self.assertRaises(ValueError):
                e.restore_backup(p,dest)

    def test_manifest_traversal_rejected(self):
        p = self.backup()
        path = p/'manifest.json'
        m = json.loads(path.read_text())
        m['files']['../../escape'] = next(iter(m['files'].values()))
        path.write_text(json.dumps(m))
        with self.assertRaises(ValueError):
            e.restore_backup(p,self.root/'restore')

    def test_manifest_identifier_traversal_rejected(self):
        p = self.backup()
        path = p/'manifest.json'
        m = json.loads(path.read_text())
        m['id'] = '../../escape'
        path.write_text(json.dumps(m))
        with self.assertRaises(ValueError):
            e.restore_backup(p,self.root/'restore')

    def test_unsafe_windows_paths(self):
        for value in ['../a','C:/a','a\\b','/a','a:stream','CON','a/../b','a.']:
            with self.assertRaises(ValueError):
                e.safe_relative(value)

    def test_empty_source(self):
        empty = self.root/'empty-source'
        empty.mkdir()
        m = e.create_backup(empty,self.vault)
        self.assertEqual(e.verify_backup(self.vault/m['id'])['files'],{})

    def test_failed_copy_does_not_publish_partial_backup(self):
        with patch('backup_engine.shutil.copy2',side_effect=PermissionError('locked')):
            with self.assertRaises(PermissionError):
                self.backup()
        self.assertEqual(list(self.vault.iterdir()),[])

    def test_source_change_during_copy_fails(self):
        original_copy = e.shutil.copy2
        def changing_copy(src,dst):
            original_copy(src,dst)
            src.write_bytes(b'changed during backup')
        with patch('backup_engine.shutil.copy2',side_effect=changing_copy):
            with self.assertRaisesRegex(ValueError,'changed'):
                self.backup()
        self.assertEqual(list(self.vault.iterdir()),[])


if __name__ == '__main__':
    unittest.main()
