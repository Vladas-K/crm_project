"""Фирменный PDF тайминга: только данные, предназначенные для команды мероприятия."""

from functools import lru_cache
from io import BytesIO
from xml.sax.saxutils import escape

from django.contrib.staticfiles import finders
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import LongTable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from svglib.svglib import svg2rlg


@lru_cache(maxsize=1)
def register_document_fonts():
    """Шрифты поставляются вместе с проектом, включая кириллицу и лицензию OFL."""
    pdfmetrics.registerFont(TTFont("TimelineSans", finders.find("fonts/noto-sans/NotoSans-Regular.ttf")))
    pdfmetrics.registerFont(TTFont("TimelineSansBold", finders.find("fonts/noto-sans/NotoSans-Bold.ttf")))


def build_timeline_pdf(event, items):
    """Возвращает готовый PDF в памяти; не создаёт файлов в media или временных папках."""
    register_document_fonts()
    output = BytesIO()
    document = SimpleDocTemplate(
        output, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm,
        topMargin=16 * mm, bottomMargin=16 * mm,
        title=f"Тайминг — {event}", author="Dievent",
    )
    body = ParagraphStyle("TimelineBody", fontName="TimelineSans", fontSize=10, leading=15,
                          splitLongWords=True, textColor=colors.HexColor("#171717"))
    bold = ParagraphStyle("TimelineBold", parent=body, fontName="TimelineSansBold")
    heading = ParagraphStyle("TimelineTitle", parent=bold, fontSize=20, leading=26, keepWithNext=True)
    label = ParagraphStyle("TimelineLabel", parent=body, fontSize=9, textColor=colors.HexColor("#626262"),
                           spaceAfter=5, keepWithNext=True)
    date_style = ParagraphStyle("TimelineDate", parent=body, spaceBefore=8, spaceAfter=20)
    header_style = ParagraphStyle("TimelineHeader", parent=bold, fontSize=9, leading=13)
    brand_style = ParagraphStyle("TimelineBrand", parent=bold, fontSize=23, leading=28)

    def paragraph(value, style=body):
        # Пользовательский текст не интерпретируется как разметка ReportLab.
        text = escape(str(value)).replace("\r\n", "\n").replace("\r", "\n").replace("\n", "<br/>")
        return Paragraph(text, style)

    logo = svg2rlg(finders.find("img/dievent-logo.svg"))
    scale = 46 / logo.height
    logo.scale(scale, scale)
    logo.width *= scale
    logo.height *= scale
    logo.hAlign = "LEFT"
    brand = Table([[logo, paragraph("Dievent", brand_style)]], colWidths=[42, document.width - 42])
    brand.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    story = [brand, Spacer(1, 20), paragraph("Тайминг мероприятия", label),
             paragraph(str(event), heading), paragraph(event.date.strftime("%d.%m.%Y"), date_style)]
    rows = [[paragraph(text, header_style) for text in ("Время", "Блок программы", "Описание")]]
    for item in items:
        rows.append([paragraph(item["time"].strftime("%H:%M")), paragraph(item["block"], bold),
                     paragraph(item["description"] or "—")])
    empty = len(rows) == 1
    if empty:
        rows.append([paragraph("Блоки тайминга ещё не добавлены."), "", ""])
    table = LongTable(rows, colWidths=[document.width * .16, document.width * .31, document.width * .53],
                      repeatRows=1, splitByRow=1, splitInRow=1, hAlign="LEFT")
    commands = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 9),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
        ("LINEABOVE", (0, 0), (-1, 0), .6, colors.HexColor("#888888")),
        ("LINEBELOW", (0, 0), (-1, 0), .6, colors.HexColor("#888888")),
        ("LINEBELOW", (0, 1), (-1, -1), .4, colors.HexColor("#dedede")),
    ]
    if empty:
        commands.append(("SPAN", (0, 1), (-1, 1)))
    table.setStyle(TableStyle(commands))
    story.append(table)
    document.build(story)
    output.seek(0)
    return output
