"""Relatório mensal de alertas em PDF (resumo + fotos)."""

from __future__ import annotations

import io
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime

from fpdf import FPDF
from PIL import Image

from vigia.hub.store import StoredEvent

MONTHS = [
    "janeiro", "fevereiro", "março", "abril", "maio", "junho",
    "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
]  # fmt: skip
KIND_LABEL = {
    "loitering": "Permanência",
    "door": "Porta",
    "vehicle": "Moto",
    "violence": "Violência",
    "face_known": "Rosto conhecido",
}
SEVERITY_LABEL = {"info": "Info", "alerta": "Alerta", "critico": "Crítico"}
PERIODS = [("Madrugada (0h-6h)", 0, 6), ("Manhã (6h-12h)", 6, 12),
           ("Tarde (12h-18h)", 12, 18), ("Noite (18h-24h)", 18, 24)]  # fmt: skip


def previous_month(today: date) -> tuple[int, int]:
    return (today.year - 1, 12) if today.month == 1 else (today.year, today.month - 1)


def month_bounds(year: int, month: int) -> tuple[float, float]:
    """Início e fim do mês em horário local, como timestamps."""
    start = datetime(year, month, 1)
    end = datetime(year + 1, 1, 1) if month == 12 else datetime(year, month + 1, 1)
    return start.timestamp(), end.timestamp()


def month_label(year: int, month: int) -> str:
    return f"{MONTHS[month - 1]}/{year}"


@dataclass
class Summary:
    total: int
    by_kind: Counter
    by_zone: Counter
    by_severity: Counter
    by_period: dict[str, int]
    top_days: list[tuple[str, int]]


def summarize(events: list[StoredEvent]) -> Summary:
    hours = [datetime.fromtimestamp(e.timestamp).hour for e in events]
    days = Counter(datetime.fromtimestamp(e.timestamp).strftime("%d/%m") for e in events)
    return Summary(
        total=len(events),
        by_kind=Counter(KIND_LABEL.get(e.kind, e.kind) for e in events),
        by_zone=Counter(e.zone or "-" for e in events),
        by_severity=Counter(SEVERITY_LABEL.get(e.severity, e.severity) for e in events),
        by_period={name: sum(lo <= h < hi for h in hours) for name, lo, hi in PERIODS},
        top_days=days.most_common(5),
    )


def report_caption(summary: Summary, year: int, month: int) -> str:
    """Texto curto que acompanha o PDF no Telegram/WhatsApp."""
    lines = [f"📊 Relatório de alertas de {month_label(year, month)}"]
    if summary.total == 0:
        lines.append("Nenhum alerta no mês. 👍")
        return "\n".join(lines)
    lines.append(f"Total: {summary.total} alerta(s)")
    lines += [f"• {k}: {n}" for k, n in summary.by_kind.most_common()]
    busiest = max(summary.by_period.items(), key=lambda kv: kv[1])
    lines.append(f"Período com mais alertas: {busiest[0]}")
    return "\n".join(lines)


def _latin1(text: str) -> str:
    """As fontes embutidas do PDF só têm Latin-1 (cobre os acentos do PT-BR)."""
    return text.replace("—", "-").encode("latin-1", "replace").decode("latin-1")


def _thumbnail(jpeg: bytes, width: int = 640) -> io.BytesIO:
    img = Image.open(io.BytesIO(jpeg)).convert("RGB")
    if img.width > width:
        img = img.resize((width, round(img.height * width / img.width)))
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=70)
    out.seek(0)
    return out


class _Pdf(FPDF):
    title_text = ""

    def footer(self) -> None:
        self.set_y(-12)
        self.set_font("Helvetica", size=8)
        self.set_text_color(120)
        self.cell(0, 6, _latin1(f"{self.title_text} - página {self.page_no()}"), align="C")


def _table(pdf: FPDF, title: str, rows: list[tuple[str, int]]) -> None:
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 7, _latin1(title), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", size=10)
    for label, n in rows or [("-", 0)]:
        pdf.cell(110, 6, _latin1(label), border="B")
        pdf.cell(25, 6, str(n), border="B", align="R", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)


def build_report_pdf(
    events: list[StoredEvent],
    year: int,
    month: int,
    load_photo: Callable[[StoredEvent], bytes | None],
    max_photos: int = 200,
) -> bytes:
    summary = summarize(events)
    pdf = _Pdf(format="A4")
    pdf.title_text = f"Vigia - {month_label(year, month)}"
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(0, 10, _latin1("Relatório de alertas"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", size=11)
    pdf.set_text_color(90)
    generated = datetime.now().strftime("%d/%m/%Y %H:%M")
    pdf.cell(
        0, 7, _latin1(f"{month_label(year, month)} · gerado em {generated}"),
        new_x="LMARGIN", new_y="NEXT",
    )  # fmt: skip
    pdf.set_text_color(0)
    pdf.ln(4)

    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 9, _latin1(f"Total de alertas: {summary.total}"), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)
    _table(pdf, "Por tipo", summary.by_kind.most_common())
    _table(pdf, "Por zona", summary.by_zone.most_common())
    _table(pdf, "Por severidade", summary.by_severity.most_common())
    _table(pdf, "Por período do dia", list(summary.by_period.items()))
    _table(pdf, "Dias com mais alertas", summary.top_days)

    if not events:
        return bytes(pdf.output())

    pdf.add_page()
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 9, "Alertas", new_x="LMARGIN", new_y="NEXT")
    shown = events[:max_photos]
    if len(events) > max_photos:
        pdf.set_font("Helvetica", "I", 9)
        pdf.cell(
            0, 6, _latin1(f"Mostrando os {max_photos} primeiros de {len(events)} alertas."),
            new_x="LMARGIN", new_y="NEXT",
        )  # fmt: skip

    col_w, gap, img_h, text_h = 90.0, 10.0, 51.0, 12.0
    cell_h = img_h + text_h + 4
    for i, ev in enumerate(shown):
        col = i % 2
        if col == 0 and pdf.get_y() + cell_h > pdf.h - pdf.b_margin:
            pdf.add_page()
        x = pdf.l_margin + col * (col_w + gap)
        y = pdf.get_y()
        photo = load_photo(ev)
        if photo:
            try:
                pdf.image(_thumbnail(photo), x=x, y=y, w=col_w, h=img_h, keep_aspect_ratio=True)
            except Exception:  # foto corrompida não pode impedir o relatório
                photo = None
        if not photo:
            pdf.set_xy(x, y)
            pdf.set_font("Helvetica", "I", 9)
            pdf.cell(col_w, img_h, "(sem foto)", border=1, align="C")
        when = datetime.fromtimestamp(ev.timestamp).strftime("%d/%m %H:%M:%S")
        kind = KIND_LABEL.get(ev.kind, ev.kind)
        pdf.set_xy(x, y + img_h + 1)
        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(col_w, 5, _latin1(f"{when} · {kind} · {ev.zone or '-'}"))
        pdf.set_xy(x, y + img_h + 6)
        pdf.set_font("Helvetica", size=8)
        pdf.multi_cell(col_w, 4, _latin1(ev.message), max_line_height=4)
        pdf.set_xy(pdf.l_margin, y if col == 0 else y + cell_h)
    return bytes(pdf.output())
