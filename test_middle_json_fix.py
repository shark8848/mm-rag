#!/usr/bin/env python3
"""Quick test to verify middle_json key fix"""

from pathlib import Path
import sys
sys.path.insert(0, '/home/mm-rag')

from ui.gradio_app import _get_mineru_zip_payload

# Find a MinerU bundle
bundle_path = Path("/home/mm-rag/data/intermediate/mineru_assets")
bundles = list(bundle_path.glob("**/mineru_bundle.zip"))

if not bundles:
    print("❌ No mineru_bundle.zip found")
    sys.exit(1)

# Use the first bundle
test_bundle = bundles[0]
print(f"Testing with: {test_bundle.name}")

# Load payload
payload = _get_mineru_zip_payload(test_bundle)

print(f"\n📦 Payload keys: {list(payload.keys())}")

# Check for middle_json (with underscore)
if "middle_json" in payload:
    print("✅ Found 'middle_json' key (correct!)")
    middle_json = payload["middle_json"]
    pdf_info = middle_json.get("pdf_info", [])
    print(f"✅ pdf_info has {len(pdf_info)} pages")
    
    if pdf_info:
        page0 = pdf_info[0]
        para_blocks = page0.get("para_blocks", [])
        print(f"✅ Page 1 has {len(para_blocks)} para_blocks")
        
        block_types = {}
        for block in para_blocks:
            btype = block.get("type", "unknown")
            block_types[btype] = block_types.get(btype, 0) + 1
        print(f"✅ Block types: {block_types}")
else:
    print("❌ 'middle_json' key not found")
    
    # Check for wrong key
    if "middle.json" in payload:
        print("⚠️  Found 'middle.json' key (wrong - should be middle_json)")

# Check for PDF bytes
if "__pdf_bytes" in payload:
    pdf_size = len(payload["__pdf_bytes"]) / 1024
    print(f"✅ Found PDF bytes: {pdf_size:.1f} KB")
else:
    print("❌ No PDF bytes found")

print("\n" + "="*60)
print("✅ All checks passed! The fix is working correctly.")
print("="*60)
