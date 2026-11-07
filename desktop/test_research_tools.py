from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch
import backup_engine as engine
import research_tools as research


class ResearchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root/'source'
        self.source.mkdir()
        for i in range(10):
            (self.source/f'{i}.txt').write_text('original')
        self.primary,self.secondary = self.root/'primary',self.root/'secondary'

    def plan(self):
        return research.protected_backup(self.source,self.primary,self.secondary)

    def test_two_verified_identical_copies(self):
        r = self.plan()
        self.assertEqual(r['secondary'],'VERIFIED')
        a,b = engine.verify_backup(r['primary_path']),engine.verify_backup(r['secondary_path'])
        self.assertEqual(a,b)
        result = engine.restore_backup(r['secondary_path'],self.root/'restored')
        self.assertEqual(result['files'],10)

    def test_secondary_failure_retains_primary_and_is_reported(self):
        with patch('research_tools.replicate',side_effect=OSError('drive unavailable')):
            r = self.plan()
        self.assertEqual(r['secondary'],'FAILED')
        self.assertEqual(len(engine.verify_backup(r['primary_path'])['files']),10)

    def test_overlap_rejected_before_write(self):
        with self.assertRaises(ValueError):
            research.protected_backup(self.source,self.primary,self.primary/'nested')
        self.assertFalse(self.primary.exists())

    def test_rule_based_alert_and_normal_change(self):
        self.plan()
        (self.source/'0.txt').write_text('normal small change')
        self.assertEqual(self.plan()['change_review']['status'],'NO RULE TRIGGERED')
        for i in range(4):
            (self.source/f'{i}.txt').write_text('mass change')
        review = self.plan()['change_review']
        self.assertEqual(review['status'],'REVIEW')
        self.assertEqual(review['changed'],4)

    def test_actual_recovery_test_and_saved_report(self):
        r = self.plan()
        result = research.recovery_test(r['primary_path'],self.root/'restored',3600,60)
        self.assertTrue(result['file_recovery_target_met'])
        self.assertTrue(result['recovery_point_age_target_met'])
        self.assertGreater(result['restore_seconds'],0)
        self.assertEqual(result['business_service_status'],'NOT TESTED')
        self.assertEqual(json.loads(Path(result['report_path']).read_text())['integrity'],'PASS')

    def test_old_backup_age_misses_target(self):
        r = self.plan()
        p = Path(r['primary_path'])/'manifest.json'
        m = json.loads(p.read_text())
        m['capture_started'] = '2020-01-01T00:00:00+00:00'
        p.write_text(json.dumps(m))
        result = research.recovery_test(r['primary_path'],self.root/'restored',3600,1)
        self.assertFalse(result['recovery_point_age_target_met'])

    def test_legacy_recovery_point_is_unknown(self):
        r = self.plan()
        p = Path(r['primary_path'])/'manifest.json'
        m = json.loads(p.read_text())
        del m['capture_started']
        p.write_text(json.dumps(m))
        result = research.recovery_test(r['primary_path'],self.root/'restored',3600,1)
        self.assertIsNone(result['recovery_point_age_target_met'])

    def test_recommend_skips_corrupted_snapshot(self):
        first,second = self.plan(),self.plan()
        (Path(second['primary_path'])/'data'/'0.txt').write_text('bad')
        result = research.recommend(self.primary)
        self.assertEqual(result['candidate'],first['primary_path'])
        self.assertEqual(len(result['rejected']),1)

    def test_duplicate_replica_does_not_overwrite(self):
        r = self.plan()
        with self.assertRaises(ValueError):
            research.replicate(r['primary_path'],self.secondary)
        engine.verify_backup(r['secondary_path'])

    def test_controlled_study_runs_real_restores_and_reports_false_alerts(self):
        result = research.controlled_study(self.root/'study-output')
        self.assertEqual(result['service_query_passes'],5)
        self.assertEqual(result['rule_true_positives'],1)
        self.assertEqual(result['rule_false_positives'],1)
        corruption = next(t for t in result['trials'] if t['scenario']=='corrupted_latest_backup')
        self.assertFalse(corruption['latest_only_integrity_pass'])
        self.assertTrue(corruption['verified_fallback_integrity_pass'])
        self.assertTrue(Path(result['report_path']).is_file())

    def test_recovery_duration_target_can_fail(self):
        r = self.plan()
        report = research.recovery_test(r['primary_path'],self.root/'restore',.000001,60)
        self.assertFalse(report['file_recovery_target_met'])


if __name__ == '__main__':
    unittest.main()
