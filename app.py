"""
FRC 2026 计球器 - 主窗口与业务逻辑
"""
import json
import sys
from pathlib import Path

from PyQt6.QtCore import Qt, QObject, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QDialog,
    QFormLayout,
    QLineEdit,
    QDialogButtonBox,
    QMessageBox,
    QSpinBox,
    QComboBox,
)
from PyQt6.QtGui import QFont


# 打包为 exe 时，配置保存在 exe 同目录
if getattr(sys, "frozen", False):
    _base_path = Path(sys.executable).parent
else:
    _base_path = Path(__file__).parent
CONFIG_PATH = _base_path / "config.json"


def load_config():
    """加载配置文件"""
    default = {
        "ball_count": 0,
        "phase": "Auto",
        "auto_score": 0,
        "teleop_score": 0,
        "shortcuts": {
            "add_small": "o",
            "add_large": "p",
            "minus_small": "[",
            "minus_large": "]",
            "toggle_phase": "t",
            "reset": "r",
            "quit": "q",
        },
        "custom_shortcuts": [],
        "window": {"x": 100, "y": 100, "opacity": 0.85},
    }
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
        else:
            # 旧格式迁移：add_one/add_five -> add_small/add_large
            sc = data.get("shortcuts", {})
            if "add_one" in sc:
                data["shortcuts"] = {
                    "add_small": sc.get("add_one", "o"),
                    "add_large": sc.get("add_five", "p"),
                    "minus_small": sc.get("minus_one", "["),
                    "minus_large": sc.get("minus_five", "]"),
                    "quit": sc.get("quit", "q"),
                    "toggle_phase": sc.get("toggle_phase", "t"),
                    "reset": sc.get("reset", "r"),
                }
            sc = data.get("shortcuts", {})
            if "quit" not in sc:
                sc["quit"] = "q"
            if "toggle_phase" not in sc:
                sc["toggle_phase"] = "t"
            if "reset" not in sc:
                sc["reset"] = "r"
            if "custom_shortcuts" not in data:
                data["custom_shortcuts"] = []
            if "auto_score" not in data:
                data["auto_score"] = 0
            if "teleop_score" not in data:
                data["teleop_score"] = 0
            return data
    save_config(default)
    return default


def save_config(config):
    """保存配置文件"""
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


class HotkeySignal(QObject):
    """用于从 pynput 线程安全传递到主线程的信号"""
    add_small = pyqtSignal()
    add_large = pyqtSignal()
    minus_small = pyqtSignal()
    minus_large = pyqtSignal()
    toggle_phase = pyqtSignal()
    reset = pyqtSignal()
    quit_app = pyqtSignal()
    custom_delta = pyqtSignal(int)  # 自定义快捷键触发的增减量（正为加，负为减）


class KeyRecorder(QObject):
    """按键录制器：后台监听，通过信号传递到主线程"""
    key_recorded = pyqtSignal(str)


class ShortcutSettingsDialog(QDialog):
    """快捷键设置：固定 4 组 + 自定义行"""

    def __init__(self, shortcuts, custom_shortcuts, parent=None):
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.shortcuts = dict(shortcuts)
        self.custom_shortcuts = list(custom_shortcuts)
        self.custom_rows = []

        layout = QVBoxLayout(self)

        form = QFormLayout()

        # 固定：加球 +1
        row1 = QHBoxLayout()
        self.add_small_edit = QLineEdit(self.shortcuts.get("add_small", "o"))
        self.add_small_edit.setMaximumWidth(60)
        self.add_small_btn = QPushButton("录制")
        self.add_small_btn.clicked.connect(lambda: self._start_record(self.add_small_edit))
        row1.addWidget(self.add_small_edit)
        row1.addWidget(self.add_small_btn)
        row1.addWidget(QLabel("（固定 +1）"))
        form.addRow("加球 +1:", row1)

        # 固定：加球 +5
        row2 = QHBoxLayout()
        self.add_large_edit = QLineEdit(self.shortcuts.get("add_large", "p"))
        self.add_large_edit.setMaximumWidth(60)
        self.add_large_btn = QPushButton("录制")
        self.add_large_btn.clicked.connect(lambda: self._start_record(self.add_large_edit))
        row2.addWidget(self.add_large_edit)
        row2.addWidget(self.add_large_btn)
        row2.addWidget(QLabel("（固定 +5）"))
        form.addRow("加球 +5:", row2)

        # 固定：减球 -1
        row3 = QHBoxLayout()
        self.minus_small_edit = QLineEdit(self.shortcuts.get("minus_small", "["))
        self.minus_small_edit.setMaximumWidth(60)
        self.minus_small_btn = QPushButton("录制")
        self.minus_small_btn.clicked.connect(lambda: self._start_record(self.minus_small_edit))
        row3.addWidget(self.minus_small_edit)
        row3.addWidget(self.minus_small_btn)
        row3.addWidget(QLabel("（固定 -1）"))
        form.addRow("减球 -1:", row3)

        # 固定：减球 -5
        row4 = QHBoxLayout()
        self.minus_large_edit = QLineEdit(self.shortcuts.get("minus_large", "]"))
        self.minus_large_edit.setMaximumWidth(60)
        self.minus_large_btn = QPushButton("录制")
        self.minus_large_btn.clicked.connect(lambda: self._start_record(self.minus_large_edit))
        row4.addWidget(self.minus_large_edit)
        row4.addWidget(self.minus_large_btn)
        row4.addWidget(QLabel("（固定 -5）"))
        form.addRow("减球 -5:", row4)

        # 切换 Auto/Teleop
        row5 = QHBoxLayout()
        self.toggle_phase_edit = QLineEdit(self.shortcuts.get("toggle_phase", "t"))
        self.toggle_phase_edit.setMaximumWidth(60)
        self.toggle_phase_btn = QPushButton("录制")
        self.toggle_phase_btn.clicked.connect(lambda: self._start_record(self.toggle_phase_edit))
        row5.addWidget(self.toggle_phase_edit)
        row5.addWidget(self.toggle_phase_btn)
        form.addRow("切换 Auto/Teleop:", row5)

        # 清零
        row6 = QHBoxLayout()
        self.reset_edit = QLineEdit(self.shortcuts.get("reset", "r"))
        self.reset_edit.setMaximumWidth(60)
        self.reset_btn = QPushButton("录制")
        self.reset_btn.clicked.connect(lambda: self._start_record(self.reset_edit))
        row6.addWidget(self.reset_edit)
        row6.addWidget(self.reset_btn)
        form.addRow("清零:", row6)

        # 关闭程序
        row7 = QHBoxLayout()
        self.quit_edit = QLineEdit(self.shortcuts.get("quit", "q"))
        self.quit_edit.setMaximumWidth(60)
        self.quit_btn = QPushButton("录制")
        self.quit_btn.clicked.connect(lambda: self._start_record(self.quit_edit))
        row7.addWidget(self.quit_edit)
        row7.addWidget(self.quit_btn)
        form.addRow("关闭程序:", row7)

        layout.addLayout(form)

        # 自定义快捷键
        layout.addWidget(QLabel("自定义："))
        self.custom_container = QWidget()
        self.custom_layout = QVBoxLayout(self.custom_container)
        self.custom_layout.setContentsMargins(0, 0, 0, 0)
        for item in self.custom_shortcuts:
            self._add_custom_row(item.get("key", ""), item.get("amount", 1), item.get("type", "add"))
        layout.addWidget(self.custom_container)

        add_btn = QPushButton("+ 添加自定义")
        add_btn.clicked.connect(lambda: self._add_custom_row("", 1, "add"))
        layout.addWidget(add_btn)

        layout.addWidget(QLabel("提示：点击「录制」后按下要绑定的键"))

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _start_record(self, edit: QLineEdit):
        import threading
        from pynput import keyboard

        edit.setPlaceholderText("请按键...")
        recorder = KeyRecorder()
        recorder.key_recorded.connect(lambda k: self._on_key_recorded(edit, k))

        def listen():
            result = [None]

            def on_press(key):
                if result[0] is not None:
                    return
                try:
                    char = key.char if hasattr(key, "char") and key.char else None
                except AttributeError:
                    char = None
                if char is not None:
                    result[0] = char
                    recorder.key_recorded.emit(char)
                    return False
                if hasattr(key, "name"):
                    k = " " if key.name == "space" else (key.name if len(key.name) == 1 else f"<{key.name}>")
                    result[0] = k
                    recorder.key_recorded.emit(k)
                    return False
                return True

            with keyboard.Listener(on_press=on_press) as lst:
                lst.join()

        threading.Thread(target=listen, daemon=True).start()

    def _on_key_recorded(self, edit: QLineEdit, key: str):
        edit.setText(key)
        edit.setPlaceholderText("")

    def _add_custom_row(self, key="", amount=1, type_="add"):
        row_widget = QWidget()
        row = QHBoxLayout(row_widget)
        row.setContentsMargins(0, 2, 0, 2)
        edit = QLineEdit(key)
        edit.setMaximumWidth(50)
        edit.setPlaceholderText("键")
        rec_btn = QPushButton("录制")
        rec_btn.clicked.connect(lambda: self._start_record(edit))
        spin = QSpinBox()
        spin.setRange(1, 999)
        spin.setValue(amount)
        spin.setMaximumWidth(60)
        combo = QComboBox()
        combo.addItems(["加", "减"])
        combo.setCurrentIndex(1 if type_ == "minus" else 0)
        combo.setMaximumWidth(50)
        del_btn = QPushButton("删除")
        row.addWidget(edit)
        row.addWidget(rec_btn)
        row.addWidget(spin)
        row.addWidget(QLabel("球"))
        row.addWidget(combo)
        row.addWidget(del_btn)
        row.addStretch()
        self.custom_layout.addWidget(row_widget)
        entry = {"edit": edit, "spin": spin, "combo": combo}

        def do_remove():
            row_widget.deleteLater()
            self.custom_rows.remove(entry)
        del_btn.clicked.connect(do_remove)
        self.custom_rows.append(entry)

    def get_settings(self):
        custom = []
        for r in self.custom_rows:
            k = r["edit"].text().strip()
            if not k:
                continue
            amt = r["spin"].value()
            typ = "minus" if r["combo"].currentText() == "减" else "add"
            custom.append({"key": k, "amount": amt, "type": typ})
        return {
            "shortcuts": {
                "add_small": self.add_small_edit.text().strip() or "o",
                "add_large": self.add_large_edit.text().strip() or "p",
                "minus_small": self.minus_small_edit.text().strip() or "[",
                "minus_large": self.minus_large_edit.text().strip() or "]",
                "toggle_phase": self.toggle_phase_edit.text().strip() or "t",
                "reset": self.reset_edit.text().strip() or "r",
                "quit": self.quit_edit.text().strip() or "q",
            },
            "custom_shortcuts": custom,
        }


class DraggableCentralWidget(QWidget):
    """中央区域：空白处可拖拽移动窗口"""

    def __init__(self, window, parent=None):
        super().__init__(parent)
        self._window = window
        self._drag_pos = None

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint()

    def mouseMoveEvent(self, event):
        if self._drag_pos is not None and event.buttons() & Qt.MouseButton.LeftButton:
            diff = event.globalPosition().toPoint() - self._drag_pos
            self._window.move(self._window.pos() + diff)
            self._drag_pos = event.globalPosition().toPoint()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = None
            pos = self._window.pos()
            self._window.config["window"]["x"] = pos.x()
            self._window.config["window"]["y"] = pos.y()
            save_config(self._window.config)


class DraggableBallLabel(QLabel):
    """球数标签：支持双击归零、拖拽移动窗口"""

    def __init__(self, window, parent=None):
        super().__init__(parent)
        self._window = window
        self._drag_pos = None

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint()

    def mouseMoveEvent(self, event):
        if self._drag_pos is not None and event.buttons() & Qt.MouseButton.LeftButton:
            diff = event.globalPosition().toPoint() - self._drag_pos
            self._window.move(self._window.pos() + diff)
            self._drag_pos = event.globalPosition().toPoint()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = None
            pos = self._window.pos()
            self._window.config["window"]["x"] = pos.x()
            self._window.config["window"]["y"] = pos.y()
            save_config(self._window.config)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._window._reset_balls(event)


class ScorerWindow(QMainWindow):
    """计球器主窗口 - 半透明、置顶、无边框、可拖动"""

    def __init__(self):
        super().__init__()
        self.config = load_config()
        self.drag_pos = None

        self.setWindowTitle("FRC 计球器")
        self.setWindowFlags(
            Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setWindowOpacity(self.config["window"].get("opacity", 0.85))

        w = self.config["window"]
        self.resize(220, 200)
        self.move(w.get("x", 100), w.get("y", 100))

        central = DraggableCentralWidget(self)
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setSpacing(8)
        layout.setContentsMargins(12, 12, 12, 12)

        # 半透明背景样式
        central.setStyleSheet(
            """
            QWidget {
                background-color: rgba(40, 44, 52, 220);
                border-radius: 8px;
                border: 1px solid rgba(255,255,255,0.15);
            }
            QLabel {
                color: #e6e6e6;
            }
            QPushButton {
                background-color: rgba(80, 85, 95, 200);
                color: #e6e6e6;
                border: none;
                border-radius: 4px;
                padding: 6px 12px;
            }
            QPushButton:hover {
                background-color: rgba(100, 105, 115, 220);
            }
            QPushButton:pressed {
                background-color: rgba(60, 65, 75, 220);
            }
            """
        )

        # 球数显示（双击归零，拖拽移动窗口）
        self.ball_label = DraggableBallLabel(self)
        self.ball_label.setText(str(self.config.get("ball_count", 0)))
        self.ball_label.setFont(QFont("Segoe UI", 36))
        self.ball_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.ball_label)

        # 积分显示：Auto / Teleop / 总分
        score_layout = QHBoxLayout()
        score_layout.setSpacing(12)
        self.auto_score_label = QLabel(f"Auto: {self.config.get('auto_score', 0)}")
        self.auto_score_label.setFont(QFont("Segoe UI", 11))
        self.teleop_score_label = QLabel(f"Teleop: {self.config.get('teleop_score', 0)}")
        self.teleop_score_label.setFont(QFont("Segoe UI", 11))
        self.total_score_label = QLabel(f"总分: {self._total_score()}")
        self.total_score_label.setFont(QFont("Segoe UI", 12))
        score_layout.addWidget(self.auto_score_label)
        score_layout.addWidget(self.teleop_score_label)
        score_layout.addWidget(self.total_score_label)
        layout.addLayout(score_layout)

        # 比赛阶段 + 清零
        phase_row = QHBoxLayout()
        self.phase_btn = QPushButton(self.config.get("phase", "Auto"))
        self.phase_btn.setMinimumHeight(32)
        self.phase_btn.clicked.connect(self._toggle_phase)
        self.reset_btn = QPushButton("清零")
        self.reset_btn.setMinimumHeight(32)
        self.reset_btn.clicked.connect(self._do_reset)
        phase_row.addWidget(self.phase_btn)
        phase_row.addWidget(self.reset_btn)
        layout.addLayout(phase_row)

        # 设置按钮
        self.settings_btn = QPushButton("设置")
        self.settings_btn.setMaximumHeight(28)
        self.settings_btn.clicked.connect(self._open_shortcut_settings)
        layout.addWidget(self.settings_btn)

        # 信号对象，供 pynput 回调使用
        self.hotkey_signal = HotkeySignal()
        self.hotkey_signal.add_small.connect(self._add_small)
        self.hotkey_signal.add_large.connect(self._add_large)
        self.hotkey_signal.minus_small.connect(self._minus_small)
        self.hotkey_signal.minus_large.connect(self._minus_large)
        self.hotkey_signal.toggle_phase.connect(self._toggle_phase)
        self.hotkey_signal.reset.connect(self._do_reset)
        self.hotkey_signal.quit_app.connect(self._quit_app)
        self.hotkey_signal.custom_delta.connect(self._update_balls)

    def _total_score(self):
        return self.config.get("auto_score", 0) + self.config.get("teleop_score", 0)

    def _refresh_score_display(self):
        self.auto_score_label.setText(f"Auto: {self.config.get('auto_score', 0)}")
        self.teleop_score_label.setText(f"Teleop: {self.config.get('teleop_score', 0)}")
        self.total_score_label.setText(f"总分: {self._total_score()}")

    def _quit_app(self):
        QApplication.instance().quit()

    def _toggle_phase(self):
        phase = self.config.get("phase", "Auto")
        new_phase = "Teleop" if phase == "Auto" else "Auto"
        self.config["phase"] = new_phase
        self.phase_btn.setText(new_phase)
        save_config(self.config)

    def _add_small(self):
        self._update_balls(1)

    def _add_large(self):
        self._update_balls(5)

    def _minus_small(self):
        self._update_balls(-1)

    def _minus_large(self):
        self._update_balls(-5)

    def _update_balls(self, delta):
        count = self.config.get("ball_count", 0) + delta
        if count < 0:
            count = 0
        self.config["ball_count"] = count

        # 按阶段累加积分（每球 1 分）
        phase = self.config.get("phase", "Auto")
        if phase == "Auto":
            self.config["auto_score"] = max(0, self.config.get("auto_score", 0) + delta)
        else:
            self.config["teleop_score"] = max(0, self.config.get("teleop_score", 0) + delta)

        self.ball_label.setText(str(count))
        self._refresh_score_display()
        save_config(self.config)

    def _do_reset(self):
        """清零球数和积分"""
        self.config["ball_count"] = 0
        self.config["auto_score"] = 0
        self.config["teleop_score"] = 0
        self.ball_label.setText("0")
        self._refresh_score_display()
        save_config(self.config)

    def _reset_balls(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._do_reset()

    def _open_shortcut_settings(self):
        dialog = ShortcutSettingsDialog(
            self.config.get("shortcuts", {}),
            self.config.get("custom_shortcuts", []),
            self,
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            settings = dialog.get_settings()
            self.config["shortcuts"] = settings["shortcuts"]
            self.config["custom_shortcuts"] = settings["custom_shortcuts"]
            save_config(self.config)
            QMessageBox.information(
                self,
                "提示",
                "快捷键与数量已保存，请重启程序生效。",
                QMessageBox.StandardButton.Ok,
            )

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_pos = event.globalPosition().toPoint()

    def mouseMoveEvent(self, event):
        if self.drag_pos is not None and event.buttons() & Qt.MouseButton.LeftButton:
            diff = event.globalPosition().toPoint() - self.drag_pos
            self.move(self.pos() + diff)
            self.drag_pos = event.globalPosition().toPoint()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_pos = None
            pos = self.pos()
            self.config["window"]["x"] = pos.x()
            self.config["window"]["y"] = pos.y()
            save_config(self.config)
