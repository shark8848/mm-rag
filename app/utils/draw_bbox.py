# Copyright (c) Opendatalab. All rights reserved.
# Adapted from MinerU: https://github.com/opendatalab/MinerU

import json
import logging
from io import BytesIO
from pathlib import Path

from pypdf import PdfReader, PdfWriter, PageObject
from reportlab.pdfgen import canvas

logger = logging.getLogger(__name__)


def cal_canvas_rect(page, bbox):
    """Calculate rectangle coordinates on canvas"""
    page_width, page_height = float(page.cropbox[2]), float(page.cropbox[3])
    
    actual_width = page_width
    actual_height = page_height
    
    rotation_obj = page.get("/Rotate", 0)
    try:
        rotation = int(rotation_obj) % 360
    except (ValueError, TypeError) as e:
        logger.warning(f"Invalid /Rotate value {rotation_obj!r}; defaulting to 0. Error: {e}")
        rotation = 0
    
    if rotation in [90, 270]:
        actual_width, actual_height = actual_height, actual_width
        
    x0, y0, x1, y1 = bbox
    rect_w = abs(x1 - x0)
    rect_h = abs(y1 - y0)
    
    if rotation == 270:
        rect_w, rect_h = rect_h, rect_w
        x0 = actual_height - y1
        y0 = actual_width - x1
    elif rotation == 180:
        x0 = page_width - x1
    elif rotation == 90:
        rect_w, rect_h = rect_h, rect_w
        x0, y0 = y0, x0 
    else:
        # rotation == 0
        y0 = page_height - y1
    
    rect = [x0, y0, rect_w, rect_h]
    return rect


def draw_bbox_without_number(i, bbox_list, page, c, rgb_config, fill_config):
    """Draw bounding boxes without numbers"""
    new_rgb = [float(color) / 255 for color in rgb_config]
    page_data = bbox_list[i]

    for bbox in page_data:
        rect = cal_canvas_rect(page, bbox)

        if fill_config:  # filled rectangle
            c.setFillColorRGB(new_rgb[0], new_rgb[1], new_rgb[2], 0.3)
            c.rect(rect[0], rect[1], rect[2], rect[3], stroke=0, fill=1)
        else:  # bounding box only
            c.setStrokeColorRGB(new_rgb[0], new_rgb[1], new_rgb[2])
            c.rect(rect[0], rect[1], rect[2], rect[3], stroke=1, fill=0)
    return c


def draw_bbox_with_number(i, bbox_list, page, c, rgb_config, fill_config, draw_bbox=True):
    """Draw bounding boxes with numbers"""
    new_rgb = [float(color) / 255 for color in rgb_config]
    page_data = bbox_list[i]
    
    for j, bbox in enumerate(page_data):
        rect = cal_canvas_rect(page, bbox)
        
        if draw_bbox:
            if fill_config:
                c.setFillColorRGB(*new_rgb, 0.3)
                c.rect(rect[0], rect[1], rect[2], rect[3], stroke=0, fill=1)
            else:
                c.setStrokeColorRGB(*new_rgb)
                c.rect(rect[0], rect[1], rect[2], rect[3], stroke=1, fill=0)
        
        c.setFillColorRGB(*new_rgb, 1.0)
        c.setFontSize(size=10)
        
        c.saveState()
        rotation_obj = page.get("/Rotate", 0)
        try:
            rotation = int(rotation_obj) % 360
        except (ValueError, TypeError):
            logger.warning(f"Invalid /Rotate value: {rotation_obj!r}, defaulting to 0")
            rotation = 0

        if rotation == 0:
            c.translate(rect[0] + rect[2] + 2, rect[1] + rect[3] - 10)
        elif rotation == 90:
            c.translate(rect[0] + 10, rect[1] + rect[3] + 2)
        elif rotation == 180:
            c.translate(rect[0] - 2, rect[1] + 10)
        elif rotation == 270:
            c.translate(rect[0] + rect[2] - 10, rect[1] - 2)
            
        c.rotate(rotation)
        c.drawString(0, 0, str(j + 1))
        c.restoreState()

    return c


def draw_layout_bbox_on_single_page(pdf_info_page, pdf_bytes, page_index, output_path):
    """
    Draw layout bboxes on a single PDF page
    
    Args:
        pdf_info_page: Page info from middle.json pdf_info array
        pdf_bytes: Original PDF bytes
        page_index: 0-based page index
        output_path: Output PDF file path
    
    Returns:
        Output PDF file path
    """
    # Extract bbox lists by type
    tables_body, tables_caption, tables_footnote = [], [], []
    imgs_body, imgs_caption, imgs_footnote = [], [], []
    titles, texts, interequations, lists, list_items = [], [], [], [], []
    
    for block in pdf_info_page.get("para_blocks", []):
        bbox = block.get("bbox", [])
        block_type = block.get("type", "")
        
        if block_type == "table":
            for nested_block in block.get("blocks", []):
                nested_bbox = nested_block.get("bbox", [])
                nested_type = nested_block.get("type", "")
                if nested_type == "table_body":
                    tables_body.append(nested_bbox)
                elif nested_type == "table_caption":
                    tables_caption.append(nested_bbox)
                elif nested_type == "table_footnote":
                    tables_footnote.append(nested_bbox)
        elif block_type == "image":
            for nested_block in block.get("blocks", []):
                nested_bbox = nested_block.get("bbox", [])
                nested_type = nested_block.get("type", "")
                if nested_type == "image_body":
                    imgs_body.append(nested_bbox)
                elif nested_type == "image_caption":
                    imgs_caption.append(nested_bbox)
                elif nested_type == "image_footnote":
                    imgs_footnote.append(nested_bbox)
        elif block_type == "title":
            titles.append(bbox)
        elif block_type in ["text", "reference"]:
            texts.append(bbox)
        elif block_type == "equation":
            interequations.append(bbox)
        elif block_type == "list":
            lists.append(bbox)
            for sub_block in block.get("blocks", []):
                list_items.append(sub_block.get("bbox", []))
    
    # Create single-page PDF
    pdf_bytes_io = BytesIO(pdf_bytes)
    pdf_docs = PdfReader(pdf_bytes_io)
    
    if page_index >= len(pdf_docs.pages):
        logger.error(f"Page index {page_index} out of range (total {len(pdf_docs.pages)} pages)")
        return None
    
    page = pdf_docs.pages[page_index]
    page_width, page_height = float(page.cropbox[2]), float(page.cropbox[3])
    custom_page_size = (page_width, page_height)

    packet = BytesIO()
    c = canvas.Canvas(packet, pagesize=custom_page_size)

    # Draw各类型的 bbox (使用不同颜色)
    # Tables
    draw_bbox_without_number(0, [tables_body], page, c, [204, 204, 0], True)
    draw_bbox_without_number(0, [tables_caption], page, c, [255, 255, 102], True)
    draw_bbox_without_number(0, [tables_footnote], page, c, [229, 255, 204], True)
    
    # Images
    draw_bbox_without_number(0, [imgs_body], page, c, [153, 255, 51], True)
    draw_bbox_without_number(0, [imgs_caption], page, c, [102, 178, 255], True)
    draw_bbox_without_number(0, [imgs_footnote], page, c, [255, 178, 102], True)
    
    # Text elements
    draw_bbox_without_number(0, [titles], page, c, [102, 102, 255], True)
    draw_bbox_without_number(0, [texts], page, c, [153, 0, 76], True)
    draw_bbox_without_number(0, [interequations], page, c, [0, 255, 0], True)
    draw_bbox_without_number(0, [lists], page, c, [40, 169, 92], True)
    draw_bbox_without_number(0, [list_items], page, c, [40, 169, 92], False)
    
    # Draw reading order numbers
    page_block_list = []
    for block in pdf_info_page.get("para_blocks", []):
        page_block_list.append(block.get("bbox", []))
    
    draw_bbox_with_number(0, [page_block_list], page, c, [255, 0, 0], False, draw_bbox=False)

    c.save()
    packet.seek(0)
    overlay_pdf = PdfReader(packet)

    # Merge overlay with original page
    if len(overlay_pdf.pages) > 0:
        new_page = PageObject(pdf=None)
        new_page.update(page)
        page = new_page
        page.merge_page(overlay_pdf.pages[0])
    
    # Write to output
    output_pdf = PdfWriter()
    output_pdf.add_page(page)
    
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, "wb") as f:
        output_pdf.write(f)
    
    return str(output_path)
