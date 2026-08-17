"""
PDF report builder shared by the four use-case scripts.

Each report documents a task three ways, in the order the brief asks for:
the requirement restated in plain English, the exact code that was run, and
the real captured output (console text and/or the generated chart).

The code shown in the PDF is the code that produced the output: `Report.step`
executes the source string it prints, so the two can never drift apart.
"""
from __future__ import annotations

import contextlib
import io
import sys
import textwrap
import traceback
from datetime import datetime
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (BaseDocTemplate, Frame, HRFlowable, Image,
                                KeepTogether, PageBreak, PageTemplate,
                                Paragraph, Preformatted, Spacer, Table,
                                TableStyle)

# --------------------------------------------------------------------------- #
# Palette
# --------------------------------------------------------------------------- #
NAVY = colors.HexColor("#12263F")
ACCENT = colors.HexColor("#2A6F97")
LIGHT = colors.HexColor("#EEF3F8")
CODE_BG = colors.HexColor("#F5F7FA")
CODE_BORDER = colors.HexColor("#D7DEE7")
OUT_BG = colors.HexColor("#1E2A38")
MUTED = colors.HexColor("#5A6B7C")

PAGE_W, PAGE_H = A4
MARGIN = 18 * mm
CONTENT_W = PAGE_W - 2 * MARGIN


def _styles():
    ss = getSampleStyleSheet()
    s = {
        "title": ParagraphStyle("t", parent=ss["Title"], fontName="Helvetica-Bold",
                                fontSize=26, leading=31, textColor=NAVY, spaceAfter=6),
        "subtitle": ParagraphStyle("st", parent=ss["Normal"], fontName="Helvetica",
                                   fontSize=12.5, leading=18, textColor=MUTED,
                                   alignment=TA_CENTER),
        "h1": ParagraphStyle("h1", parent=ss["Heading1"], fontName="Helvetica-Bold",
                             fontSize=15, leading=20, textColor=colors.white,
                             backColor=NAVY, borderPadding=(7, 9, 7, 9),
                             spaceBefore=16, spaceAfter=10, keepWithNext=1),
        "h2": ParagraphStyle("h2", parent=ss["Heading2"], fontName="Helvetica-Bold",
                             fontSize=12, leading=16, textColor=ACCENT,
                             spaceBefore=12, spaceAfter=5, keepWithNext=1),
        "body": ParagraphStyle("b", parent=ss["Normal"], fontName="Helvetica",
                               fontSize=9.8, leading=14.5, textColor=colors.HexColor("#22303F"),
                               alignment=TA_JUSTIFY, spaceAfter=6),
        "label": ParagraphStyle("l", parent=ss["Normal"], fontName="Helvetica-Bold",
                                fontSize=8, leading=11, textColor=MUTED, spaceAfter=3),
        "caption": ParagraphStyle("c", parent=ss["Normal"], fontName="Helvetica-Oblique",
                                  fontSize=8.5, leading=12, textColor=MUTED,
                                  alignment=TA_CENTER, spaceBefore=4, spaceAfter=8),
        "code": ParagraphStyle("code", fontName="Courier", fontSize=7.6, leading=10.2,
                               textColor=colors.HexColor("#1B2B3A")),
        "out": ParagraphStyle("out", fontName="Courier", fontSize=7.2, leading=9.8,
                              textColor=colors.HexColor("#E6EDF3")),
        "insight": ParagraphStyle("i", parent=ss["Normal"], fontName="Helvetica",
                                  fontSize=9.8, leading=14.5, textColor=NAVY,
                                  alignment=TA_JUSTIFY),
    }
    return s


class Report:
    """Accumulates flowables, then renders a paginated PDF."""

    def __init__(self, number: int, title: str, objective: str, backend: str = ""):
        self.number = number
        self.title = title
        self.objective = objective
        self.backend = backend
        self.s = _styles()
        self.story: list = []
        self.env: dict = {}
        self._toc: list[str] = []

    # -- content ---------------------------------------------------------- #
    def section(self, heading: str):
        self._toc.append(heading)
        self.story.append(Paragraph(heading, self.s["h1"]))
        return self

    def sub(self, heading: str):
        self.story.append(Paragraph(heading, self.s["h2"]))
        return self

    def text(self, body: str):
        self.story.append(Paragraph(textwrap.dedent(body).strip(), self.s["body"]))
        return self

    def requirement(self, body: str):
        """The task as stated in the brief, restated in our own words."""
        tbl = Table([[Paragraph(f"<b>What is being asked:</b> {textwrap.dedent(body).strip()}",
                                self.s["body"])]], colWidths=[CONTENT_W])
        tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), LIGHT),
            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#C9D6E3")),
            ("LEFTPADDING", (0, 0), (-1, -1), 9), ("RIGHTPADDING", (0, 0), (-1, -1), 9),
            ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ("LINEBEFORE", (0, 0), (0, -1), 3, ACCENT),
        ]))
        self.story.append(tbl)
        self.story.append(Spacer(1, 8))
        return self

    def insight(self, body: str):
        """A conclusion the CPD can act on."""
        tbl = Table([[Paragraph(f"<b>Insight &nbsp;&rarr;</b> {textwrap.dedent(body).strip()}",
                                self.s["insight"])]], colWidths=[CONTENT_W])
        tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FFF7E6")),
            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#E8C77A")),
            ("LEFTPADDING", (0, 0), (-1, -1), 9), ("RIGHTPADDING", (0, 0), (-1, -1), 9),
            ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ("LINEBEFORE", (0, 0), (0, -1), 3, colors.HexColor("#E0A800")),
        ]))
        self.story.append(tbl)
        self.story.append(Spacer(1, 9))
        return self

    def _code_flowable(self, code: str, label: str = "CODE"):
        code = textwrap.dedent(code).strip("\n")
        body = Preformatted(_wrap_mono(code, 108), self.s["code"])
        tbl = Table([[Paragraph(label, self.s["label"])], [body]], colWidths=[CONTENT_W])
        tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), CODE_BG),
            ("BOX", (0, 0), (-1, -1), 0.5, CODE_BORDER),
            ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (0, 0), 6), ("BOTTOMPADDING", (0, -1), (-1, -1), 8),
        ]))
        return tbl

    def _output_flowable(self, out: str, label: str = "OUTPUT"):
        out = (out or "").rstrip() or "(no console output)"
        body = Preformatted(_wrap_mono(out, 112), self.s["out"])
        tbl = Table([[Paragraph(f'<font color="#8FA9C2">{label}</font>', self.s["label"])],
                     [body]], colWidths=[CONTENT_W])
        tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), OUT_BG),
            ("BOX", (0, 0), (-1, -1), 0.5, OUT_BG),
            ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (0, 0), 6), ("BOTTOMPADDING", (0, -1), (-1, -1), 8),
        ]))
        return tbl

    def code_block(self, code: str, label: str = "CODE"):
        self.story.append(self._code_flowable(code, label))
        self.story.append(Spacer(1, 6))
        return self

    def output_block(self, out: str, label: str = "OUTPUT"):
        self.story.append(self._output_flowable(out, label))
        self.story.append(Spacer(1, 10))
        return self

    def figure(self, path, caption: str = "", width_frac: float = 1.0):
        path = Path(path)
        if not path.exists():
            return self
        from PIL import Image as PILImage  # bundled with matplotlib deps
        with PILImage.open(path) as im:
            iw, ih = im.size
        w = CONTENT_W * width_frac
        h = w * ih / iw
        max_h = PAGE_H - 2 * MARGIN - 40 * mm
        if h > max_h:
            h, w = max_h, max_h * iw / ih
        block = [Image(str(path), width=w, height=h, hAlign="CENTER")]
        if caption:
            block.append(Paragraph(caption, self.s["caption"]))
        self.story.append(KeepTogether(block))
        self.story.append(Spacer(1, 4))
        return self

    def table(self, df, caption: str = "", max_rows: int = 18, col_widths=None):
        """Render a DataFrame as a styled table."""
        d = df.head(max_rows).copy()
        header = [str(c).replace("_", " ").title() for c in d.columns]
        rows = [header] + [[_fmt(v) for v in r] for r in d.itertuples(index=False)]
        tbl = Table(rows, colWidths=col_widths or [CONTENT_W / len(header)] * len(header),
                    repeatRows=1)
        tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), NAVY),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
            ("FONTSIZE", (0, 0), (-1, -1), 7.5),
            ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
            ("GRID", (0, 0), (-1, -1), 0.25, CODE_BORDER),
            ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        block = [tbl]
        if caption:
            block.append(Paragraph(caption, self.s["caption"]))
        self.story.append(KeepTogether(block))
        self.story.append(Spacer(1, 8))
        return self

    def page_break(self):
        self.story.append(PageBreak())
        return self

    # -- execution -------------------------------------------------------- #
    def step(self, code: str, echo: bool = True, label: str = "CODE",
             out_label: str = "OUTPUT", show_output: bool = True) -> str:
        """
        Execute `code` against the report's shared namespace, capture stdout,
        and document both in the PDF.  Returns the captured output.
        """
        code = textwrap.dedent(code).strip("\n")
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                exec(compile(code, f"<usecase{self.number}>", "exec"), self.env)
        except Exception:
            buf.write("\n" + traceback.format_exc())
            print(f"!! step failed in Use Case {self.number}:\n{code}\n"
                  f"{traceback.format_exc()}", file=sys.stderr)
        out = buf.getvalue()

        # Keep a short code/output pair on one page; let long ones flow.
        block = []
        if echo:
            block.append(self._code_flowable(code, label))
            block.append(Spacer(1, 6))
        if show_output:
            block.append(self._output_flowable(out, out_label))
        total_lines = (len(code.splitlines()) if echo else 0) + \
                      (len(out.splitlines()) if show_output else 0)
        if total_lines <= 34:
            self.story.append(KeepTogether(block))
        else:
            self.story.extend(block)
        self.story.append(Spacer(1, 10))

        if out.strip():
            print(out.rstrip())
        return out

    # -- render ----------------------------------------------------------- #
    def _cover(self):
        s = self.s
        cover = [
            Spacer(1, 42 * mm),
            Paragraph("CHICAGO POLICE DEPARTMENT &middot; CRIME DATA ANALYTICS",
                      ParagraphStyle("k", parent=s["subtitle"], fontSize=9.5,
                                     textColor=ACCENT, spaceAfter=14)),
            Paragraph(f"Use Case {self.number}", ParagraphStyle(
                "n", parent=s["subtitle"], fontSize=13, textColor=MUTED, spaceAfter=6)),
            Paragraph(self.title, s["title"]),
            Spacer(1, 4),
            HRFlowable(width="42%", thickness=2, color=ACCENT, spaceAfter=16,
                       hAlign="CENTER"),
            Paragraph(f"<b>Objective</b> &nbsp;&middot;&nbsp; {self.objective}", s["subtitle"]),
            Spacer(1, 26 * mm),
        ]
        meta = [["Prepared for", "Chicago Police Department"],
                ["Prepared by", "Accenture — Python Full Stack Program"],
                ["Data source", "chicago_crime_dataset.csv + 4 reference files"],
                ["Toolchain", "Python · Pandas · NumPy · Matplotlib · Seaborn"],
                ["Warehouse", self.backend or "SQLite3 / MySQL"],
                ["Generated", datetime.now().strftime("%d %B %Y, %H:%M")]]
        t = Table(meta, colWidths=[45 * mm, CONTENT_W - 45 * mm])
        t.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
            ("FONTNAME", (1, 0), (1, -1), "Helvetica"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("TEXTCOLOR", (0, 0), (0, -1), MUTED),
            ("TEXTCOLOR", (1, 0), (1, -1), NAVY),
            ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, LIGHT]),
            ("LINEBELOW", (0, 0), (-1, -2), 0.25, CODE_BORDER),
            ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ]))
        cover += [t, PageBreak()]
        return cover

    def _decorate(self, canvas, doc):
        canvas.saveState()
        if doc.page > 1:
            canvas.setFillColor(NAVY)
            canvas.rect(0, PAGE_H - 12 * mm, PAGE_W, 12 * mm, stroke=0, fill=1)
            canvas.setFont("Helvetica-Bold", 8)
            canvas.setFillColor(colors.white)
            canvas.drawString(MARGIN, PAGE_H - 8 * mm,
                              f"USE CASE {self.number} — {self.title.upper()}")
            canvas.setFont("Helvetica", 8)
            canvas.drawRightString(PAGE_W - MARGIN, PAGE_H - 8 * mm,
                                   "Chicago Crime Data Analytics")
            canvas.setStrokeColor(CODE_BORDER)
            canvas.setLineWidth(0.5)
            canvas.line(MARGIN, 13 * mm, PAGE_W - MARGIN, 13 * mm)
            canvas.setFont("Helvetica", 7.5)
            canvas.setFillColor(MUTED)
            canvas.drawString(MARGIN, 9 * mm, "Accenture · CPD Crime Data Analytics")
            canvas.drawRightString(PAGE_W - MARGIN, 9 * mm, f"Page {doc.page - 1}")
        canvas.restoreState()

    def build(self, path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        doc = BaseDocTemplate(str(path), pagesize=A4,
                              leftMargin=MARGIN, rightMargin=MARGIN,
                              topMargin=MARGIN, bottomMargin=MARGIN,
                              title=f"Use Case {self.number} — {self.title}",
                              author="Accenture — Python Full Stack Program")
        cover_frame = Frame(MARGIN, MARGIN, CONTENT_W, PAGE_H - 2 * MARGIN, id="cover")
        body_frame = Frame(MARGIN, MARGIN + 6 * mm, CONTENT_W,
                           PAGE_H - 2 * MARGIN - 12 * mm, id="body")
        doc.addPageTemplates([
            PageTemplate(id="cover", frames=[cover_frame], onPage=self._decorate),
            PageTemplate(id="body", frames=[body_frame], onPage=self._decorate),
        ])
        doc.build(self._cover() + self.story)
        return path


# --------------------------------------------------------------------------- #
def _wrap_mono(text: str, width: int) -> str:
    """Hard-wrap monospace text so nothing runs off the page."""
    lines = []
    for line in text.expandtabs(4).splitlines():
        if len(line) <= width:
            lines.append(line)
        else:
            indent = " " * (len(line) - len(line.lstrip()) + 2)
            chunks = textwrap.wrap(line, width=width, subsequent_indent=indent,
                                   break_long_words=True, break_on_hyphens=False,
                                   drop_whitespace=False)
            lines.extend(chunks or [line])
    return "\n".join(lines)


def _fmt(v) -> str:
    import numpy as np
    import pandas as pd
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    if isinstance(v, (float, np.floating)):
        return f"{v:,.2f}"
    if isinstance(v, (int, np.integer)):
        return f"{v:,}"
    return str(v)
