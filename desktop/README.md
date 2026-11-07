# Recovery Vault — Windows desktop app

A real PySide6 application for local folder backups. This is separate from the
educational simulation and does not modify its code or the repository's main branch.

## Start

Extract the entire ZIP into a folder. Open that folder in VS Code, then run:

```powershell
$appEnvironment = Join-Path $env:LOCALAPPDATA 'RecoveryVault\venv'
& "C:\Program Files\Python315\python.exe" -m venv $appEnvironment
& "$appEnvironment\Scripts\python.exe" -m pip install -r requirements.txt
& "$appEnvironment\Scripts\python.exe" recovery_app.py
```

Alternatively run `./start.ps1` from PowerShell if your script policy permits it.
An Internet connection is required for the first dependency installation.
Do not open the app from inside the ZIP. The separate environment location avoids
Windows path-length problems with Qt when the project folder has a long name.
PySide6-Essentials is the official desktop subset of PySide6; an embedded web browser
is not needed by this app.

## Use

1. Choose a source folder and separate backup storage. Prefer an external drive
   so a single drive failure does not destroy both copies.
2. Click **Back up now**. The original files remain untouched. Every run creates
   an independent full snapshot, including empty folders and a SHA-256 manifest.
3. Select a backup to browse its files, verify its hashes, or export its manifest.
4. Click **Restore selected** and choose a separate destination. The app verifies
   the backup first and copies into a uniquely named new subfolder. It then verifies
   restored content. Existing files are never overwritten by restore.

Close apps editing the source before backup. A changed or unreadable file fails
the operation instead of reporting a successful incomplete backup. Failed staging
copies are removed; published earlier snapshots remain intact. Links and Windows
junctions are rejected. Keep the entire snapshot folder, including manifest.json
and data/, together. Partial folders are not shown in history.

## What is real

Files are copied on disk. Counts and payload sizes come from actual snapshots.
Copy time is elapsed wall-clock time for copying and verification, not a predicted
RTO. The chart shows file payload bytes, excluding filesystem/manifest overhead.
Verification rereads every listed file and checks SHA-256. It is an integrity check,
not proof against an attacker who can modify both files and manifests.

## Scope of this first version

Manual full folder snapshots, primary and optional secondary copies, history for
either storage destination, file browser, measured copy time, background workers,
progress, integrity verification, separate-folder restore, rule-based change review,
measured recovery tests, verified recovery-point recommendations and JSON reports.

No scheduled jobs, encryption, compression, incremental backups, cloud copies,
automatic retention/deletion, Volume Shadow Copy, open-database consistency or
system-image/bare-metal recovery. File content and basic copy2 metadata are copied;
Windows ACLs, alternate streams and application-specific consistency are not guaranteed.
A backup is a sequential copy, not an atomic filesystem snapshot: pause changing
data before running. Use a trusted backup drive and keep an additional off-site copy.
Do not manipulate source or destination links while an operation is running.

The app stores only the last source/storage paths in your Windows user settings.
Files are not uploaded. This is source code, not a packaged executable/installer.

## Validation

```powershell
& "$appEnvironment\Scripts\python.exe" -m unittest discover -v
```

Tests use disposable temporary folders, including real binary/text round trips,
independent versions, empty directories, corruption, path traversal, overlapping
folders and non-overwriting restores.

## Version 2: research and recovery evaluation

### Two backup destinations

Set a primary and optional secondary folder before clicking **Back up now**.
The source is copied to the primary folder and verified, then that same snapshot
is replicated to the secondary folder and verified again. Secondary failures are
reported explicitly; the successful primary snapshot is retained. Use the history
selector to browse, verify or restore from either destination.

Original + primary + secondary gives three logical copies. Two folders on one disk
do not establish independent media. Off-site placement must be arranged by the user,
for example with a suitably configured mounted remote storage destination. Copying
to a cloud-sync folder alone does not prove an off-site upload completed. There is
no cloud API, upload confirmation, geographic verification, immutability or encryption
in this version. Disconnect an external recovery copy safely after the operation if
your backup procedure requires offline storage. Never label this app ransomware-proof.

### Recovery targets and evidence

Choose a snapshot, configure a file-recovery time target (seconds) and a
recovery-point age target (minutes), then click **Run recovery test**. The app
performs a real restore into a unique new folder and saves a JSON report beside it.
The measured interval includes pre-restore integrity verification, file copying and
post-copy verification. Detection, operator response and service startup are excluded:
it is a file-recovery measurement, not complete business-service RTO compliance.

The recovery-point age uses the start of backup capture, compared with the test's
start time. This is a conservative age indicator for sequential file copying, not
a measured number of lost transactions or an application-consistent database RPO.
Older version-1 snapshots without capture-start metadata show an unknown age result.
A target miss does not mean the restore failed; integrity and target results are
reported separately. Individual files can be stable while a multi-file application
is inconsistent, so stop writers or use application-aware backup tools when needed.

### Change review and recovery-point review

The app compares new snapshots with the latest primary snapshot of the same source.
It reports added, changed and deleted files. With a baseline of at least five files,
30% or more changed/deleted triggers REVIEW. This is a rule-based heuristic, not AI,
a malware scan, or proof of an attack. Legitimate bulk migrations can trigger it.
No rule trigger does not mean data is clean. Each backup-plan result is saved under
primary-storage/.reports/, including partial success and the rule review.

**Find verified recovery point** checks snapshots newest-first and proposes the first
whose listed file hashes verify, skipping corrupted copies. A valid checksum cannot
establish that the content is desirable, uninfected or complete from a business
perspective: a new backup may faithfully preserve an accidental deletion. Review
dates, change reviews and application usability before restoring.

### Controlled study

**Run controlled study** creates a unique new subfolder beneath the destination you
choose. It generates test documents and a small student-record SQLite database, then
runs five scenarios: small edit, legitimate bulk edit, suspicious mass change,
accidental deletion, and a corrupted latest primary backup. Only generated test
files are changed or deleted. Your selected source and existing backups are untouched.

Each scenario creates and verifies two local backup copies, compares changes,
compares latest-only verification with newest-verified fallback, performs a real
restore and queries the restored student table read-only. Timings, integrity results,
service-query outcomes and rule true/false alerts are saved in study-report.json.
All study files remain in the unique study folder for inspection.

These fixtures illustrate the implementation; they do not establish general detector
accuracy, production recovery guarantees, off-site resilience, or AI effectiveness.
The student-record query is a narrow service-usability check, not a full university
application restart. AI evaluation still requires an actual model, labeled data and
a fair baseline. Encryption, protected/immutable storage, scheduling and full service
recovery remain outside the implemented scope.
