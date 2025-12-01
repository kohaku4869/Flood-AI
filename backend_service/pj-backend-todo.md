Xây dựng Dịch vụ Định tuyến Trung tâm (Core Routing Service)

Mục tiêu: Nhận yêu cầu tìm đường, tích hợp API AI để chặn các đoạn đường ngập, và trả về lộ trình an toàn.

1. Thiết lập API Trung tâm

[x] 1.1. Khởi tạo Ứng dụng API Chính: Dùng Flask.

[x] 1.2. Viết Endpoint /route_request (POST):

[x] Đầu vào (JSON): Nhận điểm bắt đầu (A), điểm kết thúc (B), và tọa độ/URL camera (nếu có).

{
  "start_coords": {"lat": 21.0, "lng": 105.8},
  "end_coords": {"lat": 21.1, "lng": 105.9},
  "camera_data": [
    {"id": "cam_001", "coords": {"lat": 21.05, "lng": 105.85}}
    // ... hoặc base64 ảnh/URL ảnh chụp nhanh
  ]
}


2. Tích hợp AI và Xử lý Ảnh

[x] 2.1. Viết Hàm Kết nối AI: Tạo một hàm xử lý bất đồng bộ để gọi API /classify từ Dịch vụ AI Vision (Mục I.2).

Công cụ: Thư viện Requests hoặc httpx trong Python.

[x] 2.2. Logic Cập nhật Ngập:

[x] Duyệt qua danh sách camera_data.

[x] Gửi ảnh chụp nhanh (snapshot) của từng camera đến API AI để nhận về kết quả FLOODED hoặc SAFE.

[x] Lập danh sách các tọa độ (coords) của các điểm ngập (FLOODED).

3. Logic Bản đồ và Định tuyến Động (Dynamic Routing)

[x] 3.1. Cài đặt và Tích hợp Engine Định tuyến: Cài đặt OSRM (Open Source Routing Machine) hoặc tích hợp API của bên thứ ba (Mapbox/GraphHopper).

Công cụ: OSRM, Python (OSRM Client/binding).

[x] 3.2. Xử lý Chặn Đường (Exclusion Logic) (RẤT QUAN TRỌNG):

[x] Dựa vào danh sách các điểm ngập đã xác định ở Mục II.2.2.

[x] Áp dụng các tọa độ ngập này vào logic định tuyến để loại bỏ các đoạn đường tương ứng khỏi tính toán.

Ví dụ: Sử dụng tính năng "Exclusion Zones" của OSRM hoặc mô phỏng bằng cách gán trọng số Vô cực cho các phân đoạn đường gần điểm ngập.

[x] 3.3. Tính toán Lộ trình Mới: Chạy thuật toán tìm đường (A*/Dijkstra) trên OSRM/Engine đã tích hợp để tìm tuyến đường an toàn, tránh các khu vực bị chặn.

[x] 3.4. Đầu ra Lộ trình (JSON): Trả về chuỗi tọa độ (polyline) của lộ trình mới.

4. Bàn giao và Kiểm thử

[x] 4.1. Tài liệu Endpoint Trung tâm: Cung cấp URL API chính (/route_request) và mô tả cấu trúc JSON đầu vào/đầu ra cho đội Frontend.

Công cụ: Postman/Swagger UI (để test và tài liệu hóa).

[x] 4.2. Kiểm thử Tích hợp: Thực hiện end-to-end test (gửi ảnh -> gọi API AI -> gọi API Định tuyến -> nhận lộ trình) để đảm bảo toàn bộ luồng hoạt động chính xác.