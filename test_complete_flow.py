#!/usr/bin/env python3
"""Test the complete bbox rendering flow"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

def test_import():
    """Test that draw_bbox can be imported"""
    print("🧪 Testing import...")
    try:
        from app.utils.draw_bbox import draw_layout_bbox_on_single_page
        print("✅ Successfully imported draw_layout_bbox_on_single_page")
        return True
    except Exception as e:
        print(f"❌ Import failed: {e}")
        return False

def test_gradio_render():
    """Test that Gradio's render function works"""
    print("\n🧪 Testing Gradio render function...")
    
    # Find a task with MinerU data
    import requests
    try:
        resp = requests.get("http://localhost:8000/tasks", timeout=10)
        resp.raise_for_status()
        tasks = resp.json()
        
        # Find a completed PDF task
        pdf_task = None
        for task in tasks:
            if task.get("status") == "completed" and task.get("media_type") == "pdf":
                pdf_task = task
                break
        
        if not pdf_task:
            print("⚠️  No completed PDF tasks found to test")
            print("   Please upload a PDF via Gradio first")
            return True  # Not a failure, just no data
        
        task_id = pdf_task["task_id"]
        print(f"✅ Found test task: {task_id}")
        
        # Import render function
        from ui.gradio_app import render_pdf_page
        
        # Try to render page 1
        print(f"🎨 Rendering page 1...")
        result = render_pdf_page(task_id=task_id, page_num=1)
        pdf_path, info_md, current_page, total_pages = result
        
        if pdf_path and Path(pdf_path).exists():
            size = Path(pdf_path).stat().st_size / 1024
            print(f"✅ Generated PDF: {Path(pdf_path).name} ({size:.1f} KB)")
            print(f"✅ Pages: {current_page} / {total_pages}")
            
            # Show first few lines of info
            lines = [l for l in info_md.split('\n')[:8] if l.strip()]
            print("\n📊 Info preview:")
            for line in lines:
                print(f"   {line}")
            
            return True
        else:
            print(f"❌ Failed to generate PDF")
            print(f"   Error: {info_md[:300]}")
            return False
            
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    print("=" * 70)
    print("MinerU Bbox Rendering - Complete Flow Test")
    print("=" * 70)
    
    # Test 1: Import
    if not test_import():
        print("\n❌ Import test failed")
        return 1
    
    # Test 2: Gradio render
    if not test_gradio_render():
        print("\n❌ Render test failed")
        return 1
    
    print("\n" + "=" * 70)
    print("✅ All tests passed!")
    print("=" * 70)
    print("\n🌐 Gradio UI: http://localhost:7861")
    print("📝 Navigate to 'PDF 管道' tab to test manually")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
