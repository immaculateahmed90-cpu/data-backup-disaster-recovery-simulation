"""Measured file-recovery tests and transparent, rule-based change review."""
from datetime import datetime, timezone
from contextlib import closing
from pathlib import Path
import json
import shutil
import sqlite3
import time
import tempfile
import secrets
import uuid
import backup_engine as engine
from monitoring_study import model_study
import encrypted_backup as encrypted


def changes(previous, current):
    if previous is None:
        return {'status': 'NO BASELINE', 'alerts': [], 'added': len(current['files']),
                'changed': 0, 'deleted': 0, 'method': 'Rule-based; not AI'}
    a, b = previous['files'], current['files']
    added = len(b.keys()-a.keys())
    deleted = len(a.keys()-b.keys())
    changed = sum(a[k]['sha256'] != b[k]['sha256'] for k in a.keys() & b.keys())
    fraction = (deleted+changed)/max(1,len(a))
    alerts = []
    if len(a) >= 5 and fraction >= .3:
        alerts.append('At least 30% of baseline files changed or disappeared (baseline >= 5 files). Review before recovery.')
    return {'status': 'REVIEW' if alerts else 'NO RULE TRIGGERED', 'alerts': alerts,
            'added': added, 'changed': changed, 'deleted': deleted,
            'affected_fraction': fraction, 'method': 'Rule-based; not AI',
            'caution': 'An alert is not proof of attack. No alert does not establish clean data.'}


def replicate(snapshot, secondary, progress=lambda n, text: None):
    snapshot, secondary = engine.clean_path(snapshot), engine.clean_path(secondary)
    m = engine.verify_backup(snapshot)
    if engine.overlap(snapshot.parent, secondary) or engine.overlap(Path(m['source']).resolve(), secondary):
        raise ValueError('Secondary storage must be separate from source and primary backup storage.')
    secondary.mkdir(parents=True, exist_ok=True)
    target = secondary / snapshot.name
    if target.exists():
        raise ValueError('This snapshot already exists in secondary storage; choose it in history to verify it.')
    temp = secondary / ('.partial-' + uuid.uuid4().hex)
    try:
        temp.mkdir()
        (temp/'data').mkdir()
        for name in m.get('directories', []):
            (temp/'data'/engine.safe_relative(name)).mkdir(parents=True,exist_ok=True)
        for i,name in enumerate(m['files']):
            src = engine.clean_path(snapshot/'data'/engine.safe_relative(name))
            dst = temp/'data'/engine.safe_relative(name)
            dst.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(src,dst)
            progress(int((i+1)*80/max(1,len(m['files']))),name)
        (temp/'manifest.json').write_text(json.dumps(m,indent=2),encoding='utf-8')
        engine.verify_backup(temp)
        temp.rename(target)
        progress(100,'Secondary copy verified')
        return str(target)
    except Exception:
        if temp.exists():
            shutil.rmtree(temp)
        raise


def protected_backup(source, primary, secondary='', progress=lambda n,text:None):
    # Validate the entire plan before starting writes.
    paths = [engine.clean_path(x) for x in [source,primary,secondary] if x]
    for i,a in enumerate(paths):
        for b in paths[i+1:]:
            if engine.overlap(a,b):
                raise ValueError('Source and both backup destinations must be separate, non-overlapping folders.')
    baseline = next((m for m in engine.history(primary)
                     if Path(m['source']).resolve() == engine.clean_path(source)),None)
    m = engine.create_backup(source,primary,progress=progress)
    result = {'kind':'backup_plan','manifest':m,'primary':'VERIFIED',
              'primary_path':str(engine.clean_path(primary)/m['id']),
              'secondary':'NOT CONFIGURED','change_review':changes(baseline,m),
              'topology_note':'Two folder paths do not prove independent media or off-site placement.'}
    if secondary:
        try:
            result['secondary_path'] = replicate(result['primary_path'],secondary,progress)
            result['secondary'] = 'VERIFIED'
        except Exception as e:
            result['secondary'] = 'FAILED'
            result['secondary_error'] = str(e)
    report_dir = engine.clean_path(primary)/'.reports'
    try:
        report_dir = engine.clean_path(report_dir)
        report_dir.mkdir(exist_ok=True)
        report_path = report_dir/('Backup-'+m['id']+'.json')
        with report_path.open('x',encoding='utf-8') as f:
            json.dump(result,f,indent=2)
        result['report_path'] = str(report_path)
    except OSError as e:
        result['report_save_error'] = str(e)
    return result


def recovery_test(snapshot, destination, rto_seconds, rpo_minutes, progress=lambda n,text:None):
    if rto_seconds <= 0 or rpo_minutes < 0:
        raise ValueError('RTO must be positive; RPO must be nonnegative.')
    m = engine.read_manifest(snapshot)
    incident = datetime.now(timezone.utc)
    point = m.get('capture_started')
    if point:
        point = datetime.fromisoformat(point)
        if point.tzinfo is None or point > incident:
            raise ValueError('Invalid backup recovery-point timestamp.')
        age = (incident-point).total_seconds()
    else:
        age = None
    result = engine.restore_backup(snapshot,destination,progress=progress)
    report = {**result,'kind':'recovery_test','tested_at':incident.isoformat(),
              'rto_target_seconds':rto_seconds,
              'file_recovery_target_met':result['restore_seconds'] <= rto_seconds,
              'rpo_target_minutes':rpo_minutes,'recovery_point_age_seconds':age,
              'recovery_point_age_target_met': None if age is None else age <= rpo_minutes*60,
              'scope':'File recovery only. Time includes backup verification, copying, and restored-file verification. It excludes detection, staff response and service restart.',
              'rpo_note':'Snapshot age uses capture start. Sequential folder copying is not an application-consistent recovery point; actual lost transactions are not measured.',
              'business_service_status':'NOT TESTED'}
    path = Path(result['output']).parent / ('Recovery-test-'+uuid.uuid4().hex+'.json')
    try:
        with path.open('x',encoding='utf-8') as f:
            json.dump(report,f,indent=2)
        report['report_path'] = str(path)
    except OSError as e:
        report['report_save_error'] = str(e)
    return report


def recommend(vault, progress=lambda n,text:None):
    rejected = []
    for m in engine.history(vault):
        try:
            engine.verify_backup(m['snapshot_path'],progress)
            return {'kind':'recommendation','candidate':m['snapshot_path'],
                    'rejected':rejected,
                    'note':'Newest hash-verified snapshot. Not a malware scan or proof of application usability. Review change alerts before use.'}
        except (OSError,ValueError) as e:
            rejected.append({'snapshot':m['id'],'reason':str(e)})
    raise ValueError('No verifiable snapshot available in the selected storage.')


def controlled_study(destination, rto_seconds=300, rpo_minutes=60, progress=lambda n,text:None):
    """Run real operations on newly generated, disposable study files only."""
    destination = engine.clean_path(destination)
    destination.mkdir(parents=True,exist_ok=True)
    workspace = destination/('Recovery-study-'+uuid.uuid4().hex[:10])
    workspace.mkdir()
    trials = []
    scenarios = [('small_edit',False),('legitimate_bulk_edit',False),
                 ('suspicious_mass_change',True),('accidental_deletion',False),
                 ('corrupted_latest_backup',False)]
    for index,(scenario,suspicious) in enumerate(scenarios):
        trial = workspace/scenario
        source,primary,secondary = trial/'source',trial/'primary',trial/'secondary'
        source.mkdir(parents=True)
        for n in range(10):
            (source/f'record-{n}.txt').write_text(f'Original record {n}\n',encoding='utf-8')
        with closing(sqlite3.connect(source/'students.sqlite')) as db:
            db.execute('CREATE TABLE students (id INTEGER PRIMARY KEY, name TEXT)')
            db.executemany('INSERT INTO students VALUES (?,?)',[(1,'Ada'),(2,'Musa'),(3,'Grace')])
            db.commit()
        baseline = protected_backup(source,primary,secondary)
        if scenario == 'small_edit':
            (source/'record-0.txt').write_text('Normal edit',encoding='utf-8')
        elif scenario in ('legitimate_bulk_edit','suspicious_mass_change'):
            for n in range(6):
                (source/f'record-{n}.txt').write_text(
                    'Approved migration' if not suspicious else 'Synthetic suspicious content',encoding='utf-8')
        elif scenario == 'accidental_deletion':
            # Only deletes one generated study file, never selected user data.
            (source/'record-0.txt').unlink()
        latest = protected_backup(source,primary,secondary)
        review = latest['change_review']
        if scenario == 'corrupted_latest_backup':
            (Path(latest['primary_path'])/'data'/'record-0.txt').write_text('Deliberate test corruption',encoding='utf-8')
        manual_ok = True
        try:
            engine.verify_backup(latest['primary_path'])
        except (ValueError,OSError):
            manual_ok = False
        selected_at = time.perf_counter()
        recommendation = recommend(primary)
        selection_seconds = time.perf_counter()-selected_at
        result = recovery_test(recommendation['candidate'],trial/'restored',rto_seconds,rpo_minutes)
        restored = Path(result['output'])
        with closing(sqlite3.connect((restored/'students.sqlite').as_uri()+'?mode=ro',uri=True)) as db:
            records = db.execute('SELECT id,name FROM students ORDER BY id').fetchall()
        usable = records == [(1,'Ada'),(2,'Musa'),(3,'Grace')]
        if not usable:
            raise ValueError('Student-record query failed after recovery.')
        trials.append({'scenario':scenario,'synthetic_suspicious_label':suspicious,
                       'rule_alert':review['status']=='REVIEW',
                       'latest_only_integrity_pass':manual_ok,
                       'verified_fallback_integrity_pass':result['integrity']=='PASS',
                       'selection_workflow_seconds':selection_seconds,
                       'file_restore_seconds':result['restore_seconds'],
                       'student_record_query_pass':usable,'student_records':len(records),
                       'recovery_report':result['report_path'],
                       'note':'The accident trial backs up the deletion; a hash-valid latest snapshot is not necessarily the desired historical state.'})
        progress(int((index+1)*90/len(scenarios)),scenario)
    progress(95,'Testing encrypted recovery from the alternate copy')
    with tempfile.TemporaryDirectory() as recovery_fixture:
        fixture = Path(recovery_fixture)
        alternate = fixture/'alternate'
        alternate.mkdir()
        password = secrets.token_urlsafe(24)
        with tempfile.TemporaryDirectory(dir=fixture) as primary_fixture:
            local = Path(primary_fixture)
            sample = local/'source'
            sample.mkdir()
            (sample/'records.txt').write_text('Generated student record',encoding='utf-8')
            vault = local/'vault'
            snapshot = engine.create_backup(sample,vault)
            archive = local/'sample.rvault'
            encrypted.export_encrypted(vault/snapshot['id'],archive,password)
            copy = encrypted.copy_verified_archive(archive,alternate,password)
        drill = encrypted.archive_drill(copy['archive'],workspace,password,rto_seconds)
        assert (Path(drill['output'])/'records.txt').read_text(encoding='utf-8') == 'Generated student record'
        drill['fixture_note'] = 'Generated primary and source were removed before restore. Alternate storage was local test media.'
    report = {'kind':'controlled_study','workspace':str(workspace),'trials':trials,
              'monitoring_experiment':model_study(),
              'encrypted_recovery_drill':drill,
              'rule_true_positives':sum(t['rule_alert'] and t['synthetic_suspicious_label'] for t in trials),
              'rule_false_positives':sum(t['rule_alert'] and not t['synthetic_suspicious_label'] for t in trials),
              'service_query_passes':sum(t['student_record_query_pass'] for t in trials),
              'limitations':['Generated fixtures only; not a production benchmark or trained AI evaluation.',
                             'Rule-based change-count threshold cannot distinguish legitimate bulk changes from attacks.',
                             'All study copies are local folders; this study does not establish 3-2-1 media/site independence.',
                             'Service check is a read-only SQLite query; it does not prove full university service recovery.',
                             'Latest-only verification versus verified fallback is a policy comparison, not a human-effort measurement.']}
    path = workspace/'study-report.json'
    path.write_text(json.dumps(report,indent=2),encoding='utf-8')
    report['report_path'] = str(path)
    progress(100,'Study complete')
    return report
