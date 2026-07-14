"""pdf_report.py — 검수 보고서(EIR) PDF 렌더러.

역할
----
`report_writer` 가 만든 보고서 섹션 dict 와 원본 검수 레코드를 받아
S3 에 올릴 PDF 바이트를 만든다. 순수 파이썬 라이브러리 `fpdf2` 를 사용한다.

한글 폰트
--------
fpdf2 의 기본 코어 폰트(Helvetica)는 한글을 렌더링하지 못한다. 한글을 제대로
출력하려면 유니코드 TTF 폰트가 필요하다. 다음 순서로 폰트를 찾는다:
  1) 환경변수 `REPORT_FONT_PATH` 가 가리키는 TTF
  2) 이 패키지 옆 `fonts/` 폴더의 *.ttf (예: NanumGothic.ttf)
폰트를 못 찾으면 Helvetica 로 대체하고, 한글은 ASCII 로 치환(누락)해 최소한
유효한 PDF 가 나오도록 한다(라벨은 영문 병기).

의존성: fpdf2 (requirements.txt). Lambda 배포 시 zip 에 함께 번들해야 한다.
"""

from __future__ import annotations

import os
from typing import Dict, List, Optional

from .record_adapter import normalize_inspection_record

_HERE = os.path.dirname(os.path.abspath(__file__))
_FONT_DIRS = (os.path.join(_HERE, "fonts"),)


def _find_font() -> Optional[str]:
    """사용할 한글 TTF 경로를 찾는다(없으면 None)."""
    env_path = os.getenv("REPORT_FONT_PATH")
    if env_path and os.path.exists(env_path):
        return env_path
    for d in _FONT_DIRS:
        if os.path.isdir(d):
            for name in os.listdir(d):
                if name.lower().endswith(".ttf"):
                    return os.path.join(d, name)
    return None


class _Report:
    """fpdf2 wrapper. 폰트 유무에 따라 한글/영문 폴백을 처리한다."""

    def __init__(self) -> None:
        from fpdf import FPDF  # 지연 import: PDF 생성 시점에만 의존성 필요
        from fpdf.enums import XPos, YPos

        # 매 multi_cell 마다 커서를 좌측 여백으로 되돌려 폭 계산이 깨지지 않게 한다.
        self._next = {"new_x": XPos.LMARGIN, "new_y": YPos.NEXT}
        self.pdf = FPDF(format="A4")
        self.pdf.set_margins(15, 15, 15)
        self.pdf.set_auto_page_break(auto=True, margin=15)
        self.pdf.add_page()

        font_path = _find_font()
        if font_path:
            self.pdf.add_font("Report", "", font_path)
            self.family = "Report"
            self.unicode = True
        else:
            print("[pdf_report] 한글 TTF 미발견 → Helvetica 대체(한글 누락 가능). "
                  "REPORT_FONT_PATH 로 폰트를 지정하세요.")
            self.family = "Helvetica"
            self.unicode = False

    def _t(self, text: str) -> str:
        """폰트가 한글을 지원하지 않으면 latin-1 로 안전 변환."""
        if self.unicode:
            return text
        return text.encode("latin-1", "replace").decode("latin-1")

    def title(self, text: str) -> None:
        self.pdf.set_font(self.family, size=18)
        self.pdf.multi_cell(0, 10, self._t(text), **self._next)
        self.pdf.ln(2)

    def heading(self, text: str) -> None:
        self.pdf.ln(3)
        self.pdf.set_font(self.family, size=13)
        self.pdf.multi_cell(0, 8, self._t(text), **self._next)

    def kv(self, label: str, value: str) -> None:
        self.pdf.set_font(self.family, size=11)
        self.pdf.multi_cell(0, 7, self._t(f"- {label}: {value}"), **self._next)

    def paragraph(self, text: str) -> None:
        self.pdf.set_font(self.family, size=11)
        self.pdf.multi_cell(0, 7, self._t(text or "-"), **self._next)

    def output(self) -> bytes:
        return bytes(self.pdf.output())


def _fmt_detections(detections: List[Dict]) -> List[str]:
    if not detections:
        return ["탐지된 손상 없음 (No damage detected)"]
    lines = []
    for i, d in enumerate(detections, 1):
        lines.append(
            f"{i}. class={d.get('class', '?')} / severity={d.get('severity', '?')} "
            f"/ confidence={d.get('confidence', '?')} / location={d.get('location', '-')}"
        )
    return lines


def build_report_pdf(record: Dict, report: Dict) -> bytes:
    """검수 레코드 + 보고서 섹션으로 EIR PDF 바이트를 생성한다."""
    record = normalize_inspection_record(record)
    r = _Report()

    r.title("컨테이너 검수 보고서 (Equipment Interchange Receipt)")

    r.heading("1. 기본 정보 (General)")
    r.kv("Event ID", str(record.get("event_id", "-")))
    r.kv("Container ID", str(record.get("container_id", "-")))
    r.kv("촬영 시각 (Captured At)", str(record.get("captured_at", "-")))
    r.kv("처리 시각 (Processed At)", str(record.get("processed_at", "-")))
    r.kv("검수 결과 (Result)", str(record.get("inspection_result", "-")))
    r.kv("모델 (Model)", str(record.get("model_version", "-")))

    r.heading("2. 위험도 (Risk)")
    r.kv("Risk Score", str(record.get("risk_score", "-")))
    r.kv("Risk Level", str(record.get("risk_level", "-")))
    r.kv("손상 개수 (Detections)", str(record.get("detection_count", 0)))

    r.heading("3. 손상 내역 (Damage Detections)")
    for line in _fmt_detections(record.get("detections") or []):
        r.paragraph(line)

    r.heading("4. 종합 소견 (Summary)")
    r.paragraph(report.get("summary", ""))

    r.heading("5. 손상 평가 (Assessment)")
    r.paragraph(report.get("damage_assessment", ""))

    r.heading("6. 권고 조치 (Recommended Action)")
    r.paragraph(report.get("recommended_action", ""))

    r.heading("7. 재사용 판정 (Reuse Decision)")
    r.kv("판정 (Decision)", str(report.get("reuse_decision", "-")))
    r.paragraph(report.get("reuse_reason", ""))

    return r.output()
