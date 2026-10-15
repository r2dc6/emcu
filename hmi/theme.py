from __future__ import annotations

from PySide6.QtGui import QFont


BG_CHARCOAL = "#1e2228"
BG_CHARCOAL_2 = "#262b33"
BG_CARD = "#2d343e"
BG_CARD_HOVER = "#343c48"
BG_INPUT = "#3a434f"
BG_HEADER = "#171a1f"
BG_NAV = "#171a1f"
FG_TEXT = "#e6ecf2"
FG_MUTED = "#8a95a3"
FG_DIM = "#5f6a78"
ACCENT_BLUE = "#3a8fd6"
ACCENT_BLUE_2 = "#57a7ea"
GREEN_OK = "#2ecc71"
GREEN_OK_DIM = "#248a53"
AMBER_WARN = "#f0ad4e"
AMBER_WARN_DIM = "#b37a2a"
RED_FAULT = "#e74c3c"
RED_FAULT_DIM = "#a23427"
BORDER = "#3a434f"
BORDER_LIGHT = "#485462"

QSS = f"""
* {{
    color: {FG_TEXT};
    font-family: "Roboto", "DejaVu Sans", "Liberation Sans", sans-serif;
}}
QMainWindow, QWidget#RootWidget, QWidget#ContentPage {{
    background: {BG_CHARCOAL};
}}
QLabel {{
    background: transparent;
    color: {FG_TEXT};
}}
QLabel#Title {{
    font-size: 22px;
    font-weight: 700;
    letter-spacing: 1px;
    color: {FG_TEXT};
}}
QLabel#HeaderClock {{
    font-size: 16px;
    color: {FG_MUTED};
}}
QLabel#OfflineBanner {{
    background: {RED_FAULT};
    color: white;
    padding: 4px 10px;
    font-weight: 700;
    border-radius: 4px;
}}
QLabel#BigReadoutValue {{
    font-size: 56px;
    font-weight: 700;
    color: {FG_TEXT};
}}
QLabel#BigReadoutValue.warn {{
    color: {AMBER_WARN};
}}
QLabel#BigReadoutValue.fault {{
    color: {RED_FAULT};
}}
QLabel#BigReadoutValue.stale {{
    color: {FG_DIM};
}}
QLabel#BigReadoutUnit {{
    font-size: 20px;
    color: {FG_MUTED};
}}
QLabel#BigReadoutLabel {{
    font-size: 14px;
    color: {FG_MUTED};
    letter-spacing: 0.5px;
}}
QLabel#CardTitle {{
    font-size: 16px;
    font-weight: 700;
    color: {FG_TEXT};
}}
QLabel#CardBody {{
    font-size: 14px;
    color: {FG_MUTED};
}}
QLabel#Countdown {{
    font-size: 36px;
    font-weight: 700;
    color: {ACCENT_BLUE_2};
    font-family: "DejaVu Sans Mono", "Liberation Mono", monospace;
}}
QLabel#Countdown.warn {{
    color: {AMBER_WARN};
}}
QLabel#BadgeText {{
    font-size: 13px;
    font-weight: 700;
    letter-spacing: 0.5px;
    padding: 3px 8px;
    border-radius: 4px;
}}
QFrame#StatusCard {{
    background: {BG_CARD};
    border: 1px solid {BORDER};
    border-radius: 8px;
}}
QFrame#StatusCard.warn {{
    border: 1px solid {AMBER_WARN_DIM};
}}
QFrame#StatusCard.fault {{
    border: 1px solid {RED_FAULT_DIM};
}}
QWidget#TopHeader {{
    background: {BG_HEADER};
    border-bottom: 1px solid {BORDER};
}}
QWidget#BottomNav {{
    background: {BG_NAV};
    border-top: 1px solid {BORDER};
}}
QPushButton {{
    background: {BG_INPUT};
    color: {FG_TEXT};
    border: 1px solid {BORDER_LIGHT};
    border-radius: 6px;
    padding: 8px 14px;
    font-size: 14px;
    font-weight: 600;
    min-width: 48px;
    min-height: 48px;
}}
QPushButton:hover {{
    background: {BG_CARD_HOVER};
    border-color: {ACCENT_BLUE};
}}
QPushButton:pressed {{
    background: {BG_CHARCOAL_2};
}}
QPushButton:disabled {{
    background: {BG_CHARCOAL_2};
    color: {FG_DIM};
    border-color: {BORDER};
}}
QPushButton#NavBtn {{
    background: transparent;
    color: {FG_MUTED};
    border: none;
    border-radius: 6px;
    font-size: 12px;
    padding: 4px 2px;
    min-width: 96px;
    min-height: 56px;
}}
QPushButton#NavBtn:checked, QPushButton#NavBtn[active="true"] {{
    background: {ACCENT_BLUE};
    color: white;
}}
QPushButton#NavBtn:hover:!checked {{
    color: {FG_TEXT};
    background: {BG_CARD};
}}
QPushButton#Primary {{
    background: {ACCENT_BLUE};
    color: white;
    border: 1px solid {ACCENT_BLUE_2};
}}
QPushButton#Primary:hover {{
    background: {ACCENT_BLUE_2};
}}
QPushButton#Primary:disabled {{
    background: {BG_INPUT};
    color: {FG_DIM};
    border-color: {BORDER};
}}
QPushButton#Danger {{
    background: {RED_FAULT};
    color: white;
    border: 1px solid {RED_FAULT_DIM};
}}
QPushButton#Danger:hover {{
    background: #ef5d4c;
}}
QPushButton#Danger:disabled {{
    background: {BG_INPUT};
    color: {FG_DIM};
    border-color: {BORDER};
}}
QPushButton#Ghost {{
    background: transparent;
    border: 1px solid {BORDER_LIGHT};
    color: {FG_MUTED};
}}
QPushButton#Ghost:hover {{
    color: {FG_TEXT};
    border-color: {ACCENT_BLUE};
}}
QPushButton#ConfirmOK {{
    background: {GREEN_OK};
    color: white;
    border: 1px solid {GREEN_OK_DIM};
}}
QPushButton#ConfirmOK:hover {{
    background: #36db81;
}}
QPushButton#KeyPadKey {{
    background: {BG_INPUT};
    color: {FG_TEXT};
    border: 1px solid {BORDER_LIGHT};
    border-radius: 6px;
    font-size: 22px;
    font-weight: 700;
    min-width: 64px;
    min-height: 56px;
}}
QPushButton#KeyPadKey:hover {{
    background: {BG_CARD_HOVER};
    border-color: {ACCENT_BLUE};
}}
QPushButton#KeyPadKey.func {{
    background: {BG_CARD};
    color: {FG_MUTED};
    font-size: 14px;
    font-weight: 600;
}}
QPushButton#KeyPadKey.enter {{
    background: {GREEN_OK};
    color: white;
}}
QPushButton#KeyPadKey.cancel {{
    background: {BG_CARD};
    color: {RED_FAULT};
}}
QPushButton#FilterBtn:checked {{
    background: {ACCENT_BLUE};
    color: white;
    border-color: {ACCENT_BLUE_2};
}}
QPushButton#AckBtn {{
    font-size: 12px;
    min-height: 36px;
    min-width: 80px;
    padding: 4px 8px;
}}
QListWidget, QTableWidget, QTextEdit, QLineEdit, QPlainTextEdit {{
    background: {BG_CHARCOAL_2};
    color: {FG_TEXT};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 4px;
    font-size: 13px;
}}
QHeaderView::section {{
    background: {BG_HEADER};
    color: {FG_MUTED};
    border: none;
    padding: 4px 8px;
    font-weight: 700;
}}
QScrollBar:vertical {{
    background: {BG_CHARCOAL_2};
    width: 10px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {BORDER_LIGHT};
    min-height: 24px;
    border-radius: 5px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QScrollBar:horizontal {{
    background: {BG_CHARCOAL_2};
    height: 10px;
}}
QScrollBar::handle:horizontal {{
    background: {BORDER_LIGHT};
    min-width: 24px;
    border-radius: 5px;
}}
QStackedWidget {{
    background: {BG_CHARCOAL};
    border: none;
}}
QLabel#DirtyMarker {{
    color: {AMBER_WARN};
    font-weight: 700;
    padding-left: 6px;
}}
QLabel#FieldError {{
    color: {RED_FAULT};
    font-size: 12px;
}}
QLabel#Banner {{
    padding: 6px 10px;
    border-radius: 6px;
    font-weight: 700;
    font-size: 13px;
}}
QLabel#Banner.info {{
    background: {ACCENT_BLUE};
    color: white;
}}
QLabel#Banner.warn {{
    background: {AMBER_WARN};
    color: #1a1a1a;
}}
QLabel#Banner.fault {{
    background: {RED_FAULT};
    color: white;
}}
QLabel#Banner.ok {{
    background: {GREEN_OK_DIM};
    color: white;
}}
QFrame#Divider {{
    background: {BORDER};
    max-height: 1px;
    min-height: 1px;
    border: none;
}}
QLabel#Lamp {{
    min-width: 16px;
    min-height: 16px;
    max-width: 16px;
    max-height: 16px;
    border-radius: 8px;
    background: {FG_DIM};
}}
QLabel#Lamp.on-green {{ background: {GREEN_OK}; }}
QLabel#Lamp.on-amber {{ background: {AMBER_WARN}; }}
QLabel#Lamp.on-red {{ background: {RED_FAULT}; }}
QLabel#Lamp.on-blue {{ background: {ACCENT_BLUE}; }}
QWidget#DialogBody {{
    background: {BG_CHARCOAL};
}}
QDialog {{
    background: {BG_CHARCOAL};
}}
QComboBox {{
    background: {BG_INPUT};
    color: {FG_TEXT};
    border: 1px solid {BORDER_LIGHT};
    border-radius: 6px;
    padding: 6px 10px;
    min-height: 40px;
}}
"""


def set_app_fonts(app) -> None:
    base = QFont()
    base.setPointSize(10)
    app.setFont(base)
    app.setStyleSheet(QSS)
