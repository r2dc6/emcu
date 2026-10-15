from __future__ import annotations

import math
from typing import Dict, List, Optional

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..constants import EVENT_KIND_ACU, EVENT_KIND_ALARM, EVENT_KIND_SYSTEM
from ..system_state import SystemState
from ..widgets import large_button


_FILTER_KIND_MAP: Dict[str, Optional[set]] = {
    "ALL": None,
    "ACU": EVENT_KIND_ACU,
    "ALARM": EVENT_KIND_ALARM,
    "SYSTEM": EVENT_KIND_SYSTEM,
}


class LogsPage(QWidget):
    request_events = Signal(int)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("ContentPage")

        self._all_rows: List[dict] = []
        self._filtered_rows: List[dict] = []
        self._page: int = 0
        self._page_size: int = 40
        self._current_filter: str = "ALL"
        self._backend_online: bool = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 10, 12, 10)
        outer.setSpacing(8)

        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(4, 0, 4, 0)
        toolbar.setSpacing(4)

        filter_group_container = QWidget(self)
        filter_group_layout = QHBoxLayout(filter_group_container)
        filter_group_layout.setContentsMargins(0, 0, 0, 0)
        filter_group_layout.setSpacing(4)

        self._filter_group = QButtonGroup(self)
        self._filter_group.setExclusive(True)

        self._btn_all = self._make_filter_btn(
            "ALL", "logs_filter_all", 72, filter_group_container
        )
        self._btn_all.setChecked(True)
        self._filter_group.addButton(self._btn_all, 0)
        filter_group_layout.addWidget(self._btn_all)

        self._btn_acu = self._make_filter_btn(
            "ACU", "logs_filter_acu", 72, filter_group_container
        )
        self._filter_group.addButton(self._btn_acu, 1)
        filter_group_layout.addWidget(self._btn_acu)

        self._btn_alarm = self._make_filter_btn(
            "ALARM", "logs_filter_alarm", 80, filter_group_container
        )
        self._filter_group.addButton(self._btn_alarm, 2)
        filter_group_layout.addWidget(self._btn_alarm)

        self._btn_system = self._make_filter_btn(
            "SYSTEM", "logs_filter_system", 88, filter_group_container
        )
        self._filter_group.addButton(self._btn_system, 3)
        filter_group_layout.addWidget(self._btn_system)

        self._btn_all.clicked.connect(lambda: self._set_filter("ALL"))
        self._btn_acu.clicked.connect(lambda: self._set_filter("ACU"))
        self._btn_alarm.clicked.connect(lambda: self._set_filter("ALARM"))
        self._btn_system.clicked.connect(lambda: self._set_filter("SYSTEM"))

        toolbar.addWidget(filter_group_container)
        toolbar.addStretch(1)

        self._refresh_btn = large_button("\u27F3 REFRESH", variant="primary")
        self._refresh_btn.setObjectName("logs_refresh_btn")
        self._refresh_btn.setMinimumWidth(100)
        self._refresh_btn.clicked.connect(self._on_refresh)
        toolbar.addWidget(self._refresh_btn)

        self._prev_btn = QPushButton("\u25C0 PREV", self)
        self._prev_btn.setObjectName("logs_prev_btn")
        self._prev_btn.setMinimumSize(72, 48)
        self._prev_btn.clicked.connect(self._on_prev_page)
        toolbar.addWidget(self._prev_btn)

        self._page_label = QLabel("Page 1 / 1", self)
        self._page_label.setObjectName("logs_page_label")
        self._page_label.setStyleSheet(
            "font-size: 13px; font-weight: 700; color: #e6ecf2; padding: 0 8px;"
        )
        self._page_label.setAlignment(Qt.AlignCenter)
        self._page_label.setMinimumWidth(80)
        toolbar.addWidget(self._page_label)

        self._next_btn = QPushButton("NEXT \u25B6", self)
        self._next_btn.setObjectName("logs_next_btn")
        self._next_btn.setMinimumSize(72, 48)
        self._next_btn.clicked.connect(self._on_next_page)
        toolbar.addWidget(self._next_btn)

        toolbar_wrap = QWidget(self)
        toolbar_wrap.setLayout(toolbar)
        toolbar_wrap.setFixedHeight(68)
        outer.addWidget(toolbar_wrap)

        self._table = QTableWidget(0, 3, self)
        self._table.setObjectName("logs_table")
        self._table.setHorizontalHeaderLabels(["Timestamp", "Category", "Message"])
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setSelectionMode(QAbstractItemView.NoSelection)
        self._table.setFocusPolicy(Qt.NoFocus)
        self._table.setAlternatingRowColors(True)
        self._table.setShowGrid(False)
        self._table.verticalHeader().setVisible(False)
        self._table.verticalHeader().setDefaultSectionSize(22)
        self._table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        header.setSectionResizeMode(1, QHeaderView.Fixed)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        self._table.setColumnWidth(0, 180)
        self._table.setColumnWidth(1, 90)

        small_font = QFont()
        small_font.setPointSize(10)
        self._table.setFont(small_font)

        outer.addWidget(self._table, 1)

        self._refresh_nav_buttons()

    @staticmethod
    def _on_filter_toggled(btn: QPushButton, checked: bool) -> None:
        if checked:
            btn.setStyleSheet(
                "QPushButton {"
                "  background: #3a8fd6;"
                "  color: white;"
                "  border: 1px solid #57a7ea;"
                "  border-radius: 6px;"
                "  padding: 8px 14px;"
                "  font-size: 14px;"
                "  font-weight: 600;"
                "}"
            )
        else:
            btn.setStyleSheet("")

    def _make_filter_btn(
        self, text: str, obj_name: str, min_width: int, parent: QWidget
    ) -> QPushButton:
        btn = QPushButton(text, parent)
        btn.setObjectName(obj_name)
        btn.setCheckable(True)
        btn.setFlat(True)
        btn.setMinimumSize(min_width, 48)
        btn.toggled.connect(lambda c, b=btn: self._on_filter_toggled(b, c))
        self._on_filter_toggled(btn, btn.isChecked())
        return btn

    def _set_filter(self, filter_key: str) -> None:
        self._current_filter = filter_key
        self._apply_filter()
        self._page = 0
        self._refresh_view()
        self._refresh_nav_buttons()

    def _apply_filter(self) -> None:
        kind_set = _FILTER_KIND_MAP.get(self._current_filter)
        if kind_set is None:
            self._filtered_rows = list(self._all_rows)
        else:
            self._filtered_rows = [
                r for r in self._all_rows if r.get("kind") in kind_set
            ]

    def _total_pages(self) -> int:
        if not self._filtered_rows:
            return 1
        return max(1, math.ceil(len(self._filtered_rows) / self._page_size))

    def _refresh_nav_buttons(self) -> None:
        total_pages = self._total_pages()
        first_page = self._page <= 0
        last_page = self._page >= total_pages - 1
        self._prev_btn.setEnabled(not first_page)
        self._next_btn.setEnabled(not last_page)
        self._page_label.setText(f"Page {self._page + 1} / {total_pages}")

    def _on_refresh(self) -> None:
        self.request_events.emit(500)

    def _on_prev_page(self) -> None:
        if self._page > 0:
            self._page -= 1
            self._refresh_view()
            self._refresh_nav_buttons()

    def _on_next_page(self) -> None:
        total_pages = self._total_pages()
        if self._page < total_pages - 1:
            self._page += 1
            self._refresh_view()
            self._refresh_nav_buttons()

    def _refresh_view(self) -> None:
        self._table.setRowCount(0)
        start = self._page * self._page_size
        end = start + self._page_size
        page_rows = self._filtered_rows[start:end]

        for idx, row in enumerate(page_rows):
            self._table.insertRow(idx)

            ts_val = row.get("ts", "")
            ts_item = QTableWidgetItem(str(ts_val))
            ts_item.setFlags(ts_item.flags() & ~Qt.ItemIsEditable)
            ts_item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            self._table.setItem(idx, 0, ts_item)

            kind_val = row.get("kind", "")
            kind_item = QTableWidgetItem(str(kind_val))
            kind_item.setFlags(kind_item.flags() & ~Qt.ItemIsEditable)
            kind_item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            self._table.setItem(idx, 1, kind_item)

            detail_val = row.get("detail", "")
            detail_item = QTableWidgetItem(str(detail_val))
            detail_item.setFlags(detail_item.flags() & ~Qt.ItemIsEditable)
            detail_item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            self._table.setItem(idx, 2, detail_item)

    def refresh(self) -> None:
        self.request_events.emit(500)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._backend_online:
            self.refresh()

    @Slot(list)
    def update_events(self, rows: list) -> None:
        self._all_rows = list(rows) if rows is not None else []
        self._apply_filter()
        self._page = 0
        self._refresh_view()
        self._refresh_nav_buttons()

    @Slot(object)
    def update_state(self, state: SystemState) -> None:
        was_online = self._backend_online
        self._backend_online = state.backend_online
        self._refresh_btn.setEnabled(state.backend_online)
