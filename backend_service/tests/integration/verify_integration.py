import asyncio
import httpx
import respx
from backend_service.ai_service import check_flood_status

# Configuration for test cases
TEST_CASES = [
    {
        "name": "Negative Test (Dry Road)",
        "image_path": "tests/assets/test.jpg",
        "expected_flood": False
    },
    {
        "name": "Positive Test (Flooded)",
        "image_path": "tests/assets/positive_test.jpg",
        "expected_flood": True
    }
]

MOCK_CAMERA_URL = "http://mock-camera/snapshot.jpg"

async def run_test_case(test_case):
    print(f"\n--- Running: {test_case['name']} ---")
    image_path = test_case['image_path']
    
    # Read the test image
    try:
        with open(image_path, "rb") as f:
            image_bytes = f.read()
        print(f"[OK] Loaded test image: {image_path} ({len(image_bytes)} bytes)")
    except FileNotFoundError:
        print(f"[FAIL] Test image not found at {image_path}")
        return

    # Mock the camera snapshot URL to return the local image
    # We use a fresh mock context for each test case to avoid side effects
    with respx.mock(assert_all_called=False) as mock:
        mock.get(MOCK_CAMERA_URL).respond(200, content=image_bytes)
        
        # Configure respx to pass through requests to localhost (where AI service is)
        mock.route(host="localhost").pass_through()
        
        camera_data = [
            {
                "id": f"cam_{test_case['name'].replace(' ', '_')}",
                "coords": {"lat": 21.0, "lng": 105.8},
                "snapshot_url": MOCK_CAMERA_URL
            }
        ]

        try:
            flooded_coords = await check_flood_status(camera_data)
            
            is_flooded = len(flooded_coords) > 0
            print(f"  Flooded coords: {flooded_coords}")
            
            if is_flooded == test_case['expected_flood']:
                print(f"  [PASS] Result matches expectation: {'FLOOD DETECTED' if is_flooded else 'NO FLOOD'}")
            else:
                print(f"  [FAIL] Result mismatch! Expected {'FLOOD' if test_case['expected_flood'] else 'NO FLOOD'}, got {'FLOOD' if is_flooded else 'NO FLOOD'}")

        except Exception as e:
            print(f"[FAIL] check_flood_status failed: {e}")
            import traceback
            traceback.print_exc()

async def main():
    print("="*60)
    print("Verifying Real Integration with AI Service (All Scenarios)")
    print("="*60)
    
    for test_case in TEST_CASES:
        await run_test_case(test_case)

if __name__ == "__main__":
    asyncio.run(main())
