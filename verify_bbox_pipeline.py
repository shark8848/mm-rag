#!/usr/bin/env python3
"""Quick verification of the complete MinerU bbox rendering pipeline"""

import requests
import time
import sys

API_BASE = "http://localhost:8000"
GRADIO_BASE = "http://localhost:7861"

def check_services():
    """Check if required services are running"""
    print("🔍 Checking services...")
    
    # Check FastAPI
    try:
        resp = requests.get(f"{API_BASE}/health", timeout=5)
        if resp.status_code == 200:
            print("✅ FastAPI is running on port 8000")
        else:
            print(f"⚠️  FastAPI responded with status {resp.status_code}")
    except Exception as e:
        print(f"❌ FastAPI not accessible: {e}")
        return False
    
    # Check Gradio
    try:
        resp = requests.get(GRADIO_BASE, timeout=5)
        if resp.status_code == 200:
            print("✅ Gradio is running on port 7861")
        else:
            print(f"⚠️  Gradio responded with status {resp.status_code}")
    except Exception as e:
        print(f"❌ Gradio not accessible: {e}")
        return False
    
    return True


def find_recent_task():
    """Find a recent completed PDF task"""
    print("\n🔍 Looking for recent PDF tasks...")
    
    try:
        resp = requests.get(f"{API_BASE}/tasks", timeout=10)
        resp.raise_for_status()
        tasks = resp.json()
        
        # Find completed PDF tasks
        pdf_tasks = [
            t for t in tasks 
            if t.get("status") == "completed" 
            and t.get("media_type") == "pdf"
        ]
        
        if not pdf_tasks:
            print("❌ No completed PDF tasks found")
            return None
        
        # Get the most recent one
        latest = max(pdf_tasks, key=lambda x: x.get("created_at", ""))
        task_id = latest.get("task_id")
        
        print(f"✅ Found task: {task_id}")
        print(f"   Title: {latest.get('metadata', {}).get('title', 'N/A')}")
        print(f"   Status: {latest.get('status')}")
        
        return task_id
        
    except Exception as e:
        print(f"❌ Failed to fetch tasks: {e}")
        return None


def verify_artifacts(task_id):
    """Verify task has required artifacts"""
    print(f"\n🔍 Checking artifacts for task {task_id}...")
    
    try:
        resp = requests.get(f"{API_BASE}/tasks/{task_id}", timeout=10)
        resp.raise_for_status()
        task = resp.json()
        
        result = task.get("result", {})
        extras = result.get("extras", {})
        artifacts = extras.get("artifacts", {})
        
        # Fallback checks
        if not artifacts:
            artifacts = result.get("artifacts", {})
        if not artifacts:
            task_extras = task.get("extras", {})
            artifacts = task_extras.get("artifacts", {})
        
        bundle_path = artifacts.get("mineru_bundle_path") or artifacts.get("mineru_zip_path")
        
        if bundle_path:
            print(f"✅ Found MinerU bundle: {bundle_path}")
            return True
        else:
            print("❌ No MinerU bundle found in artifacts")
            print(f"   Available artifact keys: {list(artifacts.keys())}")
            return False
            
    except Exception as e:
        print(f"❌ Failed to fetch task details: {e}")
        return False


def test_bbox_rendering(task_id):
    """Test bbox rendering via Gradio render function"""
    print(f"\n🎨 Testing bbox rendering for task {task_id}...")
    
    # This simulates what Gradio does
    from pathlib import Path
    import sys
    sys.path.insert(0, '/home/mm-rag')
    
    try:
        # Import the render function
        from ui.gradio_app import render_pdf_page
        
        # Try to render page 1
        result = render_pdf_page(task_id=task_id, page_num=1)
        pdf_path, info_md, current_page, total_pages = result
        
        if pdf_path and Path(pdf_path).exists():
            size = Path(pdf_path).stat().st_size
            print(f"✅ Generated annotated PDF: {Path(pdf_path).name}")
            print(f"   Size: {size / 1024:.1f} KB")
            print(f"   Pages: {current_page} / {total_pages}")
            print(f"\n📊 Info:")
            for line in info_md.split('\n')[:10]:
                if line.strip():
                    print(f"   {line}")
            return True
        else:
            print(f"❌ Failed to generate PDF")
            print(f"   Info: {info_md[:500]}")
            return False
            
    except Exception as e:
        print(f"❌ Error during rendering: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    print("=" * 70)
    print("MinerU Bbox Rendering Pipeline Verification")
    print("=" * 70)
    
    # Step 1: Check services
    if not check_services():
        print("\n❌ Required services are not running")
        print("   Please start FastAPI and Gradio services")
        return 1
    
    # Step 2: Find a recent task
    task_id = find_recent_task()
    if not task_id:
        print("\n⚠️  No recent PDF tasks found")
        print("   Please upload a PDF via Gradio to test the pipeline")
        return 1
    
    # Step 3: Verify artifacts
    if not verify_artifacts(task_id):
        print("\n❌ Task doesn't have required MinerU artifacts")
        return 1
    
    # Step 4: Test bbox rendering
    if not test_bbox_rendering(task_id):
        print("\n❌ Bbox rendering failed")
        return 1
    
    print("\n" + "=" * 70)
    print("✅ All checks passed! MinerU bbox rendering is working correctly")
    print("=" * 70)
    print(f"\n🌐 Access Gradio at: {GRADIO_BASE}")
    print("   Navigate to 'PDF 管道' tab")
    print("   Upload a PDF and click '🔄 加载分页预览' to see bbox annotations")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
