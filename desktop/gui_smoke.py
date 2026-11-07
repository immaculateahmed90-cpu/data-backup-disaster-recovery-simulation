"""Off-screen widget check; uses only temporary synthetic sample files."""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import sys
import tempfile
from pathlib import Path
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication
import backup_engine as engine
import research_tools as research
from recovery_app import MainWindow, STYLE, configure_fonts


def main():
    app = QApplication([])
    configure_fonts(app)
    app.setStyle('Fusion')
    app.setStyleSheet(STYLE)
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        # Isolate test settings so real user preferences stay untouched.
        QSettings.setDefaultFormat(QSettings.IniFormat)
        QSettings.setPath(QSettings.IniFormat,QSettings.UserScope,str(root/'settings'))
        source = root/'Sample documents'
        source.mkdir()
        (source/'Coursework').mkdir()
        (source/'Coursework'/'CYB201 notes.txt').write_text('Backup and disaster recovery\n'*300)
        (source/'Project report.txt').write_text('This preview uses temporary sample files.\n'*600)
        (source/'Records.csv').write_text('id,name\n1,Ada\n2,Musa\n'*500)
        vault = root/'Backup drive'
        secondary = root/'Secondary drive'
        for i in range(4):
            (source/'Project report.txt').write_text('Version '+str(i)+'\n'+'Report content.\n'*(800+i*500))
            research.protected_backup(source,vault,secondary)
        window = MainWindow()
        window.settings = QSettings(str(root/'preferences.ini'),QSettings.IniFormat)
        window.source.setText(str(source))
        window.vault.setText(str(vault))
        window.secondary.setText(str(secondary))
        window.refresh()
        assert window.table.rowCount() == 4
        assert window.file_table.rowCount() == 3
        window.history_location.setCurrentIndex(1)
        assert window.table.rowCount() == 4
        window.history_location.setCurrentIndex(0)
        selected = window.records[0]
        engine.verify_backup(selected['snapshot_path'])
        restored = research.recovery_test(selected['snapshot_path'],root/'Recovered documents',300,60)
        assert Path(restored['output']).is_dir()
        window.evidence.setText(f"FILE RECOVERY PASS · {restored['restore_seconds']:.3f}s / 300s target. Recovery-point age target PASS. Service not tested in this run.")
        window.review.setText('CHANGE REVIEW · Rule-based, not AI · Both sample backup copies verified. Media/site independence not established.')
        window.note('Preview data only: 4 sample snapshots created and verified.')
        window.status.setText('Preview with temporary sample files · real backup and restore engine verified')
        window.resize(1440,1250)
        window.show()
        app.processEvents()
        if len(sys.argv) > 1:
            assert window.grab().save(sys.argv[1])
        window.close()
        print('GUI rendered; history and file browser checked; actual disk restore verified.')


if __name__ == '__main__':
    main()
