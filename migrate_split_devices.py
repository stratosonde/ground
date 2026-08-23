#!/usr/bin/env python3
"""
Migration script to split telemetry_data.json into device-specific files.
Creates telemetry_data_{dev_eui}.json for each device.
"""

import json
import os
from collections import defaultdict
from datetime import datetime

def migrate_data():
    """Split telemetry_data.json by device EUI"""
    
    # Check if old file exists
    old_file = "telemetry_data.json"
    if not os.path.exists(old_file):
        print(f"❌ File {old_file} not found. Nothing to migrate.")
        return
    
    # Load existing data
    print(f"📂 Loading {old_file}...")
    with open(old_file, 'r') as f:
        all_data = json.load(f)
    
    print(f"✓ Loaded {len(all_data)} total packets")
    
    # Group by dev_eui
    by_device = defaultdict(list)
    for packet in all_data:
        dev_eui = packet.get('dev_eui', 'unknown')
        device_name = packet.get('device_name', 'unknown')
        by_device[dev_eui].append(packet)
    
    print(f"\n📊 Found {len(by_device)} devices:")
    for dev_eui, packets in by_device.items():
        device_name = packets[0].get('device_name', 'unknown')
        print(f"  - {device_name} ({dev_eui}): {len(packets)} packets")
    
    # Create backup
    backup_file = f"{old_file}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    print(f"\n💾 Creating backup: {backup_file}")
    os.rename(old_file, backup_file)
    
    # Write device-specific files
    print(f"\n✍️  Writing device-specific files:")
    for dev_eui, packets in by_device.items():
        device_name = packets[0].get('device_name', 'unknown')
        new_file = f"telemetry_data_{dev_eui}.json"
        
        with open(new_file, 'w') as f:
            json.dump(packets, f, indent=2)
        
        print(f"  ✓ {new_file} ({len(packets)} packets) - {device_name}")
    
    print(f"\n✅ Migration complete!")
    print(f"   Original file backed up to: {backup_file}")
    print(f"   Created {len(by_device)} device-specific files")

if __name__ == "__main__":
    migrate_data()
