"""pdf_report.py — 표준 EIR(Equipment Interchange Receipt) 양식 PDF 렌더러.

역할
----
`report_writer` 초안 + 검수 레코드를 **EIR 전표 레이아웃**으로 렌더링한다.
RAG 는 문장(remarks 등)만 보조하고, 양식 구조는 이 모듈이 고정한다.

의존성: fpdf2. Lambda zip 에 한글 TTF(`fonts/`)와 함께 번들.
"""

from __future__ import annotations

import os
from typing import Dict, List, Optional, Tuple

from .record_adapter import normalize_inspection_record

_HERE = os.path.dirname(os.path.abspath(__file__))
_FONT_DIRS = (os.path.join(_HERE, "fonts"),)

_TYPE_KO = {
    "hole": "구멍(Hole)",
    "dent": "찌그러짐(Dent)",
    "rust": "녹/부식(Rust)",
}
_SEV_KO = {
    "low": "경미(Low)",
    "medium": "보통(Medium)",
    "high": "심각(High)",
}
_DECISION_KO = {
    "USABLE": "인수 가능 (Accepted / Usable)",
    "REPAIR_NEEDED": "수리 후 인수 (Repair Required)",
    "REJECT": "인수 불가 (Rejected)",
}


def _find_font() -> Optional[str]:
    env_path = os.getenv("REPORT_FONT_PATH")
    if env_path and os.path.exists(env_path):
        return env_path
    for d in _FONT_DIRS:
        if os.path.isdir(d):
            for name in os.listdir(d):
                if name.lower().endswith(".ttf"):
                    return os.path.join(d, name)
    return None


class _EirForm:
    """테두리 있는 EIR 전표용 fpdf2 래퍼."""

    def __init__(self) -> None:
        from fpdf import FPDF
        from fpdf.enums import XPos, YPos

        self._next = {"new_x": XPos.LMARGIN, "new_y": YPos.NEXT}
        self.pdf = FPDF(format="A4")
        self.pdf.set_margins(12, 12, 12)
        self.pdf.set_auto_page_break(auto=True, margin=12)
        self.pdf.add_page()

        font_path = _find_font()
        if font_path:
            self.pdf.add_font("Report", "", font_path)
            self.family = "Report"
            self.unicode = True
        else:
            print(
                "[pdf_report] 한글 TTF 미발견 → Helvetica 대체. "
                "REPORT_FONT_PATH 로 폰트를 지정하세요."
            )
            self.family = "Helvetica"
            self.unicode = False

        self._page_w = self.pdf.w - self.pdf.l_margin - self.pdf.r_margin

    def _t(self, text: str) -> str:
        if self.unicode:
            return str(text or "")
        return str(text or "").encode("latin-1", "replace").decode("latin-1")

    def banner(self) -> None:
        self.pdf.set_font(self.family, size=16)
        self.pdf.cell(
            self._page_w,
            12,
            self._t("EQUIPMENT INTERCHANGE RECEIPT (EIR)"),
            border=1,
            align="C",
            new_x="LMARGIN",
            new_y="NEXT",
        )
        self.pdf.set_font(self.family, size=9)
        self.pdf.cell(
            self._page_w,
            7,
            self._t("컨테이너 장비 인수·인계 검수 전표"),
            border=1,
            align="C",
            new_x="LMARGIN",
            new_y="NEXT",
        )
        self.pdf.ln(2)

    def section(self, title: str) -> None:
        self.pdf.set_font(self.family, size=10)
        self.pdf.set_fill_color(230, 230, 230)
        self.pdf.cell(
            self._page_w,
            7,
            self._t(title),
            border=1,
            fill=True,
            new_x="LMARGIN",
            new_y="NEXT",
        )

    def row2(self, left: Tuple[str, str], right: Tuple[str, str]) -> None:
        """2열 라벨-값 행."""
        half = self._page_w / 2
        lw = half * 0.38
        vw = half * 0.62
        self.pdf.set_font(self.family, size=9)
        y0 = self.pdf.get_y()
        x0 = self.pdf.l_margin

        self.pdf.set_xy(x0, y0)
        self.pdf.cell(lw, 8, self._t(left[0]), border=1)
        self.pdf.cell(vw, 8, self._t(left[1]), border=1)

        self.pdf.set_xy(x0 + half, y0)
        self.pdf.cell(lw, 8, self._t(right[0]), border=1)
        self.pdf.cell(vw, 8, self._t(right[1]), border=1)
        self.pdf.set_xy(x0, y0 + 8)

    def row1(self, label: str, value: str, label_w: float = 40) -> None:
        self.pdf.set_font(self.family, size=9)
        line_h = 5.0
        pad = 1.2
        vw = self._page_w - label_w
        text_w = max(10.0, vw - 2 * pad)
        body = self._t(value or "-")
        text_h = self._text_height(body, text_w, line_h)
        h = max(8.0, text_h + 2 * pad)
        x0 = self.pdf.l_margin
        self._ensure_space(h)
        y0 = self.pdf.get_y()

        self.pdf.rect(x0, y0, label_w, h)
        self.pdf.rect(x0 + label_w, y0, vw, h)
        self.pdf.set_xy(x0, y0 + (h - line_h) / 2)
        self.pdf.cell(label_w, line_h, self._t(label), border=0, align="C")
        self.pdf.set_xy(x0 + label_w + pad, y0 + pad)
        self.pdf.multi_cell(text_w, line_h, body, border=0)
        self.pdf.set_xy(x0, y0 + h)

    def _ensure_space(self, h: float) -> None:
        """남은 페이지 높이가 부족하면 새 페이지."""
        if self.pdf.get_y() + h > self.pdf.page_break_trigger:
            self.pdf.add_page()

    def _text_height(self, text: str, width: float, line_h: float) -> float:
        """multi_cell 높이 측정 (그리기 없음)."""
        body = text if text else "-"
        try:
            return float(
                self.pdf.multi_cell(
                    width,
                    line_h,
                    body,
                    border=0,
                    dry_run=True,
                    output="HEIGHT",
                )
            )
        except TypeError:
            return self._estimate_height(body, width, line_h)

    def _estimate_height(self, text: str, width: float, line_h: float) -> float:
        if not text:
            return line_h
        lines = 1
        cur = 0.0
        for ch in text:
            if ch == "\n":
                lines += 1
                cur = 0.0
                continue
            w = self.pdf.get_string_width(ch)
            if cur + w > width and cur > 0:
                lines += 1
                cur = w
            else:
                cur += w
        return lines * line_h

    def multiline(self, label: str, text: str, min_h: float = 20) -> None:
        """라벨+값 멀티라인 칸. 긴 텍스트도 칸 안에 줄바꿈·높이 맞춤."""
        self.pdf.set_font(self.family, size=9)
        label_w = 40.0
        pad = 2.0
        line_h = 5.0
        val_w = self._page_w - label_w
        text_w = max(10.0, val_w - 2 * pad)
        x0 = self.pdf.l_margin
        body = self._t(text or "-")

        text_h = self._text_height(body, text_w, line_h)
        h = max(min_h, text_h + 2 * pad)
        self._ensure_space(h)
        y0 = self.pdf.get_y()

        # 테두리만 먼저 (텍스트는 한 번만 그림 → 겹침/넘침 방지)
        self.pdf.rect(x0, y0, label_w, h)
        self.pdf.rect(x0 + label_w, y0, val_w, h)

        self.pdf.set_xy(x0, y0 + max(0.0, (h - line_h) / 2))
        self.pdf.cell(label_w, line_h, self._t(label), border=0, align="C")

        self.pdf.set_xy(x0 + label_w + pad, y0 + pad)
        self.pdf.multi_cell(text_w, line_h, body, border=0)
        self.pdf.set_xy(x0, y0 + h)

    def table_header(self, cols: List[Tuple[str, float]]) -> None:
        self.pdf.set_font(self.family, size=9)
        self.pdf.set_fill_color(240, 240, 240)
        for title, w in cols:
            self.pdf.cell(w, 7, self._t(title), border=1, fill=True, align="C")
        self.pdf.ln()

    def table_row(self, cols: List[Tuple[str, float]]) -> None:
        """긴 Description 도 칸 안에서 줄바꿈."""
        self.pdf.set_font(self.family, size=8)
        line_h = 4.2
        pad = 1.0
        x0 = self.pdf.l_margin

        heights: List[float] = []
        bodies: List[str] = []
        for text, w in cols:
            body = self._t(text)
            bodies.append(body)
            heights.append(
                max(
                    line_h + 2 * pad,
                    self._text_height(body, max(8.0, w - 2 * pad), line_h) + 2 * pad,
                )
            )
        h = max(heights)
        self._ensure_space(h)
        y0 = self.pdf.get_y()

        x = x0
        for body, (_, w) in zip(bodies, cols):
            self.pdf.rect(x, y0, w, h)
            self.pdf.set_xy(x + pad, y0 + pad)
            self.pdf.multi_cell(max(8.0, w - 2 * pad), line_h, body, border=0)
            x += w
        self.pdf.set_xy(x0, y0 + h)

    def check_line(self, label: str, checked: bool) -> None:
        mark = "[X]" if checked else "[ ]"
        self.pdf.set_font(self.family, size=9)
        self.pdf.cell(
            self._page_w,
            7,
            self._t(f"  {mark}  {label}"),
            border=1,
            new_x="LMARGIN",
            new_y="NEXT",
        )

    def output(self) -> bytes:
        return bytes(self.pdf.output())


def _fmt_result_types(detections: List[Dict]) -> str:
    seen = []
    for d in detections or []:
        label = str(d.get("class") or d.get("damage_class") or "").strip().lower()
        if label and label not in seen:
            seen.append(label)
    if not seen:
        return "NONE"
    return ", ".join(_TYPE_KO.get(x, x) for x in seen)


def _condition(detections: List[Dict]) -> str:
    return "DAMAGE" if detections else "NO DAMAGE"


def build_report_pdf(record: Dict, report: Dict) -> bytes:
    """검수 레코드 + 초안을 EIR 전표 양식으로 렌더링한다."""
    record = normalize_inspection_record(record)
    detections = record.get("detections") or []
    decision = str(report.get("reuse_decision") or "USABLE").upper()
    remarks = "\n".join(
        p
        for p in [
            str(report.get("summary") or "").strip(),
            str(report.get("damage_assessment") or "").strip(),
            str(report.get("recommended_action") or "").strip(),
            str(report.get("reuse_reason") or "").strip(),
        ]
        if p
    ) or "-"

    f = _EirForm()
    w = f._page_w

    # --- Header ---
    f.banner()

    # --- Equipment / Interchange ---
    f.section("1. EQUIPMENT / INTERCHANGE INFORMATION")
    f.row2(
        ("Equipment No.", str(record.get("container_id") or "-")),
        ("Reference No.", str(record.get("event_id") or "-")),
    )
    f.row2(
        ("Date / Time In", str(record.get("captured_at") or "-")),
        ("Processed At", str(record.get("processed_at") or "-")),
    )
    f.row2(
        ("Equipment Condition", _condition(detections)),
        ("Damage Types", _fmt_result_types(detections)),
    )
    f.row2(
        ("Risk Level", str(record.get("risk_level") or "-")),
        ("Risk Score", str(record.get("risk_score") or "-")),
    )

    # --- Condition checkboxes (EIR style) ---
    f.section("2. CONDITION AT INTERCHANGE")
    f.check_line("NO DAMAGE — 손상 없음, 정상 인수 가능", not bool(detections))
    f.check_line("DAMAGE — 손상 확인됨 (하단 상세 기록)", bool(detections))

    # --- Damage table ---
    f.section("3. DAMAGE DESCRIPTION")
    cols = [
        ("No.", w * 0.08),
        ("Type", w * 0.18),
        ("Severity", w * 0.18),
        ("Location", w * 0.20),
        ("Description", w * 0.36),
    ]
    f.table_header(cols)
    if not detections:
        f.table_row(
            [
                ("-", cols[0][1]),
                ("NONE", cols[1][1]),
                ("-", cols[2][1]),
                ("-", cols[3][1]),
                ("탐지된 손상 없음", cols[4][1]),
            ]
        )
    else:
        for i, d in enumerate(detections, 1):
            raw = str(d.get("class") or "?").lower()
            sev = str(d.get("severity") or "?").lower()
            desc = str(d.get("description") or d.get("note") or "-")
            f.table_row(
                [
                    (str(i), cols[0][1]),
                    (_TYPE_KO.get(raw, raw), cols[1][1]),
                    (_SEV_KO.get(sev, sev), cols[2][1]),
                    (str(d.get("location") or "-"), cols[3][1]),
                    (desc, cols[4][1]),
                ]
            )

    # --- Remarks ---
    f.section("4. REMARKS / INSPECTOR COMMENTS")
    f.multiline("Remarks", remarks, min_h=28)

    # --- Disposition ---
    f.section("5. DISPOSITION / ACCEPTANCE")
    f.row1("Decision", _DECISION_KO.get(decision, decision), label_w=40)
    f.check_line("USABLE — 추가 조치 없이 재사용/인수 가능", decision == "USABLE")
    f.check_line(
        "REPAIR NEEDED — 수리 후 재사용", decision == "REPAIR_NEEDED"
    )
    f.check_line("REJECTED — 사용 불가 / 반출·정비 필요", decision == "REJECT")

    # --- Sign-off ---
    f.section("6. ACKNOWLEDGEMENT")
    f.row2(("Inspected By", "AI Cloud Inspection"), ("Date", str(record.get("processed_at") or "-")))
    f.row2(("Received By", "____________________"), ("Signature", "____________________"))

    return f.output()
