"""Recovery Vault: a real PySide6 folder-backup desktop application."""
import json
import sys
from datetime import datetime
from pathlib import Path
from PySide6.QtCore import Qt, QThread, Signal, QUrl, QSettings
from PySide6.QtGui import QColor, QPainter, QPen, QDesktopServices, QFontDatabase, QFont
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QLabel, QPushButton,
    QHBoxLayout, QVBoxLayout, QGridLayout, QFrame, QLineEdit, QFileDialog,
    QTableWidget, QTableWidgetItem, QHeaderView, QProgressBar, QMessageBox,
    QAbstractItemView, QSplitter, QTextEdit, QSpinBox, QComboBox, QScrollArea,
    QInputDialog, QDialog)
import backup_engine as engine
import research_tools as research
import encrypted_backup as encrypted


def size(n):
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if n < 1024 or unit == 'TB':
            return f'{n:,.1f} {unit}'
        n /= 1024


class Worker(QThread):
    progress = Signal(int, str)
    result = Signal(object)
    error = Signal(str)

    def __init__(self, fn, args):
        super().__init__()
        self.fn, self.args = fn, args

    def run(self):
        try:
            self.result.emit(self.fn(*self.args, progress=self.progress.emit))
        except Exception as exc:
            self.error.emit(str(exc))
        finally:
            # Do not retain password arguments on the completed worker object.
            self.args = ()
            self.fn = None


class StorageChart(QWidget):
    def __init__(self):
        super().__init__()
        self.records = []
        self.setMinimumHeight(155)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        p.setPen(QColor('#7f939d'))
        if not self.records:
            p.drawText(self.rect(), Qt.AlignCenter, 'Your backup activity will appear here')
            return
        values = [r['bytes'] for r in self.records[-10:]]
        step = (w-20)/len(values)
        for i, value in enumerate(values):
            bar = max(4, (h-40)*value/max(1,max(values)))
            p.setBrush(QColor('#5de0b0' if i == len(values)-1 else '#294d59'))
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(int(10+i*step), int(h-25-bar), int(max(4,step-12)), int(bar), 5, 5)
            p.setPen(QColor('#8aa1ab'))
            p.drawText(int(10+i*step), h-7, str(i+1))


class VaultArt(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedSize(210, 115)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor('#31515e'), 1, Qt.DashLine))
        p.drawEllipse(15, 10, 175, 95)
        for y in [21, 47, 73]:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor('#274652'))
            p.drawRoundedRect(55, y, 100, 20, 5, 5)
            p.setBrush(QColor('#5de0b0'))
            p.drawEllipse(66, y+7, 5, 5)
            p.setPen(QColor('#8db2bf'))
            p.drawLine(120, y+10, 142, y+10)
        p.setBrush(QColor('#5de0b0'))
        p.setPen(Qt.NoPen)
        p.drawEllipse(135, 65, 39, 39)
        p.setPen(QPen(QColor('#12392f'), 3))
        p.drawLine(145, 84, 152, 91)
        p.drawLine(152, 91, 164, 77)


def card():
    f = QFrame()
    f.setObjectName('card')
    return f


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('Recovery Vault — Real File Backup')
        self.resize(1220, 900)
        self.setMinimumSize(980, 740)
        self.settings = QSettings('CYB201', 'RecoveryVault')
        self.records = []
        self.worker = None
        self.last_result = None
        self.buttons = []
        root = QWidget()
        self.setCentralWidget(root)
        page = QHBoxLayout(root)
        page.setContentsMargins(0,0,0,0)
        sidebar = QFrame()
        sidebar.setObjectName('sidebar')
        sidebar.setFixedWidth(190)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(24,30,20,24)
        logo = QLabel('◈  Recovery\n    Vault')
        logo.setObjectName('logo')
        side.addWidget(logo)
        side.addWidget(QLabel('CYB201  /  GROUP 23'))
        side.addSpacing(32)
        side.addWidget(QLabel('▦   Backup dashboard'))
        side.addSpacing(18)
        side.addWidget(QLabel('◷   Versioned snapshots'))
        side.addSpacing(18)
        side.addWidget(QLabel('✓   Integrity protection'))
        side.addStretch()
        tip = QLabel('LOCAL FILE BACKUP\n\nYour files stay on the\ndrives you choose.\n\nFull snapshots · SHA-256')
        tip.setWordWrap(True)
        side.addWidget(tip)
        page.addWidget(sidebar)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(28,22,28,20)
        layout.setSpacing(14)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)
        content.setMinimumHeight(1240)
        page.addWidget(scroll)
        hero = QHBoxLayout()
        text = QVBoxLayout()
        text.addWidget(QLabel('PROTECT WHAT MATTERS'))
        title = QLabel('Your files. A way back.')
        title.setObjectName('title')
        text.addWidget(title)
        text.addWidget(QLabel('Back up real folders. Verify every copy. Recover with confidence.'))
        hero.addLayout(text)
        hero.addStretch()
        hero.addWidget(VaultArt())
        layout.addLayout(hero)
        metrics = QHBoxLayout()
        self.values = []
        for label, initial in [('SNAPSHOTS','0'),('FILES IN LATEST','0'),('STORED PAYLOAD','0 B'),('LAST BACKUP','—')]:
            c = card()
            v = QVBoxLayout(c)
            v.addWidget(QLabel(label))
            value = QLabel(initial)
            value.setObjectName('metric')
            self.values.append(value)
            v.addWidget(value)
            metrics.addWidget(c)
        layout.addLayout(metrics)
        config = card()
        grid = QGridLayout(config)
        grid.addWidget(QLabel('BACKUP PLAN  ·  Full folder snapshots'),0,0,1,3)
        self.source = QLineEdit(self.settings.value('source',''))
        self.source.setPlaceholderText('Choose the folder you want to protect')
        self.vault = QLineEdit(self.settings.value('vault',''))
        self.vault.setPlaceholderText('Choose backup storage, preferably on another drive')
        self.secondary = QLineEdit(self.settings.value('secondary',''))
        self.secondary.setPlaceholderText('Optional: separate drive or mounted off-site destination')
        for row, name, edit in [(1,'Source folder',self.source),(2,'Primary backup',self.vault),
                                (3,'Secondary copy',self.secondary)]:
            grid.addWidget(QLabel(name),row,0)
            grid.addWidget(edit,row,1)
            grid.addWidget(self.button('Browse…',lambda checked=False,e=edit:self.browse(e)),row,2)
        actions = QHBoxLayout()
        b = self.button('＋  Back up now',self.backup)
        b.setObjectName('primary')
        actions.addWidget(b)
        actions.addWidget(self.button('↻  Refresh history',self.refresh))
        actions.addStretch()
        actions.addWidget(QLabel('Original files are never deleted'))
        grid.addLayout(actions,4,0,1,3)
        topology = QLabel('3-copy plan: original → primary → secondary. Independent media, off-site location and offline/immutable protection must be arranged separately; folder paths cannot prove them.')
        topology.setWordWrap(True)
        grid.addWidget(topology,5,0,1,3)
        layout.addWidget(config)
        security = card()
        sec = QVBoxLayout(security)
        sec.addWidget(QLabel('ENCRYPTED RECOVERY COPY  ·  AES-256-GCM'))
        self.security_status = QLabel('Folder backups remain unencrypted. Encrypted exports support up to 32 GiB per archive. Passwords are not saved and cannot be reset.')
        self.security_status.setWordWrap(True)
        sec.addWidget(self.security_status)
        secure_actions = QHBoxLayout()
        self.encrypt_button = self.button('Export selected as encrypted archive',self.encrypt_selected)
        self.decrypt_button = self.button('Restore encrypted archive',self.decrypt_archive)
        secure_actions.addWidget(self.encrypt_button)
        secure_actions.addWidget(self.decrypt_button)
        sec.addLayout(secure_actions)
        layout.addWidget(security)
        evaluation = card()
        ev = QGridLayout(evaluation)
        ev.addWidget(QLabel('RECOVERY EVALUATION  ·  File-level targets'),0,0,1,4)
        self.rto = QSpinBox()
        self.rto.setRange(1,86400)
        self.rto.setValue(int(self.settings.value('rto',300)))
        self.rto.setSuffix(' seconds')
        self.rpo = QSpinBox()
        self.rpo.setRange(0,525600)
        self.rpo.setValue(int(self.settings.value('rpo',60)))
        self.rpo.setSuffix(' minutes')
        ev.addWidget(QLabel('File-recovery time target'),1,0)
        ev.addWidget(self.rto,1,1)
        ev.addWidget(QLabel('Recovery-point age target'),1,2)
        ev.addWidget(self.rpo,1,3)
        self.evidence = QLabel('No recovery test yet. Actual lost transactions and business-service recovery are not measured.')
        self.evidence.setWordWrap(True)
        ev.addWidget(self.evidence,2,0,1,4)
        self.review = QLabel('CHANGE REVIEW  ·  Rule-based, not AI. No baseline yet.')
        self.review.setWordWrap(True)
        ev.addWidget(self.review,3,0,1,4)
        er = QHBoxLayout()
        er.addWidget(self.button('Run recovery test',self.test_recovery))
        er.addWidget(self.button('Find verified recovery point',self.recommend))
        er.addWidget(self.button('Export latest result',self.export_result))
        er.addWidget(self.button('Run controlled study',self.study))
        ev.addLayout(er,4,0,1,4)
        layout.addWidget(evaluation)
        middle = QSplitter(Qt.Horizontal)
        history_card = card()
        hl = QVBoxLayout(history_card)
        hl.addWidget(QLabel('BACKUP HISTORY  ·  Select a snapshot'))
        self.history_location = QComboBox()
        self.history_location.addItems(['Primary storage','Secondary storage'])
        self.history_location.currentIndexChanged.connect(self.refresh)
        hl.addWidget(self.history_location)
        self.table = QTableWidget(0,4)
        self.table.setHorizontalHeaderLabels(['Created (local)','Files','Payload','Copy time'])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().hide()
        self.table.itemSelectionChanged.connect(self.show_files)
        hl.addWidget(self.table)
        row = QHBoxLayout()
        row.addWidget(self.button('✓  Verify selected',self.verify))
        row.addWidget(self.button('↗  Restore selected',self.restore))
        row.addWidget(self.button('Export manifest',self.export))
        hl.addLayout(row)
        middle.addWidget(history_card)
        graph_card = card()
        gl = QVBoxLayout(graph_card)
        gl.addWidget(QLabel('SNAPSHOT PAYLOAD'))
        self.chart = StorageChart()
        gl.addWidget(self.chart)
        gl.addWidget(QLabel('Actual file bytes · last 10 snapshots'))
        middle.addWidget(graph_card)
        middle.setSizes([650,260])
        layout.addWidget(middle,3)
        lower = QSplitter(Qt.Horizontal)
        file_card = card()
        fl = QVBoxLayout(file_card)
        self.file_title = QLabel('FILES IN SELECTED SNAPSHOT')
        fl.addWidget(self.file_title)
        self.file_table = QTableWidget(0,2)
        self.file_table.setHorizontalHeaderLabels(['File path','Size'])
        self.file_table.horizontalHeader().setSectionResizeMode(0,QHeaderView.Stretch)
        self.file_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.file_table.verticalHeader().hide()
        fl.addWidget(self.file_table)
        lower.addWidget(file_card)
        activity_card = card()
        al = QVBoxLayout(activity_card)
        al.addWidget(QLabel('ACTIVITY & RESULTS'))
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        al.addWidget(self.log)
        lower.addWidget(activity_card)
        lower.setSizes([550,360])
        layout.addWidget(lower,2)
        self.progress = QProgressBar()
        self.progress.setValue(0)
        self.progress.setFixedHeight(9)
        self.progress.setTextVisible(False)
        layout.addWidget(self.progress)
        self.status = QLabel('Ready · Choose a source folder and backup storage to begin.')
        layout.addWidget(self.status)
        self.note('Ready. Real file backups; restore always creates a new folder.')
        self.refresh()

    def button(self, title, fn):
        b = QPushButton(title)
        b.clicked.connect(fn)
        self.buttons.append(b)
        return b

    def note(self, message):
        self.log.moveCursor(self.log.textCursor().MoveOperation.End)
        self.log.insertPlainText(datetime.now().strftime('%H:%M:%S')+'  '+message+'\n')

    def browse(self, edit):
        p = QFileDialog.getExistingDirectory(self,'Choose folder',edit.text())
        if p:
            edit.setText(p)
            if edit in (self.vault,self.secondary):
                self.refresh()

    def selected(self):
        row = self.table.currentRow()
        if row < 0 or row >= len(self.records):
            QMessageBox.information(self,'Select a snapshot','Select a backup in the history table first.')
            return None
        return self.records[row]

    def refresh(self):
        self.records = []
        storage = self.vault if self.history_location.currentIndex() == 0 else self.secondary
        if storage.text().strip():
            try:
                self.records = engine.history(storage.text().strip())
            except Exception as e:
                self.note('Could not read backup history: '+str(e))
        self.table.setRowCount(len(self.records))
        for row, r in enumerate(self.records):
            values = [datetime.fromisoformat(r['created']).astimezone().strftime('%d %b %Y %H:%M:%S'),
                      str(len(r['files'])),size(r['bytes']),str(r['duration_seconds'])+' s']
            for col, value in enumerate(values):
                self.table.setItem(row,col,QTableWidgetItem(value))
        self.values[0].setText(str(len(self.records)))
        self.values[1].setText(str(len(self.records[0]['files'])) if self.records else '0')
        self.values[2].setText(size(sum(r['bytes'] for r in self.records)))
        self.values[3].setText(datetime.fromisoformat(self.records[0]['created']).astimezone().strftime('%H:%M · %d %b') if self.records else '—')
        self.chart.records = list(reversed(self.records))
        self.chart.update()
        self.file_table.setRowCount(0)
        if self.records:
            self.table.selectRow(0)
            self.show_files()

    def show_files(self):
        row = self.table.currentRow()
        if row < 0 or row >= len(self.records):
            return
        files = self.records[row]['files']
        self.file_table.setRowCount(len(files))
        for i,(name,meta) in enumerate(sorted(files.items())):
            self.file_table.setItem(i,0,QTableWidgetItem(name))
            self.file_table.setItem(i,1,QTableWidgetItem(size(meta['size'])))
        selected = self.records[row]
        report_path = Path(selected['snapshot_path']).parent/'.reports'/('Backup-'+selected['id']+'.json')
        try:
            report = json.loads(engine.clean_path(report_path).read_text(encoding='utf-8'))
            c = report['change_review']
            self.review.setText(f"CHANGE REVIEW · {c['status']} · Added {c['added']}, changed {c['changed']}, deleted {c['deleted']}. Rule-based, not AI.")
        except (OSError,ValueError,KeyError,TypeError):
            self.review.setText('CHANGE REVIEW · No saved review for this copy. Integrity verification is not a malware scan.')

    def launch(self, title, fn, args):
        self.operation = title
        self.progress.setValue(0)
        self.status.setText(title+'…')
        self.note(title+' started.')
        for b in self.buttons:
            b.setEnabled(False)
        self.source.setEnabled(False)
        self.vault.setEnabled(False)
        self.secondary.setEnabled(False)
        self.history_location.setEnabled(False)
        self.rto.setEnabled(False)
        self.rpo.setEnabled(False)
        self.table.setEnabled(False)
        self.worker = Worker(fn,args)
        self.worker.progress.connect(self.on_progress)
        self.worker.result.connect(self.done)
        self.worker.error.connect(self.failed)
        self.worker.finished.connect(self.unbusy)
        self.worker.start()

    def on_progress(self, number, message):
        self.progress.setValue(number)
        self.status.setText(self.operation+' · '+message)

    def unbusy(self):
        for b in self.buttons:
            b.setEnabled(True)
        self.source.setEnabled(True)
        self.vault.setEnabled(True)
        self.secondary.setEnabled(True)
        self.history_location.setEnabled(True)
        self.rto.setEnabled(True)
        self.rpo.setEnabled(True)
        self.table.setEnabled(True)

    def backup(self):
        if not self.source.text().strip() or not self.vault.text().strip():
            QMessageBox.information(self,'Choose folders','Choose both a source folder and backup storage.')
            return
        self.settings.setValue('source',self.source.text().strip())
        self.settings.setValue('vault',self.vault.text().strip())
        self.settings.setValue('secondary',self.secondary.text().strip())
        self.launch('Backup',research.protected_backup,(self.source.text().strip(),self.vault.text().strip(),self.secondary.text().strip()))

    def test_recovery(self):
        r = self.selected()
        if not r:
            return
        destination = QFileDialog.getExistingDirectory(self,'Choose recovery-test destination — files will be restored to a new subfolder')
        if destination:
            self.settings.setValue('rto',self.rto.value())
            self.settings.setValue('rpo',self.rpo.value())
            self.launch('Recovery test',research.recovery_test,(r['snapshot_path'],destination,self.rto.value(),self.rpo.value()))

    def password_prompt(self, confirm=False):
        def ask(label):
            dialog = QInputDialog(self)
            dialog.setWindowTitle('Encrypted backup password')
            dialog.setLabelText(label)
            dialog.setTextEchoMode(QLineEdit.Password)
            ok = dialog.exec() == QDialog.Accepted
            value = dialog.textValue() if ok else None
            dialog.setTextValue('')
            dialog.deleteLater()
            return value
        password = ask('Use a long, unique passphrase (at least 12 characters).\nKeep it safely: there is no password reset.' if confirm else 'Enter the archive password.\nWrong passwords and damaged archives cannot be restored.')
        if password is None:
            return None
        if confirm and (len(password)<12 or len(password.encode('utf-8'))>1024):
            QMessageBox.information(self,'Password length','Use at least 12 characters and no more than 1024 UTF-8 bytes.')
            return None
        if confirm:
            repeated = ask('Re-enter the same passphrase to confirm.')
            if repeated is None:
                return None
            if password != repeated:
                QMessageBox.information(self,'Passwords differ','Passwords did not match. No archive was created.')
                return None
        return password

    def encrypt_selected(self):
        r = self.selected()
        if not r:
            return
        path,_ = QFileDialog.getSaveFileName(self,'Save encrypted recovery copy — choose a new filename',r['id']+'.rvault','Recovery Vault encrypted (*.rvault)')
        if not path:
            return
        if Path(path).exists():
            QMessageBox.information(self,'Choose a new filename','Existing files are never overwritten by encrypted export.')
            return
        password = self.password_prompt(confirm=True)
        if password is not None:
            self.launch('Encrypted export',encrypted.export_encrypted,(r['snapshot_path'],path,password))

    def decrypt_archive(self):
        path,_ = QFileDialog.getOpenFileName(self,'Choose encrypted recovery archive','','Recovery Vault encrypted (*.rvault);;All files (*)')
        if not path:
            return
        destination = QFileDialog.getExistingDirectory(self,'Choose restore destination — a new subfolder will be created')
        if not destination:
            return
        password = self.password_prompt()
        if password is not None:
            self.launch('Encrypted restore',encrypted.restore_encrypted,(path,destination,password))

    def recommend(self):
        storage = self.vault if self.history_location.currentIndex() == 0 else self.secondary
        if not storage.text().strip():
            QMessageBox.information(self,'Choose storage','Choose the storage folder first.')
            return
        self.launch('Recovery-point review',research.recommend,(storage.text().strip(),))

    def study(self):
        destination = QFileDialog.getExistingDirectory(self,'Choose report folder — study creates and changes only new sample files in its own subfolder')
        if destination:
            self.launch('Controlled study',research.controlled_study,(destination,self.rto.value(),self.rpo.value()))

    def export_result(self):
        if self.last_result is None:
            QMessageBox.information(self,'No result','Run a backup, verification or recovery test first.')
            return
        path,_ = QFileDialog.getSaveFileName(self,'Export latest measured result','recovery-result.json','JSON (*.json)')
        if path:
            try:
                Path(path).write_text(json.dumps(self.last_result,indent=2),encoding='utf-8')
                self.note('Result exported to '+path)
            except OSError as e:
                QMessageBox.warning(self,'Export failed',str(e))

    def verify(self):
        r = self.selected()
        if r:
            self.launch('Verification',engine.verify_backup,(r['snapshot_path'],))

    def restore(self):
        r = self.selected()
        if not r:
            return
        destination = QFileDialog.getExistingDirectory(self,'Choose restore destination — a new subfolder will be created')
        if destination:
            self.launch('Restore',engine.restore_backup,(r['snapshot_path'],destination))

    def done(self, result):
        self.last_result = result
        self.progress.setValue(100)
        message = self.operation+' complete. All copied file hashes verified.'
        if result.get('kind') == 'encrypted_export':
            message = f"Encrypted archive created and authenticated: {result['archive']}"
            self.security_status.setText('ARCHIVE VERIFIED · AES-256-GCM · '+size(result['archive_bytes'])+'. Folder backups remain unencrypted.')
        elif result.get('kind') == 'controlled_study':
            message = f"Controlled study complete: {result['service_query_passes']}/5 student-record queries passed after real restoration. Rule false alerts: {result['rule_false_positives']}."
            self.evidence.setText(message+' Generated fixtures; not AI or production results.')
            self.note('Study report: '+result['report_path'])
        elif result.get('kind') == 'backup_plan':
            m = result['manifest']
            message = f"Primary backup VERIFIED. Secondary: {result['secondary']}. {len(m['files'])} files; {size(m['bytes'])}."
            c = result['change_review']
            self.review.setText(f"CHANGE REVIEW · {c['status']} · Added {c['added']}, changed {c['changed']}, deleted {c['deleted']}. Rule-based, not AI.")
            for alert in c['alerts']:
                self.note(alert)
            if result['secondary'] == 'FAILED':
                self.note('Secondary failed; primary retained: '+result['secondary_error'])
            self.evidence.setText(message+' Media independence and off-site placement are not verified by the app.')
        elif result.get('kind') == 'recommendation':
            message = 'Candidate: '+result['candidate']+' · '+result['note']
            self.evidence.setText(message)
        elif 'output' in result:
            message += '\nRestored to: '+result['output']
            if result.get('kind') == 'encrypted_restore':
                self.security_status.setText(f"ENCRYPTED RESTORE PASS · Authentication and SHA-256 checks passed · {result['files']} files · {result['restore_seconds']:.3f}s measured. Restored files are unencrypted.")
            if result.get('kind') == 'recovery_test':
                t = 'PASS' if result['file_recovery_target_met'] else 'MISSED'
                a = result['recovery_point_age_seconds']
                age = 'Unknown (legacy backup)' if a is None else f'{a/60:.2f} min'
                age_pass = 'UNKNOWN' if a is None else ('PASS' if result['recovery_point_age_target_met'] else 'MISSED')
                self.evidence.setText(f"FILE RECOVERY {t} · {result['restore_seconds']:.3f}s / {result['rto_target_seconds']}s target. RECOVERY-POINT AGE {age_pass} · {age}. Service recovery NOT TESTED.")
                if result.get('report_path'):
                    self.note('Report saved: '+result['report_path'])
                if result.get('report_save_error'):
                    self.note('Restore succeeded but report could not be saved: '+result['report_save_error'])
        elif self.operation == 'Backup':
            message += f" {len(result['files'])} files · {size(result['bytes'])} · {result['duration_seconds']} seconds measured copy/verification time."
        self.status.setText(message)
        self.note(message)
        self.refresh()
        if 'output' in result:
            QMessageBox.information(self,'Restore complete',message)
            QDesktopServices.openUrl(QUrl.fromLocalFile(result['output']))

    def failed(self, message):
        self.progress.setValue(0)
        self.status.setText(self.operation+' failed — see activity log.')
        self.note(self.operation+' failed: '+message)
        QMessageBox.warning(self,self.operation+' failed',message)

    def export(self):
        r = self.selected()
        if not r:
            return
        path,_ = QFileDialog.getSaveFileName(self,'Export backup manifest','backup-manifest.json','JSON (*.json)')
        if path:
            try:
                Path(path).write_text(json.dumps(r,indent=2),encoding='utf-8')
                self.note('Manifest exported to '+path)
            except OSError as e:
                QMessageBox.warning(self,'Export failed',str(e))

    def closeEvent(self,event):
        if self.worker and self.worker.isRunning():
            QMessageBox.information(self,'Operation in progress','Wait for the file operation to finish before closing the app.')
            event.ignore()
        else:
            event.accept()


STYLE = '''
QWidget { background:#101e27; color:#c3d3db; font-family:'Segoe UI'; font-size:12px; }
QFrame#sidebar { background:#0c1720; border-right:1px solid #273944; }
QFrame#sidebar QLabel { background:transparent; color:#7f99a6; }
QLabel#logo { font-size:25px; font-weight:700; color:#65dfb5; padding-bottom:18px; }
QLabel#title { font-size:32px; font-weight:700; color:#edf6f4; }
QFrame#card { background:#172a35; border:1px solid #293f4a; border-radius:10px; }
QFrame#card QLabel { background:transparent; }
QLabel#metric { color:#66e2b7; font-size:24px; font-weight:600; }
QPushButton { background:#243e4a; border:1px solid #385562; border-radius:6px; padding:10px 13px; color:#d7e7ec; }
QPushButton:hover { background:#315563; }
QPushButton:disabled { color:#607985; background:#1a303a; border-color:#253c45; }
QPushButton#primary { background:#64dfb3; color:#103b2f; font-weight:700; border:0; }
QLineEdit { background:#10212b; border:1px solid #36505e; border-radius:5px; padding:9px; selection-background-color:#276c63; }
QTableWidget,QTextEdit { background:#13242e; border:0; gridline-color:#283f4b; selection-background-color:#2a5e5b; border-radius:4px; }
QTableWidget::item { padding:7px; }
QHeaderView::section { background:#1b303c; color:#9db6c2; border:0; padding:9px; }
QProgressBar { border:0; background:#203641; border-radius:4px; }
QProgressBar::chunk { background:#64dfb3; border-radius:4px; }
QSplitter::handle { background:#101e27; width:12px; }
QMessageBox { background:#172a35; }
'''


def configure_fonts(app):
    for name in ['segoeui.ttf', 'seguisym.ttf', 'seguiemj.ttf']:
        font = Path('C:/Windows/Fonts') / name
        if font.exists():
            QFontDatabase.addApplicationFont(str(font))
    app.setFont(QFont('Segoe UI', 10))


if __name__ == '__main__':
    app = QApplication(sys.argv)
    configure_fonts(app)
    app.setStyle('Fusion')
    app.setStyleSheet(STYLE)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
