"""Monta a grade de semanas de um mês pra "Visualização Calendário"
(Prompt Mestre, Fase 4, "Alternância entre Kanban/Tabela/Lista/
Calendário"), 2026-08-06. Módulo próprio e reusado por todo board (Leads/
Cases/Traduções/Tarefas/Financial Coaching) -- a matemática de calendário
(quantas semanas, que dia cai em que célula, mês anterior/seguinte) é
sempre a mesma, só o que entra em cada dia muda por board."""
from __future__ import annotations

import calendar
from datetime import date
from typing import Callable, TypeVar

T = TypeVar("T")

WEEKDAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def build_calendar_grid(rows: list[T], date_fn: Callable[[T], date | None], year: int, month: int) -> dict:
    """`date_fn(row)` pode devolver None (item sem data -- fica de fora do
    calendário, mas continua aparecendo nas outras visualizações). Semana
    começa na segunda (mesmo padrão `calendar.Calendar(firstweekday=0)`)."""
    cal = calendar.Calendar(firstweekday=0)
    weeks: list[list[date | None]] = []
    week: list[date | None] = []
    for day in cal.itermonthdates(year, month):
        # itermonthdates preenche a semana inteira mesmo nas pontas (dias
        # do mês anterior/seguinte) pra manter o alinhamento por dia da
        # semana -- viram None aqui (célula vazia), só o dia do mês em
        # questão carrega itens.
        week.append(day if day.month == month else None)
        if len(week) == 7:
            weeks.append(week)
            week = []
    if week:
        weeks.append(week)

    items_by_date: dict[date, list[T]] = {}
    for row in rows:
        d = date_fn(row)
        if d is not None:
            items_by_date.setdefault(d, []).append(row)

    prev_year, prev_month = (year - 1, 12) if month == 1 else (year, month - 1)
    next_year, next_month = (year + 1, 1) if month == 12 else (year, month + 1)

    return {
        "weeks": weeks, "items_by_date": items_by_date,
        "month_label": f"{calendar.month_name[month]} {year}",
        "year": year, "month": month,
        "prev_year": prev_year, "prev_month": prev_month,
        "next_year": next_year, "next_month": next_month,
        "weekday_labels": WEEKDAY_LABELS,
    }
