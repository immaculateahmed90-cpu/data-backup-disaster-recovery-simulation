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

Manual full folder snapshots, local history, file browser, measured copy time,
background workers, progress, integrity verification, separate-folder restore and
manifest export. No simulation or destructive disaster button.

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
