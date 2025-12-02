import csv
import os
import time
import sys
from pathlib import Path

# Add the src directory to the python path to import backend_service
# Assuming this script is run from the backend_service directory or root
# We need to find the project root relative to this file
current_file = Path(__file__).resolve()
project_root = current_file.parent.parent.parent.parent # flood-ai
backend_service_src = project_root / 'backend_service' / 'src'
sys.path.append(str(backend_service_src))

from backend_service.get_image import create_session, get_image_by_id

def test_crawl_images():
    # Configuration using relative paths
    # project_root is e:\Code\flood-ai
    dataset_path = project_root / 'dataset' / 'dataset_camera_day_du.csv'
    output_dir = project_root / 'dataset' / 'imgs'

    # Create output directory if it doesn't exist
    if not output_dir.exists():
        output_dir.mkdir(parents=True, exist_ok=True)
        print(f"Created directory: {output_dir}")

    # Read the first 5 cameras from the CSV file
    cam_ids = []
    try:
        with open(dataset_path, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            # Debug: Print field names
            print(f"CSV Field names: {reader.fieldnames}")
            
            for i, row in enumerate(reader):
                if i >= 5:
                    break
                if 'CamId' not in row:
                    print(f"Row {i} keys: {row.keys()}")
                    continue
                cam_ids.append(row['CamId'])
    except FileNotFoundError:
        print(f"Dataset file not found at: {dataset_path}")
        return

    print(f"Found {len(cam_ids)} cameras to download: {cam_ids}")

    # Initialize session
    session = create_session()

    # Download and save images
    for cam_id in cam_ids:
        print(f"Downloading image from camera {cam_id}...")
        img_data = get_image_by_id(session, cam_id)
        
        if img_data:
            file_path = output_dir / f"{cam_id}.jpg"
            with open(file_path, 'wb') as f:
                f.write(img_data)
            print(f"Saved: {file_path}")
        else:
            print(f"Failed to download image from camera {cam_id}")
            
        # Sleep briefly to avoid spamming the server
        time.sleep(0.5)

if __name__ == "__main__":
    test_crawl_images()
