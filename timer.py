"""
FRC 2026 Rebuilt 赛季 · 资格赛比赛计时与枢纽站状态参考。

时间表（Teleop 倒计时 2:20→0:00）：
  过渡切换 2:20–2:10 | 切换1 2:10–1:45 | 切换2 1:45–1:20
  切换3 1:20–0:55 | 切换4 0:55–0:30 | 比赛结束 0:30–0:00

自动阶段：0:20–0:00。自动与 Teleop 之间墙钟可有 3 秒空隙（仅用于与场边音效对齐），
界面不单独显示、全场剩余秒不把该间隙计入（自动结束后主行固定为 A0…140，直至 Teleop 开计）。
可勾选「跳过自动阶段」直接从 Teleop 2:20 起计（无自动、无空隙）。
以 R 开始=红方赢自动（auto_winner=RED）；以 B 开始=蓝方赢自动（auto_winner=BLUE）。

主计时行：「字母 + 当前子阶段剩余秒 + 0/90 0 + 整场比赛剩余秒」
  例：A10 0/90 0 150、T5 0/90 0 135、B5 0/90 0 110、R20 0/90 0 100、E15 0/90 0 15

SHIFT 字母：红方赢自动 → 奇数 SHIFT 为 B、偶数 SHIFT 为 R；蓝方赢自动则对调。
枢纽：自动/过渡/终局双方双枢纽均激活；SHIFT 按上表一方双激活、另一方双未激活。
"""
from __future__ import annotations

import math
import os
import struct
import tempfile
import wave
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path
from typing import Dict, List, Optional, Tuple


class AutoOutcome(Enum):
    """自动阶段胜负（auto_winner）。以 R 开始=红方赢自动；以 B 开始=蓝方赢自动。"""

    RED_WINS = auto()
    BLUE_WINS = auto()


class MatchPhase(Enum):
    AUTO = auto()
    TELEOP_TRANSITION = auto()
    TELEOP_SWITCH_1 = auto()
    TELEOP_SWITCH_2 = auto()
    TELEOP_SWITCH_3 = auto()
    TELEOP_SWITCH_4 = auto()
    TELEOP_ENDGAME = auto()
    FINISHED = auto()


class SoundEvent(Enum):
    MATCH_START = auto()
    AUTO_END = auto()
    TELEOP_BEGIN = auto()
    ALLIANCE_SHIFT = auto()
    ENDGAME_BEGIN = auto()
    MATCH_END = auto()
    MATCH_STOPPED = auto()
    FOGHORN = auto()


AUTO_SECONDS = 20
# 自动结束至 Teleop（含过渡）开始之间的场间空隙
GAP_AFTER_AUTO_SECONDS = 3
TELEOP_SECONDS = 140  # 2:20
# 墙钟总长（含 3s 间隙）；界面「全场剩余」按 自动+Teleop（20+140=160）计，不含间隙
TOTAL_MATCH_SECONDS = AUTO_SECONDS + GAP_AFTER_AUTO_SECONDS + TELEOP_SECONDS

# 计分占位（可按队伍数据接入）
SCOUT_STATS_PLACEHOLDER = "0/90 0"


@dataclass(frozen=True)
class HubState:
    """四列：红1、红2、蓝1、蓝2 —— True 为激活。"""

    red_a: bool
    red_b: bool
    blue_a: bool
    blue_b: bool


def shift_display_letter(shift_n: int, outcome: AutoOutcome) -> str:
    """SHIFT 主显示字母：红方赢自动 → 奇数 B / 偶数 R；蓝方赢自动 → 奇数 R / 偶数 B。"""
    odd = (shift_n % 2) == 1
    if outcome == AutoOutcome.RED_WINS:
        return "B" if odd else "R"
    return "R" if odd else "B"


def _shift_hubs(shift_n: int, outcome: AutoOutcome) -> HubState:
    """整联盟「双枢纽均激活」或「双枢纽均未激活」。"""
    odd = (shift_n % 2) == 1
    if outcome == AutoOutcome.RED_WINS:
        if odd:
            return HubState(False, False, True, True)
        return HubState(True, True, False, False)
    if odd:
        return HubState(True, True, False, False)
    return HubState(False, False, True, True)


def teleop_phase_and_hubs(t: int, outcome: AutoOutcome) -> Tuple[MatchPhase, HubState]:
    """t 为 Teleop 内剩余整秒数（2:20→140 … 0:00→0），返回阶段与枢纽状态。"""
    if t > 130:
        return MatchPhase.TELEOP_TRANSITION, HubState(True, True, True, True)
    if t > 105:
        return MatchPhase.TELEOP_SWITCH_1, _shift_hubs(1, outcome)
    if t > 80:
        return MatchPhase.TELEOP_SWITCH_2, _shift_hubs(2, outcome)
    if t > 55:
        return MatchPhase.TELEOP_SWITCH_3, _shift_hubs(3, outcome)
    if t > 30:
        return MatchPhase.TELEOP_SWITCH_4, _shift_hubs(4, outcome)
    if t >= 0:
        return MatchPhase.TELEOP_ENDGAME, HubState(True, True, True, True)
    return MatchPhase.FINISHED, HubState(True, True, True, True)


def primary_display_letter(phase: MatchPhase, outcome: AutoOutcome) -> str:
    """与主计时行首字母一致（不含秒数）。"""
    if phase == MatchPhase.AUTO:
        return "A"
    if phase == MatchPhase.TELEOP_TRANSITION:
        return "T"
    if phase == MatchPhase.TELEOP_ENDGAME:
        return "E"
    if phase == MatchPhase.TELEOP_SWITCH_1:
        return shift_display_letter(1, outcome)
    if phase == MatchPhase.TELEOP_SWITCH_2:
        return shift_display_letter(2, outcome)
    if phase == MatchPhase.TELEOP_SWITCH_3:
        return shift_display_letter(3, outcome)
    if phase == MatchPhase.TELEOP_SWITCH_4:
        return shift_display_letter(4, outcome)
    if phase == MatchPhase.FINISHED:
        return "—"
    return "?"


def format_scouting_timer_line(
    phase: MatchPhase,
    auto_left: int,
    t_rem: int,
    match_rem: int,
    outcome: AutoOutcome,
) -> str:
    """例：A10 0/90 0 150；auto_left 仅在 AUTO 段使用。"""
    if phase == MatchPhase.FINISHED:
        return f"— {SCOUT_STATS_PLACEHOLDER} {match_rem}"

    letter: str
    seg: int
    if phase == MatchPhase.AUTO:
        letter, seg = "A", max(0, auto_left)
    elif phase == MatchPhase.TELEOP_TRANSITION:
        letter, seg = "T", max(0, t_rem - 130)
    elif phase == MatchPhase.TELEOP_SWITCH_1:
        letter, seg = shift_display_letter(1, outcome), max(0, t_rem - 105)
    elif phase == MatchPhase.TELEOP_SWITCH_2:
        letter, seg = shift_display_letter(2, outcome), max(0, t_rem - 80)
    elif phase == MatchPhase.TELEOP_SWITCH_3:
        letter, seg = shift_display_letter(3, outcome), max(0, t_rem - 55)
    elif phase == MatchPhase.TELEOP_SWITCH_4:
        letter, seg = shift_display_letter(4, outcome), max(0, t_rem - 30)
    elif phase == MatchPhase.TELEOP_ENDGAME:
        letter, seg = "E", max(0, t_rem)
    else:
        letter, seg = "?", 0

    return f"{letter}{seg} {SCOUT_STATS_PLACEHOLDER} {match_rem}"


def phase_label_zh(phase: MatchPhase) -> str:
    return {
        MatchPhase.AUTO: "自动阶段",
        MatchPhase.TELEOP_TRANSITION: "过渡切换",
        MatchPhase.TELEOP_SWITCH_1: "切换 1",
        MatchPhase.TELEOP_SWITCH_2: "切换 2",
        MatchPhase.TELEOP_SWITCH_3: "切换 3",
        MatchPhase.TELEOP_SWITCH_4: "切换 4",
        MatchPhase.TELEOP_ENDGAME: "比赛结束",
        MatchPhase.FINISHED: "已结束",
    }.get(phase, "")


def qualification_letter_subtitle(hubs: HubState, letter: str) -> str:
    """红/蓝是否「双枢纽均激活」。"""
    r_all = hubs.red_a and hubs.red_b
    b_all = hubs.blue_a and hubs.blue_b
    return (
        f"红{'双激活' if r_all else '非双激活'} · "
        f"蓝{'双激活' if b_all else '非双激活'}　→　{letter}"
    )


@dataclass
class MatchTimerState:
    """从按下开始起经过的秒数（可浮点用于平滑显示）。"""

    elapsed_sec: float = 0.0
    auto_outcome: AutoOutcome = AutoOutcome.RED_WINS
    # True：不跑自动阶段，一开始即 Teleop 2:20 倒计时
    skip_auto: bool = False

    def total_match_seconds(self) -> float:
        return float(TELEOP_SECONDS) if self.skip_auto else float(TOTAL_MATCH_SECONDS)

    def is_finished(self) -> bool:
        return self.elapsed_sec >= self.total_match_seconds()

    def tick(self, dt: float) -> None:
        cap = self.total_match_seconds()
        self.elapsed_sec = min(cap, self.elapsed_sec + max(0.0, dt))

    def set_elapsed(self, sec: float) -> None:
        cap = self.total_match_seconds()
        self.elapsed_sec = max(0.0, min(cap, sec))

    def snapshot(self) -> Tuple[str, str, str, str, str]:
        """
        返回 (阶段行, 主计时行, 枢纽摘要, 主字母, 枢纽说明行)
        """
        e = self.elapsed_sec
        total = self.total_match_seconds()
        oc = self.auto_outcome

        if e >= total:
            hubs = HubState(True, True, True, True)
            ph = MatchPhase.FINISHED
            letter = primary_display_letter(ph, oc)
            sub = qualification_letter_subtitle(hubs, letter)
            timer_str = format_scouting_timer_line(ph, 0, 0, 0, oc)
            return f"资格赛 · {phase_label_zh(ph)}", timer_str, _hubs_line(hubs), letter, sub

        if not self.skip_auto and e < AUTO_SECONDS:
            auto_left = max(0, AUTO_SECONDS - int(e))
            match_rem = auto_left + TELEOP_SECONDS
            hubs = HubState(True, True, True, True)
            ph = MatchPhase.AUTO
            letter = primary_display_letter(ph, oc)
            sub = qualification_letter_subtitle(hubs, letter)
            timer_str = format_scouting_timer_line(ph, auto_left, 0, match_rem, oc)
            return (
                f"资格赛 · {phase_label_zh(ph)}",
                timer_str,
                _hubs_line(hubs),
                letter,
                sub,
            )

        # 墙钟间隙：仍显示为自动结束瞬间（A0），全场剩余=140，间隙不计入显示总秒
        if not self.skip_auto and e < AUTO_SECONDS + GAP_AFTER_AUTO_SECONDS:
            hubs = HubState(True, True, True, True)
            ph = MatchPhase.AUTO
            letter = primary_display_letter(ph, oc)
            sub = qualification_letter_subtitle(hubs, letter)
            match_rem = TELEOP_SECONDS
            timer_str = format_scouting_timer_line(ph, 0, 0, match_rem, oc)
            return (
                f"资格赛 · {phase_label_zh(ph)}",
                timer_str,
                _hubs_line(hubs),
                letter,
                sub,
            )

        teleop_base = 0.0 if self.skip_auto else float(AUTO_SECONDS + GAP_AFTER_AUTO_SECONDS)
        teleop_elapsed = e - teleop_base
        t_rem = max(0, int(TELEOP_SECONDS - teleop_elapsed))
        ph, hubs = teleop_phase_and_hubs(t_rem, oc)

        if ph == MatchPhase.FINISHED:
            letter = primary_display_letter(ph, oc)
            sub = qualification_letter_subtitle(hubs, letter)
            timer_str = format_scouting_timer_line(ph, 0, t_rem, 0, oc)
            return f"资格赛 · {phase_label_zh(ph)}", timer_str, _hubs_line(hubs), letter, sub

        match_rem = t_rem
        letter = primary_display_letter(ph, oc)
        sub = qualification_letter_subtitle(hubs, letter)
        timer_str = format_scouting_timer_line(ph, 0, t_rem, match_rem, oc)
        return (
            f"资格赛 · {phase_label_zh(ph)}",
            timer_str,
            _hubs_line(hubs),
            letter,
            sub,
        )

    def current_match_phase(self) -> Optional[MatchPhase]:
        """当前比赛阶段（用于 Rebuilt 阶段提示音边界）。"""
        e = self.elapsed_sec
        total = self.total_match_seconds()
        if e >= total:
            return MatchPhase.FINISHED
        if not self.skip_auto and e < AUTO_SECONDS:
            return MatchPhase.AUTO
        if not self.skip_auto and e < AUTO_SECONDS + GAP_AFTER_AUTO_SECONDS:
            return MatchPhase.AUTO
        teleop_base = 0.0 if self.skip_auto else float(AUTO_SECONDS + GAP_AFTER_AUTO_SECONDS)
        teleop_elapsed = e - teleop_base
        t_rem = max(0, int(TELEOP_SECONDS - teleop_elapsed))
        phase, _ = teleop_phase_and_hubs(t_rem, self.auto_outcome)
        return phase


def _write_mono_wav(path: str, hz: float, duration_ms: int, volume: float = 0.35) -> None:
    """生成简短正弦 WAV（无外部资源时的 Rebuilt 占位提示音）。"""
    framerate = 44100
    nframes = max(1, int(framerate * duration_ms / 1000))
    ramp = max(1, min(nframes // 4, int(framerate * 0.008)))
    with wave.open(path, "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(framerate)
        for i in range(nframes):
            t = i / framerate
            fade = 1.0
            if i < ramp:
                fade = i / ramp
            elif i >= nframes - ramp:
                fade = (nframes - 1 - i) / ramp
            val = int(
                volume
                * 32767.0
                * math.sin(2.0 * math.pi * hz * t)
                * fade
            )
            val = max(-32767, min(32767, val))
            w.writeframes(struct.pack("<h", val))


_tone_file_cache: Dict[Tuple[float, int], str] = {}


class RebuiltPhaseSounds:
    """
    FRC 2026 Rebuilt 各阶段提示音。

    优先加载与脚本同目录下 sounds/rebuilt/<阶段>.wav（可自行从 FIRST 官方资源、
    现场录音或 Chief Delphi 讨论帖中取得合法文件后替换同名文件）。
    若文件不存在则播放内置短纯音占位。
    """

    _event_wavs: Dict[SoundEvent, str] = {
        SoundEvent.MATCH_START: "CavalryCharge.wav",
        SoundEvent.AUTO_END: "Buzzer.wav",
        SoundEvent.TELEOP_BEGIN: "ThreeBells.wav",
        SoundEvent.ALLIANCE_SHIFT: "Shift.wav",
        SoundEvent.ENDGAME_BEGIN: "EndGame.wav",
        SoundEvent.MATCH_END: "Sonar.wav",
        SoundEvent.MATCH_STOPPED: "Buzzer.wav",
        SoundEvent.FOGHORN: "Sonar.wav",
    }

    _event_fallback: Dict[SoundEvent, Tuple[float, int]] = {
        SoundEvent.MATCH_START: (587.0, 220),
        SoundEvent.AUTO_END: (880.0, 140),
        SoundEvent.TELEOP_BEGIN: (659.0, 220),
        SoundEvent.ALLIANCE_SHIFT: (1046.0, 120),
        SoundEvent.ENDGAME_BEGIN: (988.0, 180),
        SoundEvent.MATCH_END: (196.0, 300),
        SoundEvent.MATCH_STOPPED: (880.0, 140),
        SoundEvent.FOGHORN: (147.0, 420),
    }

    def __init__(self, parent=None) -> None:
        from PyQt6.QtCore import QTimer
        from PyQt6.QtMultimedia import QSoundEffect

        self._root = Path(__file__).resolve().parent / "sounds" / "rebuilt"
        self._effect = QSoundEffect(parent)
        self._effect.setVolume(0.42)
        self._timer = QTimer(parent)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._play_next)
        self._pending: List[SoundEvent] = []

    def _play_event(self, event: SoundEvent) -> None:
        from PyQt6.QtCore import QUrl

        name = self._event_wavs.get(event)
        if name:
            wav = self._root / name
            if wav.is_file():
                self._effect.setSource(QUrl.fromLocalFile(str(wav.resolve())))
                self._effect.play()
                return

        hz_ms = self._event_fallback.get(event, (880.0, 80))
        key = (hz_ms[0], hz_ms[1])
        if key not in _tone_file_cache:
            fd, path = tempfile.mkstemp(suffix=".wav", prefix="rebuilt_tone_")
            os.close(fd)
            _write_mono_wav(path, hz_ms[0], hz_ms[1])
            _tone_file_cache[key] = path
        self._effect.setSource(QUrl.fromLocalFile(_tone_file_cache[key]))
        self._effect.play()

    def _play_next(self) -> None:
        if not self._pending:
            return
        evt = self._pending.pop(0)
        self._play_event(evt)
        if self._pending:
            # 同一秒命中多个事件（如 AUTO_END 与 TELEOP_BEGIN）时，串行播放
            self._timer.start(260)

    def play_event(self, event: SoundEvent) -> None:
        self._pending = [event]
        self._timer.stop()
        self._play_next()

    def play_events(self, events: List[SoundEvent]) -> None:
        if not events:
            return
        self._pending.extend(events)
        if not self._timer.isActive():
            self._play_next()


def _timed_sound_events(prev_elapsed: float, new_elapsed: float, skip_auto: bool) -> List[SoundEvent]:
    """
    根据 elapsed 穿越阈值触发事件（单位：秒）。
    含自动时：AUTO 20s → AUTO_END；再经 GAP_AFTER_AUTO_SECONDS 后 TELEOP_BEGIN；
    Teleop 140s；总长 AUTO+GAP+TELEOP。
    """
    events: List[Tuple[float, SoundEvent]] = []

    def add(threshold: float, evt: SoundEvent) -> None:
        if prev_elapsed < threshold <= new_elapsed:
            events.append((threshold, evt))

    # 按用户表：2:10, 1:45, 1:20, 0:55
    shift_teleop_elapsed = [10, 35, 60, 85]
    endgame_teleop_elapsed = 110  # 0:30

    if skip_auto:
        add(0.0, SoundEvent.TELEOP_BEGIN)
        for t in shift_teleop_elapsed:
            add(float(t), SoundEvent.ALLIANCE_SHIFT)
        add(float(endgame_teleop_elapsed), SoundEvent.ENDGAME_BEGIN)
        add(float(TELEOP_SECONDS), SoundEvent.MATCH_END)
    else:
        teleop_start = float(AUTO_SECONDS + GAP_AFTER_AUTO_SECONDS)
        add(float(AUTO_SECONDS), SoundEvent.AUTO_END)
        add(teleop_start, SoundEvent.TELEOP_BEGIN)
        for t in shift_teleop_elapsed:
            add(teleop_start + float(t), SoundEvent.ALLIANCE_SHIFT)
        add(teleop_start + float(endgame_teleop_elapsed), SoundEvent.ENDGAME_BEGIN)
        add(teleop_start + float(TELEOP_SECONDS), SoundEvent.MATCH_END)

    events.sort(key=lambda x: x[0])
    return [evt for _, evt in events]


def _hubs_line(h: HubState) -> str:
    def one(x: bool) -> str:
        return "激活" if x else "非激活"

    return (
        f"红:{one(h.red_a)}/{one(h.red_b)}  "
        f"蓝:{one(h.blue_a)}/{one(h.blue_b)}"
    )


def run_timer_app() -> None:
    """独立小窗口：按下「开始」后按表倒计时并显示资格赛说明。"""
    import sys

    from PyQt6.QtCore import Qt, QTimer
    from PyQt6.QtGui import QFont, QFontInfo
    from PyQt6.QtWidgets import (
        QApplication,
        QButtonGroup,
        QCheckBox,
        QComboBox,
        QHBoxLayout,
        QLabel,
        QMainWindow,
        QPushButton,
        QRadioButton,
        QTabWidget,
        QVBoxLayout,
        QWidget,
    )

    class TimerWindow(QMainWindow):
        # 简单模式：每颗 80px（在 20px 基础上再 ×4）；字高约 2 颗、行高约 4 颗；黑底红字 + Unifont
        _LED_GRAIN_PX = 80
        _LED_LINE_HEIGHT_GRAINS = 4
        _LED_FONT_HEIGHT_GRAINS = 2

        _LED_STYLE_COLORS = """
            QLabel {
                background-color: #000000;
                color: #ff2222;
                padding: 0px;
                margin: 0px;
                border: none;
            }
        """

        @staticmethod
        def _led_font(pixel_size: int, letter_space: float) -> QFont:
            for name in ("Unifont", "GNU Unifont", "Unifont CSUR", "Unifont Upper"):
                f = QFont(name)
                f.setPixelSize(pixel_size)
                f.setBold(True)
                f.setStyleHint(QFont.StyleHint.Monospace)
                f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, letter_space)
                if QFontInfo(f).exactMatch():
                    return f
            fb = QFont("Consolas")
            fb.setPixelSize(pixel_size)
            fb.setBold(True)
            fb.setStyleHint(QFont.StyleHint.Monospace)
            fb.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, letter_space)
            return fb

        def __init__(self) -> None:
            super().__init__()
            self.setWindowTitle("FRC 2026 Rebuilt · 资格赛计时")
            self._state = MatchTimerState()
            self._running = False

            tabs = QTabWidget()
            self.setCentralWidget(tabs)

            page_display = QWidget()
            disp_layout = QVBoxLayout(page_display)
            disp_layout.setSpacing(8)

            disp_btn_row = QHBoxLayout()
            self.btn_start = QPushButton("开始")
            self.btn_start.clicked.connect(self._on_start)
            self.btn_reset = QPushButton("重置")
            self.btn_reset.clicked.connect(self._on_reset)
            disp_btn_row.addWidget(self.btn_start)
            disp_btn_row.addWidget(self.btn_reset)
            disp_btn_row.addStretch()
            disp_layout.addLayout(disp_btn_row)

            self.line_phase = QLabel("资格赛 · 未开始")
            self.line_phase.setFont(QFont("Segoe UI", 12))
            self.line_timer = QLabel("A20 0/90 0 160")
            self.line_timer.setFont(QFont("Segoe UI", 22, QFont.Weight.Bold))
            self.line_timer.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.line_hubs = QLabel("")
            self.line_hubs.setFont(QFont("Segoe UI", 10))
            self.line_letters = QLabel("")
            self.line_letters.setFont(QFont("Segoe UI", 14, QFont.Weight.DemiBold))
            self.line_hint = QLabel(
                "主行：字母+子阶段剩余秒；末项=全场剩余（自动+Teleop=160，不含墙钟 3s 间隙）。\n"
                "间隙内仍显示 A0…140。SHIFT 字母由 auto_winner 与奇偶决定。"
            )
            self.line_hint.setFont(QFont("Segoe UI", 9))
            self.line_hint.setWordWrap(True)

            grain = self._LED_GRAIN_PX
            font_px = self._LED_FONT_HEIGHT_GRAINS * grain
            letter_space = max(2.0, float(grain) / 5.0)
            self.led_line = QLabel("A20 0/90 0 160")
            self.led_line.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.led_line.setFont(self._led_font(font_px, letter_space))
            self.led_line.setStyleSheet(self._LED_STYLE_COLORS)
            self.led_line.setFixedHeight(self._LED_LINE_HEIGHT_GRAINS * grain)
            self.led_line.setScaledContents(False)

            disp_layout.addWidget(self.line_phase)
            disp_layout.addWidget(self.line_timer)
            disp_layout.addWidget(self.line_hubs)
            disp_layout.addWidget(self.line_letters)
            disp_layout.addWidget(self.line_hint)
            disp_layout.addWidget(self.led_line)
            disp_layout.addStretch()

            page_settings = QWidget()
            set_layout = QVBoxLayout(page_settings)
            set_layout.setSpacing(10)

            view_row = QHBoxLayout()
            view_row.addWidget(QLabel("显示界面："))
            self.combo_view = QComboBox()
            self.combo_view.addItems(["复杂（显示页含说明）", "简单（仅 LED 一行）"])
            self.combo_view.currentIndexChanged.connect(self._on_view_changed)
            view_row.addWidget(self.combo_view)
            view_row.addStretch()
            set_layout.addLayout(view_row)

            opt_row = QHBoxLayout()
            self.chk_skip_auto = QCheckBox("跳过自动阶段")
            self.chk_skip_auto.setToolTip(
                "勾选后无自动、无 3s 空隙，直接从 Teleop 2:20 倒计时（总长 2:20）"
            )
            self.radio_r = QRadioButton("以 R 开始（红方自动胜）")
            self.radio_b = QRadioButton("以 B 开始（蓝方自动胜）")
            self.radio_r.setChecked(True)
            self._side_group = QButtonGroup(self)
            self._side_group.addButton(self.radio_r)
            self._side_group.addButton(self.radio_b)
            opt_row.addWidget(self.chk_skip_auto)
            opt_row.addStretch()
            set_layout.addLayout(opt_row)
            side_row = QHBoxLayout()
            side_row.addWidget(self.radio_r)
            side_row.addWidget(self.radio_b)
            set_layout.addLayout(side_row)
            self.chk_skip_auto.stateChanged.connect(self._on_options_changed)
            self.radio_r.toggled.connect(self._on_options_changed)
            self.radio_b.toggled.connect(self._on_options_changed)

            self.chk_sound = QCheckBox("Rebuilt 事件提示音")
            self.chk_sound.setChecked(True)
            self.chk_sound.setToolTip(
                "按事件表播放（开始/切换/终局/结束）。WAV 放入 sounds/rebuilt/ 可覆盖内置音。"
            )
            set_layout.addWidget(self.chk_sound)

            fh_row = QHBoxLayout()
            self.btn_foghorn = QPushButton("Foghorn")
            self.btn_foghorn.clicked.connect(self._on_foghorn)
            fh_row.addWidget(self.btn_foghorn)
            fh_row.addStretch()
            set_layout.addLayout(fh_row)
            set_layout.addStretch()

            tabs.addTab(page_display, "显示")
            tabs.addTab(page_settings, "设置")

            self._sounds = RebuiltPhaseSounds(self)
            self._last_phase: Optional[MatchPhase] = None

            self._qtimer = QTimer(self)
            self._qtimer.setInterval(100)
            self._qtimer.timeout.connect(self._on_tick)

            self._apply_view_mode()
            self._refresh()

        def _apply_view_mode(self) -> None:
            simple = self.combo_view.currentIndex() == 1
            self.line_phase.setVisible(not simple)
            self.line_timer.setVisible(not simple)
            self.line_hubs.setVisible(not simple)
            self.line_letters.setVisible(not simple)
            self.line_hint.setVisible(not simple)
            self.led_line.setVisible(simple)
            if simple:
                h = self._LED_LINE_HEIGHT_GRAINS * self._LED_GRAIN_PX + 120
                self.setMinimumSize(360, h)
            else:
                self.setMinimumSize(400, 320)

        def _on_view_changed(self, _index: int) -> None:
            self._apply_view_mode()

        def _apply_options_from_ui(self) -> None:
            self._state.skip_auto = self.chk_skip_auto.isChecked()
            self._state.auto_outcome = (
                AutoOutcome.BLUE_WINS if self.radio_b.isChecked() else AutoOutcome.RED_WINS
            )
            self._state.set_elapsed(self._state.elapsed_sec)

        def _set_options_enabled(self, enabled: bool) -> None:
            self.chk_skip_auto.setEnabled(enabled)
            self.radio_r.setEnabled(enabled)
            self.radio_b.setEnabled(enabled)

        def _on_options_changed(self) -> None:
            if self._running:
                return
            self._apply_options_from_ui()
            self._refresh()

        def _on_start(self) -> None:
            self._apply_options_from_ui()
            if self._state.is_finished():
                self._state.set_elapsed(0.0)
            self._last_phase = self._state.current_match_phase()
            self._running = True
            self._set_options_enabled(False)
            self._qtimer.start()
            self.btn_start.setEnabled(False)
            if self.chk_sound.isChecked():
                start_events = [SoundEvent.MATCH_START]
                if self._state.skip_auto:
                    start_events.append(SoundEvent.TELEOP_BEGIN)
                self._sounds.play_events(start_events)

        def _on_reset(self) -> None:
            was_running = self._running
            self._running = False
            self._qtimer.stop()
            self._state = MatchTimerState()
            self._apply_options_from_ui()
            self._last_phase = None
            self.btn_start.setEnabled(True)
            self._set_options_enabled(True)
            if was_running and self.chk_sound.isChecked():
                self._sounds.play_event(SoundEvent.MATCH_STOPPED)
            self._refresh()

        def _on_foghorn(self) -> None:
            if self.chk_sound.isChecked():
                self._sounds.play_event(SoundEvent.FOGHORN)

        def _on_tick(self) -> None:
            prev = self._state.elapsed_sec
            self._state.tick(0.1)
            ph = self._state.current_match_phase()
            if self._running and ph is not None and ph != self._last_phase:
                self._last_phase = ph
            if self._running and self.chk_sound.isChecked():
                events = _timed_sound_events(prev, self._state.elapsed_sec, self._state.skip_auto)
                self._sounds.play_events(events)
            self._refresh()
            if self._state.is_finished():
                self._running = False
                self._qtimer.stop()
                self.btn_start.setEnabled(True)
                self._set_options_enabled(True)

        def _refresh(self) -> None:
            if not self._running:
                self._apply_options_from_ui()
            line1, timer_s, hubs_s, letters, letter_sub = self._state.snapshot()
            self.line_phase.setText(line1)
            self.line_timer.setText(timer_s)
            self.line_hubs.setText(hubs_s)
            self.line_letters.setText(f"主字母：{letters}\n{letter_sub}")
            self.led_line.setText(timer_s)

    app = QApplication(sys.argv)
    w = TimerWindow()
    w.resize(520, 440)
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    run_timer_app()
