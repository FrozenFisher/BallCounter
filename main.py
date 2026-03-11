"""
FRC 2026 计球器 - 入口
"""
import sys
import threading

from PyQt6.QtWidgets import QApplication
from pynput import keyboard

from app import ScorerWindow, load_config


def _key_to_str(key):
    """将 pynput 的 key 转为可比较的字符串"""
    try:
        if hasattr(key, "char") and key.char:
            return key.char
    except AttributeError:
        pass
    if hasattr(key, "name"):
        return " " if key.name == "space" else (key.name if len(key.name) == 1 else f"<{key.name}>")
    return None


def run_hotkey_listener(window: ScorerWindow):
    """在后台线程运行全局快捷键监听"""
    config = load_config()
    shortcuts = config.get("shortcuts", {})
    custom = config.get("custom_shortcuts", [])
    add_small = shortcuts.get("add_small", "o")
    add_large = shortcuts.get("add_large", "p")
    minus_small = shortcuts.get("minus_small", "[")
    minus_large = shortcuts.get("minus_large", "]")
    crooked_add = shortcuts.get("crooked_add", "a")
    crooked_minus = shortcuts.get("crooked_minus", "s")
    toggle_crooked_mode = shortcuts.get("toggle_crooked_mode", "<tab>")
    toggle_phase = shortcuts.get("toggle_phase", "t")
    reset_key = shortcuts.get("reset", "r")
    quit_key = shortcuts.get("quit", "q")

    def on_press(key):
        try:
            k = _key_to_str(key)
            if k is None:
                return
            if k == quit_key:
                # 先停止监听线程，再让 Qt 退出，避免窗口销毁后仍访问信号对象
                window.hotkey_signal.quit_app.emit()
                return False
            elif k == toggle_phase:
                window.hotkey_signal.toggle_phase.emit()
            elif k == reset_key:
                window.hotkey_signal.reset.emit()
            elif k == toggle_crooked_mode:
                window.hotkey_signal.toggle_crooked_mode.emit()
            elif k == crooked_add:
                window.hotkey_signal.crooked_add.emit()
            elif k == crooked_minus:
                window.hotkey_signal.crooked_minus.emit()
            elif k == add_small:
                window.hotkey_signal.add_small.emit()
            elif k == add_large:
                window.hotkey_signal.add_large.emit()
            elif k == minus_small:
                window.hotkey_signal.minus_small.emit()
            elif k == minus_large:
                window.hotkey_signal.minus_large.emit()
            else:
                for item in custom:
                    if item.get("key") == k:
                        amt = item.get("amount", 1)
                        delta = amt if item.get("type") == "add" else -amt
                        window.hotkey_signal.custom_delta.emit(delta)
                        break
        except RuntimeError:
            # Qt 对象已销毁时，停止监听线程，避免在解释器关闭阶段再报错
            return False

    with keyboard.Listener(on_press=on_press) as listener:
        listener.join()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("FRC 计球器")

    window = ScorerWindow()
    window.show()

    # 在后台线程启动快捷键监听
    hotkey_thread = threading.Thread(
        target=run_hotkey_listener, args=(window,), daemon=True
    )
    hotkey_thread.start()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
