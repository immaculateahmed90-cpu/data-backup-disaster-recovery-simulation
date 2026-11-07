# CYB201: Data Backup and Disaster Recovery Simulation

Group 23 educational Python lab. Requires Python 3.10 or newer and only the
standard library. The missing original script was unavailable in the accessible
chat and repository; this is a replacement implementation.

## Run in Windows PowerShell

From the existing repository folder:

```powershell
git fetch origin
git switch setup/simulation-validation
git pull --ff-only origin setup/simulation-validation
& "C:\Program Files\Python315\python.exe" -m unittest discover -v
& "C:\Program Files\Python315\python.exe" group23_simulation_lab.py
```

If the branch has not been created locally, `git switch` normally creates it
from the uniquely matching remote branch. If needed, explicitly use
`git switch --track origin/setup/simulation-validation` instead.
If Git reports local changes or diverged history, keep those changes and resolve
them before continuing; these instructions do not require a reset or force pull.

## What the lab demonstrates

- Full backup: all files in a snapshot; recover from one set.
- Incremental: changes and deletions since the previous backup; recover from the
  full set and every subsequent incremental in order.
- Differential: changes and deletions since the full backup; recover from the
  full set and latest differential.
- A synthetic disaster at minute 150 clears an in-memory primary dataset.
  Backups at minute 120 recover that snapshot, losing the later unsaved file.
- SHA-256 manifests detect payload corruption and dependency checks reject
  missing or out-of-order recovery sets.

All data is synthetic and held in memory. No real files are backed up or deleted.
No packages, administrator privileges, or network access are needed to run it.
An integrity PASS means the reconstructed synthetic snapshot matches its manifest
and expected data. Hashes are integrity checks, not authentication or encryption.

## Interpreting results honestly

The displayed 30-minute data-loss window is a **modeled scenario outcome**, not a
measured RPO or a promised service objective. Restore seconds use the explicit
assumption `2 seconds per set + payload bytes / 1024 bytes per second`.
They are **modeled estimates, not measured RTO or performance benchmarks**.
Payload bytes count synthetic content in the selected recovery chain, excluding
metadata, compression, and historical backup retention. This is not disk usage.
Strategies share a final snapshot time so their recovery dependencies can be
compared; the exercise does not establish which strategy is fastest in production.

For a presentation, label these results "Simulation / modeled values". Real
recovery measurements would require timed disk restores in a documented test
environment. This lab does not implement a production backup system or 3-2-1
storage, off-site copies, encryption, scheduling, or ransomware protection.
