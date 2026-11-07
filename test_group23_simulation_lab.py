import unittest
from group23_simulation_lab import take_backup, restore, run_demo


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.initial = {'a': b'one', 'b': b'two'}
        self.full = take_backup(self.initial, 0)

    def test_full_is_independent_copy(self):
        self.initial.clear()
        self.assertEqual(restore([self.full]), {'a': b'one', 'b': b'two'})

    def test_incremental_handles_add_edit_delete_and_recreate(self):
        changed = {'a': b'edited', 'c': b'new'}
        first = take_backup(changed, 10, 'incremental', [self.full])
        self.assertEqual(first.deleted, ('b',))
        self.assertEqual(restore([self.full, first]), changed)
        changed['b'] = b'recreated'
        second = take_backup(changed, 20, 'incremental', [self.full, first])
        self.assertEqual(second.payload, {'b': b'recreated'})
        self.assertEqual(restore([self.full, first, second]), changed)

    def test_differential_restores_from_full_and_latest_only(self):
        take_backup({'a': b'intermediate'}, 10, 'differential', [self.full])
        latest = take_backup({'b': b'latest'}, 20, 'differential', [self.full])
        self.assertEqual(restore([self.full, latest]), {'b': b'latest'})

    def test_missing_or_reordered_dependency_fails(self):
        first = take_backup({'a': b'changed'}, 10, 'incremental', [self.full])
        second = take_backup({}, 20, 'incremental', [self.full, first])
        for chain in ([first], [self.full, second], [self.full, second, first], []):
            with self.assertRaises(ValueError):
                restore(chain)

    def test_corruption_fails(self):
        self.full.payload['a'] = b'corrupted'
        with self.assertRaisesRegex(ValueError, 'integrity'):
            restore([self.full])

    def test_empty_and_unchanged_snapshots(self):
        empty = take_backup({}, 0)
        self.assertEqual(restore([empty]), {})
        unchanged = take_backup(self.initial, 1, 'incremental', [self.full])
        self.assertEqual(unchanged.payload, {})
        self.assertEqual(restore([self.full, unchanged]), self.initial)

    def test_invalid_inputs(self):
        for kind in ('unknown', 'incremental', 'differential'):
            with self.assertRaises(ValueError):
                take_backup({}, 1, kind)
        with self.assertRaises(ValueError):
            take_backup({}, 0, 'incremental', [self.full])

    def test_demo_results(self):
        results = run_demo()
        self.assertEqual([r['restore_sets'] for r in results], [1, 3, 2])
        self.assertTrue(all(r['integrity'] == 'PASS' for r in results))
        self.assertTrue(all(r['modeled_data_loss_window_minutes'] == 30 for r in results))


if __name__ == '__main__':
    unittest.main()
