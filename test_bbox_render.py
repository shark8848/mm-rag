#!/usr/bin/env python3
"""Test script to verify bbox rendering functionality"""

import json
import sys
from pathlib import Path

# Test reading middle.json from a MinerU bundle
def test_read_middle_json():
    """Test reading middle.json from artifacts"""
    # Use the known middle.json path from the editor context
    middle_json_path = Path("/home/mm-rag/data/intermediate/mineru_assets/0d94d3b5-e1f6-4c59-b871-bc6ccf0baa42/0d94d3b5-e1f6-4c59-b871-bc6ccf0baa42_KnowledgeTransformer_详细设计文档/0d94d3b5-e1f6-4c59-b871-bc6ccf0baa42_KnowledgeTransformer_详细设计文档_middle.json")
    
    if not middle_json_path.exists():
        print(f"❌ middle.json not found: {middle_json_path}")
        return None
    
    print(f"✅ Found middle.json: {middle_json_path}")
    
    try:
        with open(middle_json_path, 'r', encoding='utf-8') as f:
            middle_json = json.load(f)
        
        pdf_info = middle_json.get("pdf_info", [])
        print(f"✅ PDF has {len(pdf_info)} pages")
        
        if pdf_info:
            page0 = pdf_info[0]
            para_blocks = page0.get("para_blocks", [])
            print(f"✅ Page 1 has {len(para_blocks)} blocks")
            
            # Count block types
            block_types = {}
            for block in para_blocks:
                btype = block.get("type", "unknown")
                block_types[btype] = block_types.get(btype, 0) + 1
            
            print(f"✅ Block types: {block_types}")
            
            # Check bbox format
            if para_blocks:
                first_block = para_blocks[0]
                bbox = first_block.get("bbox")
                print(f"✅ Sample bbox: {bbox}")
        
        return middle_json, middle_json_path
        
    except Exception as e:
        print(f"❌ Error reading middle.json: {e}")
        import traceback
        traceback.print_exc()
        return None


def test_bbox_drawing():
    """Test the bbox drawing function"""
    result = test_read_middle_json()
    if not result:
        return False
    
    middle_json, middle_json_path = result
    pdf_info = middle_json.get("pdf_info", [])
    if not pdf_info:
        print("❌ No pdf_info")
        return False
    
    # Test importing the draw function
    try:
        from app.utils.draw_bbox import draw_layout_bbox_on_single_page
        print("✅ Successfully imported draw_layout_bbox_on_single_page")
    except Exception as e:
        print(f"❌ Failed to import: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    # Extract task_id from middle.json filename
    # Pattern: {task_id}_{filename}_middle.json
    filename = middle_json_path.stem  # Remove .json
    filename = filename.replace('_middle', '')  # Remove _middle suffix
    # Now we have {task_id}_{filename}
    # Task ID is UUID format: 8-4-4-4-12 characters
    import re
    uuid_pattern = r'^([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})'
    match = re.match(uuid_pattern, filename)
    
    if not match:
        print(f"❌ Could not extract task_id from filename: {filename}")
        return False
    
    task_id = match.group(1)
    print(f"✅ Extracted task_id: {task_id}")
    
    # Look for PDF in data/raw with matching task_id
    raw_dir = Path("/home/mm-rag/data/raw")
    pdf_files = list(raw_dir.glob(f"{task_id}_*.pdf"))
    
    if not pdf_files:
        print(f"❌ No PDF found for task_id {task_id} in {raw_dir}")
        return False
    
    pdf_path = pdf_files[0]
    print(f"✅ Found PDF: {pdf_path.name}")
    
    try:
        pdf_bytes = pdf_path.read_bytes()
        print(f"✅ Read PDF: size={len(pdf_bytes)} bytes")
    except Exception as e:
        print(f"❌ Failed to read PDF: {e}")
        return False
    
    # Test drawing bbox on page 0
    try:
        output_path = "/tmp/test_bbox_layout.pdf"
        result = draw_layout_bbox_on_single_page(
            pdf_info_page=pdf_info[0],
            pdf_bytes=pdf_bytes,
            page_index=0,
            output_path=output_path
        )
        
        if result and Path(result).exists():
            size = Path(result).stat().st_size
            print(f"✅ Generated annotated PDF: {result}, size={size} bytes")
            return True
        else:
            print(f"❌ Failed to generate PDF")
            return False
            
    except Exception as e:
        print(f"❌ Error drawing bbox: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    print("=" * 60)
    print("Testing MinerU bbox rendering")
    print("=" * 60)
    
    success = test_bbox_drawing()
    
    print("=" * 60)
    if success:
        print("✅ All tests passed!")
        sys.exit(0)
    else:
        print("❌ Tests failed")
        sys.exit(1)
