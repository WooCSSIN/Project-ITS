import io
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

try:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
    REPORTLAB_AVAILABLE = True
except ImportError:
    REPORTLAB_AVAILABLE = False
    logger.warning("reportlab chưa được cài đặt. Chức năng xuất PDF sẽ không hoạt động. pip install reportlab")


def generate_fine_pdf(violation: dict) -> Optional[bytes]:
    """
    Tạo biên bản xử phạt vi phạm giao thông dưới dạng PDF.
    
    Args:
        violation: dict chứa thông tin vi phạm từ DB.
    
    Returns:
        bytes của file PDF, hoặc None nếu lỗi.
    """
    if not REPORTLAB_AVAILABLE:
        logger.error("reportlab chưa được cài đặt.")
        return None

    try:
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            rightMargin=2*cm, leftMargin=2*cm,
            topMargin=2*cm, bottomMargin=2*cm
        )

        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            'title', parent=styles['Heading1'],
            fontSize=14, spaceAfter=6, alignment=TA_CENTER,
            textColor=colors.HexColor('#1a1a2e'),
        )
        subtitle_style = ParagraphStyle(
            'subtitle', parent=styles['Normal'],
            fontSize=10, spaceAfter=4, alignment=TA_CENTER,
            textColor=colors.HexColor('#555555'),
        )
        label_style = ParagraphStyle(
            'label', parent=styles['Normal'],
            fontSize=10, textColor=colors.HexColor('#333333'),
        )
        value_style = ParagraphStyle(
            'value', parent=styles['Normal'],
            fontSize=11, fontName='Helvetica-Bold',
            textColor=colors.HexColor('#000000'),
        )
        section_style = ParagraphStyle(
            'section', parent=styles['Heading2'],
            fontSize=11, spaceBefore=12, spaceAfter=6,
            textColor=colors.HexColor('#c0392b'),
        )

        # Map tên lỗi vi phạm
        violation_type_map = {
            'red_light': 'Vượt đèn đỏ',
            'wrong_lane': 'Đi sai làn đường',
            'no_parking': 'Dừng đỗ sai quy định',
        }
        v_type = violation_type_map.get(violation.get('violation_type', ''), violation.get('violation_type', 'N/A'))
        fine_number = violation.get('fine_number') or f"BB-{violation.get('id', '000'):04d}"
        timestamp = violation.get('timestamp')
        if isinstance(timestamp, datetime):
            ts_str = timestamp.strftime("%H:%M - %d/%m/%Y")
        else:
            ts_str = str(timestamp or 'N/A')

        confirmed_at = violation.get('confirmed_at')
        confirmed_str = confirmed_at.strftime("%d/%m/%Y") if isinstance(confirmed_at, datetime) else str(confirmed_at or datetime.now().strftime("%d/%m/%Y"))

        story = []

        # Header
        story.append(Paragraph("CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM", subtitle_style))
        story.append(Paragraph("Độc lập - Tự do - Hạnh phúc", subtitle_style))
        story.append(Spacer(1, 0.3*cm))
        story.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor('#c0392b')))
        story.append(Spacer(1, 0.3*cm))
        story.append(Paragraph("BIÊN BẢN VI PHẠM HÀNH CHÍNH", title_style))
        story.append(Paragraph("(Lĩnh vực: Trật tự an toàn giao thông đường bộ)", subtitle_style))
        story.append(Spacer(1, 0.5*cm))

        # Số biên bản và ngày
        info_data = [
            [Paragraph("Số biên bản:", label_style), Paragraph(fine_number, value_style),
             Paragraph("Ngày lập:", label_style), Paragraph(confirmed_str, value_style)],
        ]
        info_table = Table(info_data, colWidths=[3*cm, 5*cm, 3*cm, 5*cm])
        info_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ]))
        story.append(info_table)
        story.append(Spacer(1, 0.3*cm))
        story.append(HRFlowable(width="100%", thickness=0.5, color=colors.grey))
        story.append(Spacer(1, 0.3*cm))

        # Thông tin vi phạm
        story.append(Paragraph("I. THÔNG TIN VI PHẠM", section_style))
        vio_data = [
            ["Loại vi phạm:", v_type],
            ["Thời điểm vi phạm:", ts_str],
            ["Camera phát hiện:", f"Camera ID #{violation.get('camera_id', 'N/A')}"],
            ["Độ tin cậy:", f"{(violation.get('confidence', 0) or 0) * 100:.0f}%"],
        ]
        vio_table = Table(vio_data, colWidths=[5*cm, 11*cm])
        vio_table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('ROWBACKGROUNDS', (0, 0), (-1, -1), [colors.HexColor('#f9f9f9'), colors.white]),
            ('BOX', (0, 0), (-1, -1), 0.5, colors.lightgrey),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.lightgrey),
        ]))
        story.append(vio_table)
        story.append(Spacer(1, 0.3*cm))

        # Thông tin phương tiện
        story.append(Paragraph("II. THÔNG TIN PHƯƠNG TIỆN", section_style))
        plate = violation.get('license_plate') or 'Chưa xác định'
        track_id = violation.get('vehicle_track_id') or 'N/A'
        vehicle_data = [
            ["Biển kiểm soát:", plate],
            ["Track ID (hệ thống):", str(track_id)],
        ]
        vehicle_table = Table(vehicle_data, colWidths=[5*cm, 11*cm])
        vehicle_table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 11),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('ROWBACKGROUNDS', (0, 0), (-1, -1), [colors.HexColor('#fff3cd'), colors.white]),
            ('BOX', (0, 0), (-1, -1), 0.5, colors.lightgrey),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.lightgrey),
        ]))
        story.append(vehicle_table)
        story.append(Spacer(1, 0.5*cm))

        # Chân trang ký tên
        story.append(HRFlowable(width="100%", thickness=0.5, color=colors.grey))
        story.append(Spacer(1, 0.3*cm))
        sign_data = [
            [
                Paragraph("Người vi phạm\n(ký, ghi rõ họ tên)", ParagraphStyle('sign', parent=styles['Normal'], fontSize=10, alignment=TA_CENTER)),
                Paragraph("Cán bộ lập biên bản\n(ký, ghi rõ họ tên)", ParagraphStyle('sign', parent=styles['Normal'], fontSize=10, alignment=TA_CENTER)),
            ],
            [Paragraph("\n\n\n\n_____________________", ParagraphStyle('sign', parent=styles['Normal'], fontSize=10, alignment=TA_CENTER)),
             Paragraph("\n\n\n\n_____________________", ParagraphStyle('sign', parent=styles['Normal'], fontSize=10, alignment=TA_CENTER))],
        ]
        sign_table = Table(sign_data, colWidths=[8*cm, 8*cm])
        story.append(sign_table)

        doc.build(story)
        buffer.seek(0)
        return buffer.read()

    except Exception as e:
        logger.error(f"Lỗi khi tạo PDF biên bản: {e}", exc_info=True)
        return None
