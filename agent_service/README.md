# Flood-AI Agent Service 🤖

Agent Service là một ứng dụng FastAPI cung cấp trợ lý AI đàm thoại thông minh (Conversational AI Assistant) giúp người dân TP.HCM theo dõi tình hình ngập lụt, xem dự báo thời tiết, tra cứu camera và tìm đường tránh ngập trực tiếp trên bản đồ.

Được xây dựng dựa trên kiến trúc **Agentic Tool-Calling** sử dụng **LangGraph** và **Gemini 2.0 Flash**.

## 🌟 Chức Năng Chính (Features)

- **Tự động suy luận & gọi tool**: AI có khả năng hiểu ngữ cảnh từ câu hỏi (VD: "Đường Nguyễn Trãi có ngập không?", "Tìm đường đi tránh ngập từ chợ Bến Thành tới sân bay") để gọi đúng API tương ứng.
- **Giao tiếp hai chiều với Frontend (WebSocket)**: Không chỉ chat, AI có thể **điều khiển trực tiếp** bản đồ trên frontend (VD: vẽ đường đi, hiển thị marker) thông qua WebSocket.
- **Stream Response (SSE)**: Phản hồi text từ AI được stream theo từng token để hiển thị ngay lập tức, mang lại trải nghiệm mượt mà.

## 🏗 Kiến Trúc (Architecture)

Agent được thiết kế dạng State Graph sử dụng kịch bản loop (Agent ↔ Tools):

1. **User Input** đến qua REST API `/chat/stream`.
2. **LangGraph State** lưu trữ lịch sử hội thoại.
3. **Agent Node (Gemini 2.0 Flash)** nhận context, suy luận và quyết định gọi Tool nào.
4. **Tool Node** thực thi các lệnh gọi API sang **Backend Service** (hoặc API ngoài như TomTom), thu thập json data trả về cho AI.
5. AI tổng hợp dữ liệu thành câu trả lời tự nhiên cho người dùng.
6. Nếu có tool điều khiển giao diện (như `set_route`), hệ thống sẽ broadcast lệnh qua WebSocket xuống trình duyệt.

## 🛠 Bộ Công Cụ (Available Tools)

Agent được trang bị 8 công cụ (tools) chuyên dụng phục vụ việc truy xuất dữ liệu:

| Tool                           | Chức năng (Description)                                                              |
| ------------------------------ | ------------------------------------------------------------------------------------ |
| `get_camera_status`            | Kiểm tra trạng thái ngập HIỆN TẠI của một camera trên tên đường cụ thể.              |
| `get_camera_future_status`     | Dự báo tình trạng ngập trên một con đường sau N giờ.                                 |
| `get_camera_history_frequency` | Tra cứu lịch sử tần suất ngập của một đường (thường xuyên, thỉnh thoảng, ít khi).    |
| `get_current_condition`        | Lấy dữ liệu thời tiết và mức thủy triều HIỆN TẠI.                                    |
| `get_weather_forecast`         | Dự báo dữ liệu thời tiết (lượng mưa, thủy triều) sau N giờ.                          |
| `get_all_flooded_streets`      | Trả về danh sách TOÀN BỘ các tuyến đường đang ghi nhận tình trạng ngập hiện tại.     |
| `geocode_address`              | Chuyển đổi tên địa danh / tên đường thành tọa độ GPS `[lat, lng]` (Dùng TomTom API). |
| `set_route`                    | Tìm và vẽ đường đi tránh ngập trên bản đồ. Gửi lệnh qua WebSocket tới Frontend.      |

_Lưu ý: System Prompt được lập trình nghiêm ngặt để agent **tự động** chain các tool lại với nhau (VD: Người dùng nhập tên đường → AI tự gọi `geocode` lấy lat/lng → truyền vào `set_route`)._

## 🔌 API Endpoints

### 1. HTTP REST APIs

- `GET /health` : Kiểm tra trạng thái service.
- `POST /chat/stream` : Endpoint chính nhận tin nhắn từ user. Trả về stream SSE (`text/event-stream`).
- `POST /reset` : Xóa lịch sử hội thoại hiện tại đối với session đó.

### 2. WebSocket

- `WS /ws/frontend` : Kết nối duy trì với Frontend web app. Khi Agent gọi các tool điều hướng (như `set_route`), API sẽ broadcast kết quả qua channel này để cập nhật bản đồ frontend theo thời gian thực.

## 🚀 Hướng Dẫn Cài Đặt (Setup & Run)

Dự án Agent Service sử dụng `uv` để quản lý dependencies.

### 1. Cài đặt môi trường

Đảm bảo bạn đã cài đặt Python >= 3.12 và `uv`.

```bash
cd agent_service
uv sync
```

### 2. Cấu hình biến môi trường

Mở file `.env` ở root (hoặc tạo từ `.env.example`) và đảm bảo có các keys sau:

```ini
# Chứa danh sách các API Keys (Cách nhau bằng dấu phẩy)
GEMINI_API_KEY=key_1,key_2

# TomTom dùng cho hàm Geocode lấy tọa độ
TOMTOM_API_KEY=your_tomtom_api_key

# URL để Agent giao tiếp với Backend Service
BACKEND_URL=http://localhost:5000
```

### 3. Khởi động Service

Dùng `uv` để chạy Agent Service ở port `8001`:

```bash
uv run agent-service
```

Service giờ sẽ chạy tại: `http://localhost:8001`
