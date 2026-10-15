from __future__ import annotations

from typing import Optional
import math

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .theme import FG_MUTED, FG_TEXT, GREEN_OK, RED_FAULT


def _repolish(widget: QWidget) -> None:
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def _format_min_max(min_value: float, max_value: float) -> str:
    def _fmt(v: float) -> str:
        if v == int(v):
            return f"{int(v)}"
        return f"{v}"

    return f"Min {_fmt(min_value)}" if math.isinf(max_value) else f"Min {_fmt(min_value)} / Max {_fmt(max_value)}"


class ConfirmDialog(QDialog):
    def __init__(
        self,
        parent: Optional[QWidget],
        title: str,
        message: str,
        confirm_text: str = "Confirm",
        cancel_text: str = "Cancel",
        dangerous: bool = False,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        self.setWindowFlag(Qt.WindowMinimizeButtonHint, False)
        self.setWindowFlag(Qt.WindowMaximizeButtonHint, False)
        self.setWindowFlag(Qt.WindowCloseButtonHint, True)
        self.setSizeGripEnabled(False)
        self.setFixedSize(680, 280)

        body = QWidget(self)
        body.setObjectName("DialogBody")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(body)

        layout = QVBoxLayout(body)
        layout.setContentsMargins(28, 22, 28, 22)
        layout.setSpacing(14)

        title_bar = QHBoxLayout()
        title_bar.setContentsMargins(0, 0, 0, 0)
        title_bar.setSpacing(8)

        title_label = QLabel(title, body)
        title_label.setStyleSheet(
            f"font-size: 18px; font-weight: 700; color: {FG_TEXT};"
        )
        title_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        title_bar.addWidget(title_label)
        title_bar.addStretch(1)
        layout.addLayout(title_bar)

        divider = QWidget(body)
        divider.setObjectName("Divider")
        divider.setFixedHeight(1)
        divider.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        layout.addWidget(divider)

        msg_container = QVBoxLayout()
        msg_container.setContentsMargins(2, 6, 2, 6)
        msg_container.setSpacing(0)

        msg_label = QLabel(message, body)
        msg_label.setStyleSheet(
            f"font-size: 14px; color: {FG_TEXT};"
        )
        msg_label.setTextFormat(Qt.RichText)
        msg_label.setWordWrap(True)
        msg_label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        msg_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        msg_container.addWidget(msg_label)
        layout.addLayout(msg_container, 1)

        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 8, 0, 0)
        btn_row.setSpacing(14)
        btn_row.addStretch(1)

        cancel_btn = QPushButton(cancel_text, body)
        cancel_btn.setObjectName("Ghost")
        cancel_btn.setMinimumSize(140, 56)
        cancel_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        confirm_btn = QPushButton(confirm_text, body)
        if dangerous:
            confirm_btn.setObjectName("Danger")
        else:
            confirm_btn.setObjectName("ConfirmOK")
        confirm_btn.setMinimumSize(140, 56)
        confirm_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        confirm_btn.clicked.connect(self.accept)
        btn_row.addWidget(confirm_btn)

        layout.addLayout(btn_row)

    @staticmethod
    def confirm(
        parent: Optional[QWidget],
        title: str,
        message: str,
        dangerous: bool = False,
        confirm_text: str = "Confirm",
        cancel_text: str = "Cancel",
    ) -> bool:
        dlg = ConfirmDialog(
            parent,
            title=title,
            message=message,
            confirm_text=confirm_text,
            cancel_text=cancel_text,
            dangerous=dangerous,
        )
        result = dlg.exec()
        return result == QDialog.Accepted


class NumericKeypad(QDialog):
    def __init__(
        self,
        parent: Optional[QWidget],
        initial_value: Optional[float] = None,
        min_value: float = 0.0,
        max_value: float = 100.0,
        step: float = 1.0,
        decimals: int = 0,
        unit: str = "",
        title: str = "Enter Value",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        self.setWindowFlag(Qt.WindowMinimizeButtonHint, False)
        self.setWindowFlag(Qt.WindowMaximizeButtonHint, False)
        self.setWindowFlag(Qt.WindowCloseButtonHint, True)
        self.setSizeGripEnabled(False)
        self.setFixedSize(700, 400)

        self._min_value: float = min_value
        self._max_value: float = max_value
        self._step: float = step
        self._decimals: int = decimals
        self._unit: str = unit
        self._entry: str = ""
        self._final_value: Optional[float] = None

        body = QWidget(self)
        body.setObjectName("DialogBody")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(body)

        layout = QVBoxLayout(body)
        layout.setContentsMargins(24, 18, 24, 18)
        layout.setSpacing(10)

        header = QVBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(2)

        title_label = QLabel(title, body)
        title_label.setStyleSheet(
            f"font-size: 18px; font-weight: 700; color: {FG_TEXT};"
        )
        title_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        header.addWidget(title_label)

        subtitle_label = QLabel(_format_min_max(min_value, max_value), body)
        subtitle_label.setStyleSheet(
            f"font-size: 12px; color: {FG_MUTED};"
        )
        subtitle_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        header.addWidget(subtitle_label)

        layout.addLayout(header)

        readout_container = QVBoxLayout()
        readout_container.setContentsMargins(4, 6, 4, 6)
        readout_container.setSpacing(4)

        readout_row = QHBoxLayout()
        readout_row.setContentsMargins(0, 0, 0, 0)
        readout_row.setSpacing(10)
        readout_row.setAlignment(Qt.AlignCenter)

        self._value_label = QLabel(body)
        self._value_label.setObjectName("BigReadoutValue")
        self._value_label.setStyleSheet("font-size: 44px; font-weight: 700;")
        self._value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._value_label.setMinimumHeight(64)
        readout_row.addWidget(self._value_label, 1)

        self._unit_label = QLabel(unit, body)
        self._unit_label.setStyleSheet(
            f"font-size: 18px; color: {FG_MUTED}; font-weight: 600;"
        )
        self._unit_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self._unit_label.setMinimumWidth(40)
        readout_row.addWidget(self._unit_label, 0)

        readout_container.addLayout(readout_row)

        self._error_label = QLabel(body)
        self._error_label.setStyleSheet(
            f"font-size: 12px; color: {RED_FAULT}; font-weight: 600;"
        )
        self._error_label.setAlignment(Qt.AlignCenter)
        self._error_label.setVisible(False)
        readout_container.addWidget(self._error_label)

        layout.addLayout(readout_container)

        keypad_grid = QGridLayout()
        keypad_grid.setContentsMargins(0, 4, 0, 0)
        keypad_grid.setSpacing(8)
        keypad_grid.setColumnStretch(0, 1)
        keypad_grid.setColumnStretch(1, 1)
        keypad_grid.setColumnStretch(2, 1)
        keypad_grid.setColumnStretch(3, 1)

        self._btn_7 = self._make_digit_key("7")
        keypad_grid.addWidget(self._btn_7, 0, 0)
        self._btn_8 = self._make_digit_key("8")
        keypad_grid.addWidget(self._btn_8, 0, 1)
        self._btn_9 = self._make_digit_key("9")
        keypad_grid.addWidget(self._btn_9, 0, 2)
        self._btn_backspace = self._make_func_key("\u232B Backspace")
        self._btn_backspace.clicked.connect(self._on_backspace)
        keypad_grid.addWidget(self._btn_backspace, 0, 3)

        self._btn_4 = self._make_digit_key("4")
        keypad_grid.addWidget(self._btn_4, 1, 0)
        self._btn_5 = self._make_digit_key("5")
        keypad_grid.addWidget(self._btn_5, 1, 1)
        self._btn_6 = self._make_digit_key("6")
        keypad_grid.addWidget(self._btn_6, 1, 2)
        self._btn_clear = self._make_func_key("C Clear")
        self._btn_clear.clicked.connect(self._on_clear)
        keypad_grid.addWidget(self._btn_clear, 1, 3)

        self._btn_1 = self._make_digit_key("1")
        keypad_grid.addWidget(self._btn_1, 2, 0)
        self._btn_2 = self._make_digit_key("2")
        keypad_grid.addWidget(self._btn_2, 2, 1)
        self._btn_3 = self._make_digit_key("3")
        keypad_grid.addWidget(self._btn_3, 2, 2)
        self._btn_cancel = self._make_cancel_key("Cancel")
        self._btn_cancel.clicked.connect(self.reject)
        keypad_grid.addWidget(self._btn_cancel, 2, 3)

        self._btn_0 = self._make_digit_key("0")
        keypad_grid.addWidget(self._btn_0, 3, 0)

        self._btn_dot = self._make_digit_key(".")
        if decimals <= 0:
            self._btn_dot.setEnabled(False)
            self._btn_dot.setVisible(False)
        keypad_grid.addWidget(self._btn_dot, 3, 1)

        self._btn_up = self._make_func_key("\u25B2 +step")
        self._btn_up.clicked.connect(self._on_step_up)
        self._btn_up.hide()

        self._btn_down = self._make_func_key("\u25BC -step")
        self._btn_down.clicked.connect(self._on_step_down)
        self._btn_down.hide()

        self._btn_enter = self._make_enter_key("OK")
        self._btn_enter.clicked.connect(self._on_enter)
        keypad_grid.addWidget(self._btn_enter, 3, 2, 1, 2)

        layout.addLayout(keypad_grid, 1)

        if initial_value is not None:
            self._entry = self._format_value(initial_value)

        self._refresh_display()
        for index, button in enumerate(self.findChildren(QPushButton)):
            button.setObjectName(f"keypad_key_{index}")
            button.setAccessibleName(button.text())
            button.setStyleSheet(
                "QPushButton { min-width: 48px; min-height: 48px; padding: 2px; "
                "font-size: 18px; }"
            )

    def _make_digit_key(self, label: str) -> QPushButton:
        btn = QPushButton(label, self)
        btn.setObjectName("KeyPadKey")
        btn.setMinimumSize(56, 56)
        btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        btn.clicked.connect(lambda: self._on_digit(label))
        return btn

    def _make_func_key(self, label: str) -> QPushButton:
        btn = QPushButton(label, self)
        btn.setObjectName("KeyPadKey")
        btn.setProperty("func", True)
        btn.setMinimumSize(56, 56)
        btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        _repolish(btn)
        return btn

    def _make_cancel_key(self, label: str) -> QPushButton:
        btn = QPushButton(label, self)
        btn.setObjectName("KeyPadKey")
        btn.setProperty("cancel", True)
        btn.setMinimumSize(56, 56)
        btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        _repolish(btn)
        return btn

    def _make_enter_key(self, label: str) -> QPushButton:
        btn = QPushButton(label, self)
        btn.setObjectName("KeyPadKey")
        btn.setProperty("enter", True)
        btn.setMinimumSize(56, 56)
        btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        _repolish(btn)
        return btn

    def _format_value(self, v: float) -> str:
        if self._decimals <= 0:
            return f"{int(round(v))}"
        return f"{v:.{self._decimals}f}"

    def _on_digit(self, ch: str) -> None:
        self._hide_error()
        if ch == ".":
            if self._decimals <= 0:
                return
            if "." in self._entry:
                return
            if self._entry == "" or self._entry == "-":
                self._entry += "0."
            else:
                self._entry += "."
        else:
            self._entry += ch
        self._refresh_display()

    def _on_backspace(self) -> None:
        self._hide_error()
        if self._entry:
            self._entry = self._entry[:-1]
            self._refresh_display()

    def _on_clear(self) -> None:
        self._hide_error()
        self._entry = ""
        self._refresh_display()

    def _parse_entry(self) -> Optional[float]:
        if not self._entry:
            return None
        try:
            return float(self._entry)
        except ValueError:
            return None

    def _count_decimals(self, s: str) -> int:
        if "." not in s:
            return 0
        return len(s.split(".", 1)[1])

    def _on_step_up(self) -> None:
        self._hide_error()
        current = self._parse_entry()
        if current is None:
            base = self._min_value
        else:
            base = current
        new_val = base + self._step
        if new_val > self._max_value:
            new_val = self._max_value
        self._entry = self._format_value(new_val)
        self._refresh_display()

    def _on_step_down(self) -> None:
        self._hide_error()
        current = self._parse_entry()
        if current is None:
            base = self._min_value
        else:
            base = current
        new_val = base - self._step
        if new_val < self._min_value:
            new_val = self._min_value
        self._entry = self._format_value(new_val)
        self._refresh_display()

    def _validate_and_get(self) -> Optional[float]:
        if not self._entry:
            self._show_error("Enter a value")
            return None
        try:
            val = float(self._entry)
        except ValueError:
            self._show_error("Invalid number")
            return None
        if not math.isfinite(val):
            self._show_error("Enter a finite number")
            return None
        if self._count_decimals(self._entry) > self._decimals:
            self._show_error(f"Too many decimals (max {self._decimals})")
            return None
        if val < self._min_value or val > self._max_value:
            self._show_error(
                f"Value must be between {self._min_value} and {self._max_value}"
            )
            return None
        return val

    def _on_enter(self) -> None:
        val = self._validate_and_get()
        if val is None:
            return
        self._final_value = val
        self.accept()

    def _show_error(self, text: str) -> None:
        self._error_label.setText(text)
        self._error_label.setVisible(True)

    def _hide_error(self) -> None:
        self._error_label.setVisible(False)

    def _refresh_display(self) -> None:
        if not self._entry:
            self._value_label.setText("\u2014")
            return
        self._value_label.setText(self._entry)

    def value(self) -> Optional[float]:
        return self._final_value

    @staticmethod
    def get_value(
        parent: Optional[QWidget],
        initial_value: Optional[float] = None,
        min_value: float = 0.0,
        max_value: float = 100.0,
        step: float = 1.0,
        decimals: int = 0,
        unit: str = "",
        title: str = "Enter Value",
    ) -> Optional[float]:
        dlg = NumericKeypad(
            parent,
            initial_value=initial_value,
            min_value=min_value,
            max_value=max_value,
            step=step,
            decimals=decimals,
            unit=unit,
            title=title,
        )
        result = dlg.exec()
        if result == QDialog.Accepted:
            return dlg.value()
        return None
