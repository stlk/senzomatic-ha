#!/usr/bin/env python3
"""
Setup script for testing Senzomatic integration without Home Assistant.
"""
import subprocess
import sys
import os

def install_requirements():
    """Install required packages."""
    print("📦 Installing required packages...")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])
        print("✅ Requirements installed successfully!")
    except subprocess.CalledProcessError as e:
        print(f"❌ Failed to install requirements: {e}")
        return False
    return True

def check_structure():
    """Check if the integration files are in the right place."""
    print("🔍 Checking file structure...")
    
    required_files = [
        "custom_components/senzomatic/__init__.py",
        "custom_components/senzomatic/api.py", 
        "custom_components/senzomatic/const.py",
        "test_senzomatic.py"
    ]
    
    missing_files = []
    for file_path in required_files:
        if not os.path.exists(file_path):
            missing_files.append(file_path)
    
    if missing_files:
        print("❌ Missing required files:")
        for file_path in missing_files:
            print(f"   • {file_path}")
        return False
    
    print("✅ All required files found!")
    return True

def main():
    """Main setup function."""
    print("🏠 Senzomatic Integration Test Setup")
    print("=" * 40)
    print()
    
    if not check_structure():
        print("\n❌ Setup failed - missing files!")
        print("Make sure you have the integration files in the correct structure.")
        return
    
    if not install_requirements():
        print("\n❌ Setup failed - could not install requirements!")
        return
    
    print("\n🎉 Setup completed successfully!")
    print("\nYou can now run the test script:")
    print("  python test_senzomatic.py")
    print()
    print("Or if you prefer to run it directly:")
    print("  python3 test_senzomatic.py")

if __name__ == "__main__":
    main() 