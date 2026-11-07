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
    QAbstractItemView, QSplitter, QTextEdit)
import backup_engine as engine


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
        page.addWidget(content)
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
        for row, name, edit in [(1,'Source folder',self.source),(2,'Backup storage',self.vault)]:
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
        grid.addLayout(actions,3,0,1,3)
        layout.addWidget(config)
        middle = QSplitter(Qt.Horizontal)
        history_card = card()
        hl = QVBoxLayout(history_card)
        hl.addWidget(QLabel('BACKUP HISTORY  ·  Select a snapshot'))
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
            if edit is self.vault:
                self.refresh()

    def selected(self):
        row = self.table.currentRow()
        if row < 0 or row >= len(self.records):
            QMessageBox.information(self,'Select a snapshot','Select a backup in the history table first.')
            return None
        return self.records[row]

    def refresh(self):
        self.records = []
        if self.vault.text().strip():
            try:
                self.records = engine.history(self.vault.text().strip())
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

    def show_files(self):
        row = self.table.currentRow()
        if row < 0 or row >= len(self.records):
            return
        files = self.records[row]['files']
        self.file_table.setRowCount(len(files))
        for i,(name,meta) in enumerate(sorted(files.items())):
            self.file_table.setItem(i,0,QTableWidgetItem(name))
            self.file_table.setItem(i,1,QTableWidgetItem(size(meta['size'])))

    def launch(self, title, fn, args):
        self.operation = title
        self.progress.setValue(0)
        self.status.setText(title+'…')
        self.note(title+' started.')
        for b in self.buttons:
            b.setEnabled(False)
        self.source.setEnabled(False)
        self.vault.setEnabled(False)
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
        self.table.setEnabled(True)

    def backup(self):
        if not self.source.text().strip() or not self.vault.text().strip():
            QMessageBox.information(self,'Choose folders','Choose both a source folder and backup storage.')
            return
        self.settings.setValue('source',self.source.text().strip())
        self.settings.setValue('vault',self.vault.text().strip())
        self.launch('Backup',engine.create_backup,(self.source.text().strip(),self.vault.text().strip()))

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
        if 'output' in result:
            message += '\nRestored to: '+result['output']
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
