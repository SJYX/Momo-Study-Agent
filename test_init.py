#!/usr/bin/env python3
"""Test script to check StudyFlowManager initialization"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

# Set environment variable to avoid interactive user selection
os.environ['MOMO_USER'] = 'Asher'

try:
    from main import StudyFlowManager
    print("✓ StudyFlowManager import successful")

    # Test initialization
    manager = StudyFlowManager(environment='production')
    print("✓ StudyFlowManager initialization successful")
    print(f"✓ Logger created: {type(manager.logger)}")
    print(f"✓ Environment: {manager.environment}")

except Exception as e:
    print(f"✗ Error: {e}")
    import traceback
    traceback.print_exc()