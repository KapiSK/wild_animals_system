import os
import shutil
from fastapi.testclient import TestClient
from server import app, UPLOAD_DIR

client = TestClient(app)

def test_migration():
    source = "CAM_TEST1"
    dest = "CAM_TEST2"
    
    # 1. Setup test directories and files
    source_dir = os.path.join(UPLOAD_DIR, source)
    dest_dir = os.path.join(UPLOAD_DIR, dest)
    os.makedirs(source_dir, exist_ok=True)
    if os.path.exists(dest_dir):
        shutil.rmtree(dest_dir)
        
    old_file = os.path.join(source_dir, f"{source}_20260901120000_1_1.jpg")
    new_file = os.path.join(source_dir, f"{source}_20260920120000_1_2.jpg")
    
    with open(old_file, "w") as f:
        f.write("old data")
    with open(new_file, "w") as f:
        f.write("new data")
        
    # 2. Call API
    # Using a fake admin session or bypassing auth for this simple unit test may be tricky since verify_admin is a dependency.
    # We will override the dependency for testing.
    from server import verify_admin
    app.dependency_overrides[verify_admin] = lambda: {"role": "admin"}
    
    response = client.post(
        "/api/admin/migrate_camera",
        json={
            "source_camera_id": source,
            "dest_camera_id": dest,
            "start_datetime": "2026-09-17T00:00:00"
        }
    )
    
    print("API Response:", response.json())
    
    # 3. Assertions
    assert os.path.exists(old_file), "Old file should not be moved"
    assert not os.path.exists(new_file), "New file should be moved"
    
    expected_new_file = os.path.join(dest_dir, f"{dest}_20260920120000_1_2.jpg")
    assert os.path.exists(expected_new_file), "New file should be in the dest directory with new name"
    
    print("Test passed successfully!")
    
    # Cleanup
    shutil.rmtree(source_dir)
    shutil.rmtree(dest_dir)

if __name__ == "__main__":
    test_migration()
