import requests
import time

# Tạo một phiên làm việc (Session) để lưu giữ Cookie tự động
def create_session():
    session = requests.Session()
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://giaothong.hochiminhcity.gov.vn/"
    }
    session.headers.update(headers)
    
    # Truy cập trang chủ 1 lần để server "đóng dấu" cookie vào session
    try:
        print("Đang khởi tạo Session...")
        session.get("https://giaothong.hochiminhcity.gov.vn/", timeout=5, verify=False)
    except Exception as e:
        print(f"Cảnh báo khởi tạo: {e}")
    
    return session

def get_image_by_id(session, camera_id):
    """
    Input: 
        - session: Đối tượng session đã khởi tạo
        - camera_id: ID của camera (string)
    Output: 
        - Dữ liệu ảnh (bytes) nếu thành công
        - None nếu thất bại
    """
    try:
        ts = int(time.time() * 1000) # Timestamp mới nhất
        url = f"https://giaothong.hochiminhcity.gov.vn:8007/Render/CameraHandler.ashx?id={camera_id}&bg=black&w=300&h=230&t={ts}"
        
        # Dùng lại session để gọi
        response = session.get(url, timeout=5, verify=False)
        
        if response.status_code == 200:
            return response.content # Trả về dữ liệu thô của ảnh
        else:
            print(f"Lỗi {camera_id}: Status {response.status_code}")
            return None
            
    except Exception as e:
        print(f"Lỗi kết nối {camera_id}: {e}")
        return None