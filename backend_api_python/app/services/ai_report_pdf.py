"""PDF rendering for AI Copilot research reports."""

import json
import re
from datetime import datetime, timezone
from io import BytesIO
from typing import Any

from app.utils.logger import get_logger

logger = get_logger(__name__)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _plain_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)

def _has_cjk_text(value: Any) -> bool:
    text = _plain_text(value)
    return bool(re.search(r"[\u2e80-\u9fff\uac00-\ud7af\u3040-\u30ff]", text))


def _register_report_pdf_font(language: str = "", prefer_cjk: bool = False) -> str:
    from pathlib import Path

    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    language_key = _language_key(language)
    universal_candidates = [
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/Library/Fonts/Arial Unicode.ttf",
    ]
    cjk_candidates = [
        ("C:/Windows/Fonts/msyh.ttc", True),
        ("C:/Windows/Fonts/msyh.ttf", True),
        ("C:/Windows/Fonts/simsun.ttc", True),
        ("/System/Library/Fonts/Hiragino Sans GB.ttc", True),
        ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", True),
        ("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc", True),
        ("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc", True),
    ]
    script_candidates = {
        "ar": [
            ("/usr/share/fonts/truetype/noto/NotoNaskhArabic-Regular.ttf", False),
            ("/usr/share/fonts/truetype/noto/NotoSansArabic-Regular.ttf", False),
            ("/System/Library/Fonts/GeezaPro.ttc", False),
        ],
        "th": [
            ("/usr/share/fonts/truetype/noto/NotoSansThai-Regular.ttf", False),
            ("/System/Library/Fonts/ThonburiUI.ttc", False),
            ("/System/Library/Fonts/Supplemental/Thonburi.ttc", False),
        ],
    }
    candidates = (
        [(path, language_key in {"zh-CN", "zh-TW", "ja", "ko"}) for path in universal_candidates]
        + script_candidates.get(language_key, [])
        + (cjk_candidates if prefer_cjk else [])
        + [
            ("/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf", False),
            ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", False),
            ("C:/Windows/Fonts/arial.ttf", False),
        ]
    )
    font_name = f"QuantDingerSans_{re.sub(r'[^A-Za-z0-9]', '_', language_key)}"
    for path, is_cjk in candidates:
        if prefer_cjk and not is_cjk and path not in universal_candidates:
            continue
        try:
            if Path(path).exists():
                pdfmetrics.registerFont(TTFont(font_name, path))
                return font_name
        except Exception as e:
            logger.debug(f"Failed to register PDF font {path}: {e}")
    if prefer_cjk:
        try:
            from reportlab.pdfbase.cidfonts import UnicodeCIDFont

            pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
            return "STSong-Light"
        except Exception as e:
            logger.debug(f"Failed to register built-in CJK PDF font: {e}")
    return "Helvetica"


def _language_key(language: str = "") -> str:
    lang = (language or "").replace("_", "-").lower()
    if lang.startswith("zh-tw") or lang.startswith("zh-hk") or lang.startswith("zh-hant"):
        return "zh-TW"
    if lang.startswith("zh"):
        return "zh-CN"
    for key in ("ja", "ko", "de", "fr", "ru", "ar", "th", "vi"):
        if lang.startswith(key):
            return key
    return "en"


def _outlook_labels(language: str = "") -> dict[str, str]:
    labels = {
        "en": {"BUY": "Bullish", "SELL": "Bearish", "HOLD": "Neutral"},
        "zh-CN": {"BUY": "利多", "SELL": "利空", "HOLD": "中性"},
        "zh-TW": {"BUY": "利多", "SELL": "利空", "HOLD": "中性"},
        "ja": {"BUY": "強気", "SELL": "弱気", "HOLD": "中立"},
        "ko": {"BUY": "강세", "SELL": "약세", "HOLD": "중립"},
        "de": {"BUY": "Bullisch", "SELL": "Bärisch", "HOLD": "Neutral"},
        "fr": {"BUY": "Haussier", "SELL": "Baissier", "HOLD": "Neutre"},
        "ru": {"BUY": "Бычий", "SELL": "Медвежий", "HOLD": "Нейтральный"},
        "ar": {"BUY": "إيجابي", "SELL": "سلبي", "HOLD": "محايد"},
        "th": {"BUY": "เชิงบวก", "SELL": "เชิงลบ", "HOLD": "เป็นกลาง"},
        "vi": {"BUY": "Tích cực", "SELL": "Tiêu cực", "HOLD": "Trung lập"},
    }
    return labels.get(_language_key(language), labels["en"])


def _report_pdf_labels(language: str = "") -> dict[str, str]:
    labels = {
        "title": "QuantDinger AI Research Report",
        "subtitle": "AI-assisted market analysis for research use only",
        "target": "Target",
        "generated": "Generated",
        "decision": "Outlook",
        "confidence": "Confidence",
        "summary": "Executive Summary",
        "plan": "Trading Plan",
        "scores": "Model Scores",
        "trend": "Trend Outlook",
        "crypto": "Crypto Market Structure",
        "details": "Detailed Analysis",
        "reasons": "Key Reasons",
        "risks": "Risk Notes",
        "indicators": "Technical Indicators",
        "rr_warning": "Risk/reward warning",
        "rr_warning_text": "Potential reward is lower than the planned risk. The target was not stretched to hide this warning.",
        "disclaimer": "This report is generated by AI for research only and is not investment advice.",
    }
    overrides = {
        "zh-CN": {
            "title": "QuantDinger AI 研究报告",
            "subtitle": "AI 辅助市场分析，仅供研究参考",
            "target": "分析标的",
            "generated": "生成时间",
            "decision": "观点",
            "confidence": "置信度",
            "summary": "核心摘要",
            "plan": "交易计划",
            "scores": "模型评分",
            "trend": "趋势展望",
            "crypto": "加密市场结构",
            "details": "详细分析",
            "reasons": "核心理由",
            "risks": "风险提示",
            "indicators": "技术指标",
            "rr_warning": "风险收益警告",
            "rr_warning_text": "潜在收益低于计划风险；系统不会通过拉远止盈来隐藏这一警告。",
            "disclaimer": "本报告由 AI 生成，仅供研究参考，不构成投资建议。",
        },
        "zh-TW": {
            "title": "QuantDinger AI 研究報告",
            "subtitle": "AI 輔助市場分析，僅供研究參考",
            "target": "分析標的",
            "generated": "生成時間",
            "decision": "觀點",
            "confidence": "信心度",
            "summary": "核心摘要",
            "plan": "交易計畫",
            "scores": "模型評分",
            "trend": "趨勢展望",
            "crypto": "加密市場結構",
            "details": "詳細分析",
            "reasons": "核心理由",
            "risks": "風險提示",
            "indicators": "技術指標",
            "rr_warning": "風險收益警告",
            "rr_warning_text": "潛在收益低於計畫風險；系統不會透過拉遠止盈來隱藏此警告。",
            "disclaimer": "本報告由 AI 生成，僅供研究參考，不構成投資建議。",
        },
        "ja": {
            "title": "QuantDinger AI リサーチレポート",
            "subtitle": "AI による市場分析（調査目的のみ）",
            "target": "対象",
            "generated": "作成日時",
            "decision": "見通し",
            "confidence": "信頼度",
            "summary": "要約",
            "plan": "取引計画",
            "scores": "モデル評価",
            "trend": "トレンド見通し",
            "crypto": "暗号資産の市場構造",
            "details": "詳細分析",
            "reasons": "主な根拠",
            "risks": "リスク注意事項",
            "indicators": "テクニカル指標",
            "rr_warning": "リスクリワード警告",
            "rr_warning_text": "期待利益が計画損失を下回っています。この警告を隠すために利確目標を遠ざけることはありません。",
            "disclaimer": "本レポートは AI が調査目的で作成したもので、投資助言ではありません。",
        },
        "ko": {
            "title": "QuantDinger AI 리서치 보고서",
            "subtitle": "연구 목적의 AI 기반 시장 분석",
            "target": "분석 대상",
            "generated": "생성 시각",
            "decision": "전망",
            "confidence": "신뢰도",
            "summary": "핵심 요약",
            "plan": "거래 계획",
            "scores": "모델 점수",
            "trend": "추세 전망",
            "crypto": "암호화폐 시장 구조",
            "details": "상세 분석",
            "reasons": "주요 근거",
            "risks": "위험 참고사항",
            "indicators": "기술적 지표",
            "rr_warning": "손익비 경고",
            "rr_warning_text": "예상 수익이 계획된 위험보다 낮습니다. 이 경고를 감추기 위해 목표가를 임의로 늘리지 않습니다.",
            "disclaimer": "이 보고서는 AI가 연구 목적으로 생성했으며 투자 조언이 아닙니다.",
        },
        "de": {
            "title": "QuantDinger KI-Researchbericht",
            "subtitle": "KI-gestützte Marktanalyse nur zu Forschungszwecken",
            "target": "Instrument",
            "generated": "Erstellt",
            "decision": "Ausblick",
            "confidence": "Konfidenz",
            "summary": "Zusammenfassung",
            "plan": "Handelsplan",
            "scores": "Modellbewertungen",
            "trend": "Trendausblick",
            "crypto": "Kryptomarktstruktur",
            "details": "Detailanalyse",
            "reasons": "Hauptgründe",
            "risks": "Risikohinweise",
            "indicators": "Technische Indikatoren",
            "rr_warning": "Risiko-Rendite-Warnung",
            "rr_warning_text": "Die mögliche Rendite liegt unter dem geplanten Risiko. Das Kursziel wurde nicht künstlich erweitert, um diese Warnung zu verdecken.",
            "disclaimer": "Dieser Bericht wurde von KI zu Forschungszwecken erstellt und ist keine Anlageberatung.",
        },
        "fr": {
            "title": "Rapport de recherche IA QuantDinger",
            "subtitle": "Analyse de marché assistée par IA, à des fins de recherche uniquement",
            "target": "Actif analysé",
            "generated": "Généré le",
            "decision": "Perspective",
            "confidence": "Confiance",
            "summary": "Synthèse",
            "plan": "Plan de trading",
            "scores": "Scores du modèle",
            "trend": "Perspectives de tendance",
            "crypto": "Structure du marché crypto",
            "details": "Analyse détaillée",
            "reasons": "Principaux arguments",
            "risks": "Risques",
            "indicators": "Indicateurs techniques",
            "rr_warning": "Avertissement risque/rendement",
            "rr_warning_text": "Le gain potentiel est inférieur au risque prévu. L’objectif n’a pas été artificiellement éloigné pour masquer cet avertissement.",
            "disclaimer": "Ce rapport est généré par IA à des fins de recherche et ne constitue pas un conseil en investissement.",
        },
        "ru": {
            "title": "Аналитический отчёт QuantDinger AI",
            "subtitle": "Анализ рынка с помощью ИИ только для исследовательских целей",
            "target": "Инструмент",
            "generated": "Создан",
            "decision": "Прогноз",
            "confidence": "Уверенность",
            "summary": "Краткое резюме",
            "plan": "Торговый план",
            "scores": "Оценки модели",
            "trend": "Прогноз тренда",
            "crypto": "Структура крипторынка",
            "details": "Подробный анализ",
            "reasons": "Ключевые причины",
            "risks": "Риски",
            "indicators": "Технические индикаторы",
            "rr_warning": "Предупреждение о риске/доходности",
            "rr_warning_text": "Потенциальная доходность ниже планового риска. Цель не была искусственно отдалена, чтобы скрыть это предупреждение.",
            "disclaimer": "Этот отчёт создан ИИ только для исследований и не является инвестиционной рекомендацией.",
        },
        "ar": {
            "title": "تقرير أبحاث QuantDinger بالذكاء الاصطناعي",
            "subtitle": "تحليل للسوق بمساعدة الذكاء الاصطناعي لأغراض البحث فقط",
            "target": "الأصل محل التحليل",
            "generated": "تاريخ الإنشاء",
            "decision": "التوقعات",
            "confidence": "درجة الثقة",
            "summary": "الملخص التنفيذي",
            "plan": "خطة التداول",
            "scores": "درجات النموذج",
            "trend": "توقعات الاتجاه",
            "crypto": "هيكل سوق العملات الرقمية",
            "details": "التحليل التفصيلي",
            "reasons": "الأسباب الرئيسية",
            "risks": "ملاحظات المخاطر",
            "indicators": "المؤشرات الفنية",
            "rr_warning": "تحذير نسبة المخاطرة إلى العائد",
            "rr_warning_text": "العائد المحتمل أقل من المخاطرة المخطط لها. لم يتم إبعاد هدف الربح بشكل مصطنع لإخفاء هذا التحذير.",
            "disclaimer": "أُنشئ هذا التقرير بالذكاء الاصطناعي لأغراض البحث فقط ولا يُعد نصيحة استثمارية.",
        },
        "th": {
            "title": "รายงานวิจัย QuantDinger AI",
            "subtitle": "การวิเคราะห์ตลาดด้วย AI เพื่อการวิจัยเท่านั้น",
            "target": "สินทรัพย์ที่วิเคราะห์",
            "generated": "สร้างเมื่อ",
            "decision": "มุมมอง",
            "confidence": "ความเชื่อมั่น",
            "summary": "บทสรุป",
            "plan": "แผนการเทรด",
            "scores": "คะแนนโมเดล",
            "trend": "แนวโน้มตลาด",
            "crypto": "โครงสร้างตลาดคริปโท",
            "details": "การวิเคราะห์โดยละเอียด",
            "reasons": "เหตุผลสำคัญ",
            "risks": "ข้อควรระวังด้านความเสี่ยง",
            "indicators": "ตัวชี้วัดทางเทคนิค",
            "rr_warning": "คำเตือนอัตราความเสี่ยงต่อผลตอบแทน",
            "rr_warning_text": "ผลตอบแทนที่เป็นไปได้ต่ำกว่าความเสี่ยงตามแผน ระบบไม่ได้ขยายเป้าหมายกำไรเพื่อซ่อนคำเตือนนี้",
            "disclaimer": "รายงานนี้สร้างโดย AI เพื่อการวิจัยเท่านั้น ไม่ใช่คำแนะนำการลงทุน",
        },
        "vi": {
            "title": "Báo cáo nghiên cứu QuantDinger AI",
            "subtitle": "Phân tích thị trường có hỗ trợ của AI, chỉ dành cho mục đích nghiên cứu",
            "target": "Tài sản phân tích",
            "generated": "Thời gian tạo",
            "decision": "Nhận định",
            "confidence": "Độ tin cậy",
            "summary": "Tóm tắt chính",
            "plan": "Kế hoạch giao dịch",
            "scores": "Điểm mô hình",
            "trend": "Triển vọng xu hướng",
            "crypto": "Cấu trúc thị trường tiền mã hóa",
            "details": "Phân tích chi tiết",
            "reasons": "Lý do chính",
            "risks": "Lưu ý rủi ro",
            "indicators": "Chỉ báo kỹ thuật",
            "rr_warning": "Cảnh báo tỷ lệ rủi ro/lợi nhuận",
            "rr_warning_text": "Lợi nhuận tiềm năng thấp hơn rủi ro dự kiến. Mục tiêu chốt lời không bị kéo xa một cách giả tạo để che giấu cảnh báo này.",
            "disclaimer": "Báo cáo này do AI tạo cho mục đích nghiên cứu và không phải là lời khuyên đầu tư.",
        },
    }
    labels.update(overrides.get(_language_key(language), {}))
    labels["field_trend"] = {
        "en": "Trend", "zh-CN": "趋势", "zh-TW": "趨勢", "ja": "トレンド", "ko": "추세",
        "de": "Trend", "fr": "Tendance", "ru": "Тренд", "ar": "الاتجاه", "th": "แนวโน้ม", "vi": "Xu hướng",
    }.get(_language_key(language), "Trend")
    labels["field_direction"] = {
        "en": "Direction", "zh-CN": "方向", "zh-TW": "方向", "ja": "方向", "ko": "방향",
        "de": "Richtung", "fr": "Direction", "ru": "Направление", "ar": "الاتجاه", "th": "ทิศทาง", "vi": "Hướng",
    }.get(_language_key(language), "Direction")
    labels["field_score"] = {
        "en": "Score", "zh-CN": "评分", "zh-TW": "評分", "ja": "スコア", "ko": "점수",
        "de": "Bewertung", "fr": "Score", "ru": "Оценка", "ar": "الدرجة", "th": "คะแนน", "vi": "Điểm",
    }.get(_language_key(language), "Score")
    labels["field_strength"] = {
        "en": "Strength", "zh-CN": "强度", "zh-TW": "強度", "ja": "強さ", "ko": "강도",
        "de": "Stärke", "fr": "Force", "ru": "Сила", "ar": "القوة", "th": "ความแข็งแกร่ง", "vi": "Độ mạnh",
    }.get(_language_key(language), "Strength")
    labels["field_summary"] = labels["summary"]
    labels["field_value"] = {
        "en": "Value", "zh-CN": "数值", "zh-TW": "數值", "ja": "値", "ko": "값",
        "de": "Wert", "fr": "Valeur", "ru": "Значение", "ar": "القيمة", "th": "ค่า", "vi": "Giá trị",
    }.get(_language_key(language), "Value")
    labels["field_signal"] = {
        "en": "Signal", "zh-CN": "信号", "zh-TW": "訊號", "ja": "シグナル", "ko": "신호",
        "de": "Signal", "fr": "Signal", "ru": "Сигнал", "ar": "الإشارة", "th": "สัญญาณ", "vi": "Tín hiệu",
    }.get(_language_key(language), "Signal")
    extra_labels = {
        "en": ["Current Price", "24h Change", "Entry", "Stop Loss", "Take Profit", "Risk/Reward", "Horizon", "Outlook"],
        "zh-CN": ["当前价格", "24 小时涨跌", "入场价", "止损价", "止盈价", "风险收益比", "周期", "预测"],
        "zh-TW": ["目前價格", "24 小時漲跌", "進場價", "停損價", "停利價", "風險收益比", "週期", "預測"],
        "ja": ["現在価格", "24時間変動", "エントリー", "損切り", "利確", "リスクリワード", "期間", "見通し"],
        "ko": ["현재 가격", "24시간 변동", "진입가", "손절가", "목표가", "손익비", "기간", "전망"],
        "de": ["Aktueller Kurs", "24h-Änderung", "Einstieg", "Stop-Loss", "Kursziel", "Risiko/Rendite", "Zeitraum", "Ausblick"],
        "fr": ["Cours actuel", "Variation sur 24 h", "Entrée", "Stop", "Objectif", "Risque/rendement", "Horizon", "Perspective"],
        "ru": ["Текущая цена", "Изменение за 24 ч", "Вход", "Стоп-лосс", "Цель", "Риск/доходность", "Период", "Прогноз"],
        "ar": ["السعر الحالي", "التغير خلال 24 ساعة", "الدخول", "وقف الخسارة", "جني الأرباح", "المخاطرة/العائد", "الفترة", "التوقعات"],
        "th": ["ราคาปัจจุบัน", "การเปลี่ยนแปลง 24 ชม.", "ราคาเข้า", "จุดตัดขาดทุน", "เป้าหมายกำไร", "ความเสี่ยง/ผลตอบแทน", "กรอบเวลา", "มุมมอง"],
        "vi": ["Giá hiện tại", "Thay đổi 24 giờ", "Điểm vào", "Cắt lỗ", "Chốt lời", "Rủi ro/lợi nhuận", "Khung thời gian", "Nhận định"],
    }.get(_language_key(language))
    (
        labels["current_price"],
        labels["change_24h"],
        labels["entry"],
        labels["stop_loss"],
        labels["take_profit"],
        labels["risk_reward"],
        labels["horizon"],
        labels["outlook"],
    ) = extra_labels
    return labels


def build_ai_report_pdf(report: dict, target: dict | None = None, language: str = "en-US") -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT, TA_RIGHT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        KeepTogether,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    target = target or {}
    language_key = _language_key(language)
    prefer_cjk = language_key in {"zh-CN", "zh-TW", "ja", "ko"} or _has_cjk_text(report) or _has_cjk_text(target)
    font_name = _register_report_pdf_font(language=language, prefer_cjk=prefer_cjk)
    is_rtl = language_key == "ar"
    width, height = A4
    buf = BytesIO()
    labels = _report_pdf_labels(language)

    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        rightMargin=16 * mm,
        leftMargin=16 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=labels["title"],
    )
    content_width = width - doc.leftMargin - doc.rightMargin
    styles = getSampleStyleSheet()
    base_style = ParagraphStyle(
        "ReportBase",
        parent=styles["Normal"],
        fontName=font_name,
        fontSize=9.5,
        leading=15,
        textColor=colors.HexColor("#273449"),
        spaceAfter=4,
        shaping=is_rtl,
        alignment=TA_RIGHT if is_rtl else TA_LEFT,
    )
    small_style = ParagraphStyle(
        "ReportSmall",
        parent=base_style,
        fontSize=8,
        leading=11,
        textColor=colors.HexColor("#667085"),
    )
    title_style = ParagraphStyle(
        "ReportTitle",
        parent=base_style,
        fontSize=22,
        leading=28,
        textColor=colors.white,
        spaceAfter=2,
    )
    section_style = ParagraphStyle(
        "ReportSection",
        parent=base_style,
        fontSize=13,
        leading=17,
        textColor=colors.HexColor("#0f2f55"),
        spaceBefore=10,
        spaceAfter=7,
    )
    table_head_style = ParagraphStyle(
        "ReportTableHead",
        parent=base_style,
        fontSize=8,
        leading=10,
        textColor=colors.HexColor("#667085"),
    )
    table_value_style = ParagraphStyle(
        "ReportTableValue",
        parent=base_style,
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#111827"),
    )

    def clean_text(value: Any) -> str:
        text = _plain_text(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        return text.replace("\r\n", "\n").replace("\r", "\n").strip()

    def value_text(value: Any) -> str:
        if value in (None, ""):
            return "-"
        if isinstance(value, dict):
            parts = []
            preferred = ["trend", "direction", "score", "strength", "summary", "value", "signal"]
            keys = [key for key in preferred if key in value] + [key for key in value.keys() if key not in preferred]
            for key in keys[:4]:
                item = value.get(key)
                if item not in (None, "", [], {}):
                    field_label = labels.get(f"field_{key}", str(key).replace("_", " ").title())
                    parts.append(f"{field_label}: {value_text(item)}")
            return "; ".join(parts) or "-"
        if isinstance(value, (list, tuple)):
            return "; ".join(value_text(item) for item in value[:5] if item not in (None, "", [], {})) or "-"
        return clean_text(value)

    def p(text: Any, style: ParagraphStyle = base_style) -> Paragraph:
        return Paragraph(clean_text(text).replace("\n", "<br/>"), style)

    def section(title: str) -> list[Any]:
        return [Spacer(1, 5 * mm), Paragraph(clean_text(title), section_style)]

    def pair_table(items: list[tuple[str, Any]], columns: int = 2) -> Table:
        rows = []
        row = []
        for label, value in items:
            row.append([Paragraph(clean_text(label), table_head_style), Paragraph(value_text(value), table_value_style)])
            if len(row) == columns:
                rows.append(row)
                row = []
        if row:
            while len(row) < columns:
                row.append([Paragraph("", table_head_style), Paragraph("", table_value_style)])
            rows.append(row)

        col_width = content_width / columns
        table = Table(rows, colWidths=[col_width] * columns, hAlign="LEFT")
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f7f9fc")),
            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#d8e1ee")),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e6edf5")),
            ("LEFTPADDING", (0, 0), (-1, -1), 9),
            ("RIGHTPADDING", (0, 0), (-1, -1), 9),
            ("TOPPADDING", (0, 0), (-1, -1), 7),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        return table

    def simple_table(headers: list[str], rows: list[list[Any]]) -> Table:
        data = [[Paragraph(clean_text(header), table_head_style) for header in headers]]
        data.extend([[Paragraph(value_text(value), table_value_style) for value in row] for row in rows])
        table = Table(data, colWidths=[content_width / len(headers)] * len(headers), hAlign="LEFT", repeatRows=1)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef4fb")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#42526e")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#fafcff")]),
            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#d8e1ee")),
            ("INNERGRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#e6edf5")),
            ("LEFTPADDING", (0, 0), (-1, -1), 7),
            ("RIGHTPADDING", (0, 0), (-1, -1), 7),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        return table

    def bullet_block(items: Any) -> list[Any]:
        if not isinstance(items, list):
            return []
        return [p(f"- {value_text(item)}") for item in items if value_text(item) != "-"]

    def draw_page(canvas_obj: Any, document: Any) -> None:
        canvas_obj.saveState()
        canvas_obj.setFillColor(colors.HexColor("#8a94a6"))
        canvas_obj.setFont(font_name, 7.5)
        if is_rtl:
            canvas_obj.drawRightString(
                width - doc.rightMargin,
                9 * mm,
                labels["disclaimer"],
                direction="RTL",
                shaping=True,
            )
            canvas_obj.drawString(doc.leftMargin, 9 * mm, f"QuantDinger Research · {document.page}")
        else:
            canvas_obj.drawString(doc.leftMargin, 9 * mm, labels["disclaimer"])
            canvas_obj.drawRightString(width - doc.rightMargin, 9 * mm, f"QuantDinger Research · {document.page}")
        canvas_obj.restoreState()

    symbol = report.get("symbol") or target.get("symbol") or ""
    market = report.get("market") or target.get("market") or ""
    decision = _plain_text(report.get("decision") or "HOLD").upper()
    decision_display = _outlook_labels(language).get(decision, decision)
    decision_color = colors.HexColor("#15803d" if decision == "BUY" else "#b91c1c" if decision == "SELL" else "#b7791f")
    story: list[Any] = []
    header = Table([
        [
            [Paragraph(labels["title"], title_style), Paragraph(labels["subtitle"], small_style)],
            [
                Paragraph(labels["decision"], small_style),
                Paragraph(decision_display, ParagraphStyle("Decision", parent=base_style, fontSize=20, leading=24, textColor=decision_color)),
            ],
        ]
    ], colWidths=[content_width * 0.72, content_width * 0.28])
    header.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#102033")),
        ("BOX", (0, 0), (-1, -1), 0, colors.HexColor("#102033")),
        ("LEFTPADDING", (0, 0), (-1, -1), 13),
        ("RIGHTPADDING", (0, 0), (-1, -1), 13),
        ("TOPPADDING", (0, 0), (-1, -1), 13),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 13),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(header)
    story.append(Spacer(1, 6 * mm))
    story.append(pair_table([
        (labels["target"], f"{market}:{symbol}" if market or symbol else "-"),
        (labels["generated"], _now_utc().strftime("%Y-%m-%d %H:%M UTC")),
        (labels["confidence"], report.get("confidence", "-")),
        (labels["decision"], decision_display),
    ], columns=2))

    if report.get("summary"):
        story.extend(section(labels["summary"]))
        story.append(p(report.get("summary")))

    market_data = report.get("market_data") if isinstance(report.get("market_data"), dict) else {}
    plan = report.get("trading_plan") if isinstance(report.get("trading_plan"), dict) else {}
    rr_value = plan.get("risk_reward_ratio")
    if rr_value is None:
        rr_value = plan.get("riskRewardRatio")
    plan_items = [
        (labels["current_price"], market_data.get("current_price")),
        (labels["change_24h"], market_data.get("change_24h")),
        (labels["entry"], plan.get("entry_price") or plan.get("entryPrice")),
        (labels["stop_loss"], plan.get("stop_loss") or plan.get("stopLoss")),
        (labels["take_profit"], plan.get("take_profit") or plan.get("takeProfit")),
        (labels["risk_reward"], rr_value),
    ]
    if any(v not in (None, "") for _, v in plan_items):
        story.extend(section(labels["plan"]))
        story.append(pair_table([(k, "-" if v in (None, "") else v) for k, v in plan_items]))
        if plan.get("rr_warning") or plan.get("rrWarning"):
            warning = Table(
                [[Paragraph(clean_text(labels["rr_warning"]), table_head_style),
                  Paragraph(clean_text(labels["rr_warning_text"]), table_value_style)]],
                colWidths=[content_width * 0.25, content_width * 0.75],
                hAlign="LEFT",
            )
            warning.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fff7e6")),
                ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#faad14")),
                ("LEFTPADDING", (0, 0), (-1, -1), 9),
                ("RIGHTPADDING", (0, 0), (-1, -1), 9),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]))
            story.append(Spacer(1, 2 * mm))
            story.append(warning)

    scores = report.get("scores") if isinstance(report.get("scores"), dict) else {}
    if scores:
        story.extend(section(labels["scores"]))
        story.append(pair_table([(str(k).replace("_", " ").title(), v) for k, v in scores.items()]))

    trend = report.get("trend_outlook") or report.get("trendOutlook")
    trend_summary = report.get("trend_outlook_summary") or report.get("trendOutlookSummary")
    if trend_summary or trend:
        story.extend(section(labels["trend"]))
        if trend_summary:
            story.append(p(trend_summary))
        if isinstance(trend, dict):
            story.append(simple_table(
                [labels["horizon"], labels["outlook"]],
                [[str(k), v] for k, v in trend.items()],
            ))

    crypto_summary = report.get("crypto_factor_summary")
    crypto_factors = report.get("crypto_factors") if isinstance(report.get("crypto_factors"), dict) else {}
    if crypto_summary or crypto_factors:
        story.extend(section(labels["crypto"]))
        if crypto_summary:
            story.append(p(crypto_summary))
        if crypto_factors:
            story.append(pair_table([(str(k).replace("_", " "), v) for k, v in crypto_factors.items() if k != "signals"]))

    details = report.get("detailed_analysis") if isinstance(report.get("detailed_analysis"), dict) else {}
    if details:
        story.extend(section(labels["details"]))
        for key, value in details.items():
            story.append(KeepTogether([
                Paragraph(clean_text(str(key).replace("_", " ").title()), ParagraphStyle(
                    f"Detail{key}",
                    parent=base_style,
                    fontSize=10.5,
                    leading=14,
                    textColor=colors.HexColor("#0f2f55"),
                    spaceBefore=3,
                )),
                p(value),
            ]))

    if report.get("reasons"):
        story.extend(section(labels["reasons"]))
        story.extend(bullet_block(report.get("reasons")))
    if report.get("risks"):
        story.extend(section(labels["risks"]))
        story.extend(bullet_block(report.get("risks")))

    indicators = report.get("indicators") if isinstance(report.get("indicators"), dict) else {}
    if indicators:
        story.extend(section(labels["indicators"]))
        story.append(pair_table([(str(k).replace("_", " "), v) for k, v in indicators.items()]))

    doc.build(story, onFirstPage=draw_page, onLaterPages=draw_page)
    return buf.getvalue()
