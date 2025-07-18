#!/usr/bin/env python3
"""
Standalone test script for Senzomatic API integration.
This allows testing the API functionality without installing into Home Assistant.
"""
import asyncio
import json
import logging
import os
import sys
from getpass import getpass

import aiohttp

# Import our API module
from custom_components.senzomatic.api import SenzomaticAPI

# Set up logging to see what's happening
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

async def test_senzomatic_api():
    """Test the Senzomatic API functionality."""
    print("🔧 Senzomatic API Test Script")
    print("=" * 50)
    
    # Get credentials from user
    print("\n📝 Enter your Senzomatic credentials:")
    username = os.getenv("USERNAME") 
    password = os.getenv("PASSWORD")
    oauth_client_id = os.getenv("OAUTH_CLIENT_ID")
    if not username:
        username = input("Email: ").strip()
    else:
        print(f"Email: {username} (from environment)")
        
    if not password:
        password = getpass("Password: ").strip()
    else:
        print("Password: *** (from environment)")
    
    if not username or not password:
        print("❌ Username and password are required!")
        return
    
    print(f"\n🔐 Testing authentication for: {username}")
    
    # Create aiohttp session
    async with aiohttp.ClientSession() as session:
        # Initialize API client
        api = SenzomaticAPI(session, username, password, oauth_client_id)
        
        # Test 1: Authentication
        print("\n1️⃣ Testing authentication...")
        auth_success = await api.async_authenticate()
        
        if not auth_success:
            print("❌ Authentication failed!")
            print("   • Check your credentials")
            print("   • Verify you can log in at https://erp.mgrd.cz")
            return
        
        print("✅ Authentication successful!")
        print(f"   • Installation ID: {api.installation_id}")
        
        # Test 2: Device Discovery
        print("\n2️⃣ Discovering devices...")
        devices = await api.async_get_device_list()
        
        if not devices:
            print("❌ No devices found!")
            print("   • Check that your account has access to sensors")
            print("   • Verify devices are online")
            return
        
        print(f"✅ Found {len(devices)} devices:")
        for device in devices:
            print(f"   • {device['name']} ({device['model']})")
            if 'uuid' in device:
                print(f"     UUID: {device['uuid']}")
            else:
                print("     ⚠️  No UUID found for this device")
        
        # Test 3: Sensor Data Retrieval
        print("\n3️⃣ Testing sensor data retrieval...")
        
        # Test with first device that has UUID
        test_device = None
        for device in devices:
            if 'uuid' in device:
                test_device = device
                break
        
        if not test_device:
            print("❌ No devices with UUID found for testing!")
            return
        
        print(f"📊 Testing with device: {test_device['name']}")
        
        # Test different sensor types
        sensor_types = [
            ("temperature_ambient_celsius", "Temperature"),
            ("rel_humidity_ambient_pct", "Relative Humidity"), 
            ("abs_humidity_ambient_gm3", "Absolute Humidity"),
            ("moisture", "Wood Moisture")
        ]
        
        sensor_results = {}
        for sensor_type, sensor_name in sensor_types:
            print(f"   • Testing {sensor_name}...")
            try:
                data = await api.async_get_sensor_data(test_device['uuid'], sensor_type)
                
                if data and data.get("data", {}).get("result"):
                    result_data = data["data"]["result"]
                    if result_data and len(result_data) > 0:
                        values = result_data[0].get("values", [])
                        if values:
                            latest_value = values[-1][1] if len(values) > 0 else None
                            if latest_value is not None:
                                sensor_results[sensor_name] = float(latest_value)
                                print(f"     ✅ {sensor_name}: {latest_value}")
                            else:
                                print(f"     ⚠️  {sensor_name}: No recent data")
                        else:
                            print(f"     ⚠️  {sensor_name}: No values in response")
                    else:
                        print(f"     ⚠️  {sensor_name}: Empty result")
                else:
                    print(f"     ⚠️  {sensor_name}: No data available")
                    
            except Exception as e:
                print(f"     ❌ {sensor_name}: Error - {e}")
        
        # Test 4: Full Data Retrieval
        print("\n4️⃣ Testing full data retrieval (like Home Assistant would use)...")
        try:
            full_data = await api.async_get_data()
            
            if full_data and "devices" in full_data and "sensors" in full_data:
                print("✅ Full data retrieval successful!")
                
                print(f"\n📋 Summary:")
                print(f"   • Total devices: {len(full_data['devices'])}")
                print(f"   • Devices with sensor data: {len(full_data['sensors'])}")
                
                print(f"\n📊 Sensor data by device:")
                for device_id, sensors in full_data["sensors"].items():
                    device_name = next(
                        (d["name"] for d in full_data["devices"] if d["id"] == device_id),
                        f"Device {device_id}"
                    )
                    print(f"   • {device_name}:")
                    for sensor_type, value in sensors.items():
                        print(f"     - {sensor_type}: {value}")
                
                # Save test results to file
                with open("senzomatic_test_results.json", "w") as f:
                    json.dump(full_data, f, indent=2)
                print(f"\n💾 Full results saved to: senzomatic_test_results.json")
                
            else:
                print("❌ Full data retrieval failed!")
                
        except Exception as e:
            print(f"❌ Full data retrieval error: {e}")
    
    print("\n🎉 Test completed!")
    print("\nIf all tests passed, the integration should work in Home Assistant.")
    print("If there were errors, check the logs above for troubleshooting.")

async def test_specific_device():
    """Test a specific device by UUID."""
    print("\n🎯 Test Specific Device")
    print("=" * 30)
    
    username = input("Email: ").strip()
    password = getpass("Password: ").strip()
    device_uuid = input("Device UUID: ").strip()
    
    if not all([username, password, device_uuid]):
        print("❌ All fields are required!")
        return
    
    async with aiohttp.ClientSession() as session:
        api = SenzomaticAPI(session, username, password)
        
        if not await api.async_authenticate():
            print("❌ Authentication failed!")
            return
        
        print("✅ Authentication successful!")
        
        # Test all sensor types for this device
        sensor_types = [
            "temperature_ambient_celsius",
            "rel_humidity_ambient_pct", 
            "abs_humidity_ambient_gm3",
            "moisture"
        ]
        
        for sensor_type in sensor_types:
            print(f"\n📊 Testing {sensor_type}:")
            try:
                data = await api.async_get_sensor_data(device_uuid, sensor_type)
                print(f"Raw response: {json.dumps(data, indent=2)}")
            except Exception as e:
                print(f"Error: {e}")

def main():
    """Main function with menu."""
    print("🏠 Senzomatic Home Assistant Integration Tester")
    print("=" * 55)
    print()
    print("Choose an option:")
    print("1. Full API test (recommended)")
    print("2. Test specific device by UUID")
    print("3. Exit")
    
    choice = "1" #input("\nEnter choice (1-3): ").strip()
    
    if choice == "1":
        asyncio.run(test_senzomatic_api())
    elif choice == "2":
        asyncio.run(test_specific_device())
    elif choice == "3":
        print("👋 Goodbye!")
        sys.exit(0)
    else:
        print("❌ Invalid choice!")
        main()

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n👋 Test interrupted by user. Goodbye!")
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        logging.exception("Unexpected error during testing") 