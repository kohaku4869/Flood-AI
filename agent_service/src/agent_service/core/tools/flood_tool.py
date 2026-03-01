import math
import pandas as pd
import httpx
import re
import unicodedata

from langchain_core.tools import StructuredTool

from agent_service.api.manager import manager
from agent_service.core.utils.config import BACKEND_URL, DATASET_PATH, TOMTOM_API_KEY
from agent_service.core.tools.tool_des import (
    GetCameraStatusInput,
    GetCameraFutureStatusInput,
    GetCameraHistoryFrequencyInput,
    GeocodeInput,
    GetWeatherForecastInput,
    SetRouteInput,
    GetFloodRiskPredictionInput,
    ShowCameraImageInput,
    GetSafeStreetsNearbyInput,
    GetAreaFloodReportInput,
)

# ── Load & chuẩn hóa dataset ────────────────────────────────────────────────

df = pd.read_csv(DATASET_PATH)


def _normalize(text: str) -> str:
    """Chuẩn hóa text: lowercase, bỏ dấu, bỏ ký tự đặc biệt."""
    text = text.lower().strip()
    # Bỏ dấu tiếng Việt
    text = unicodedata.normalize("NFD", text)
    text = re.sub(r"[\u0300-\u036f]", "", text)
    # Bỏ đ -> d
    text = text.replace("đ", "d")
    # Bỏ ký tự đặc biệt, giữ chữ + số + khoảng trắng
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


# Tạo cột normalized sẵn để search nhanh
df["street_normalized"] = df["Street_Name"].apply(_normalize)


def _search_cameras(street_name: str) -> pd.DataFrame:
    """Tìm cameras theo tên đường (fuzzy search bằng substring)."""
    query = _normalize(street_name)
    mask = df["street_normalized"].str.contains(query, na=False)
    return df[mask]


# ── Tool functions ────────────────────────────────────────────────────────────


async def get_camera_status(street_name: str) -> dict:
    """Lấy trạng thái camera hiện tại theo tên đường từ backend flood-status."""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{BACKEND_URL}/flood-status",
                timeout=10,
            )
            response.raise_for_status()
            data = response.json()
    except Exception as e:
        return {"found": False, "error": f"Không thể lấy dữ liệu flood-status: {str(e)}"}

    query = _normalize(street_name)
    all_cameras = data.get("cameras", [])

    # Lọc camera có name chứa tên đường tìm kiếm
    matched = [
        cam for cam in all_cameras
        if query in _normalize(cam.get("name", ""))
    ]

    if not matched:
        return {"found": False, "message": f"Không tìm thấy camera nào trên đường '{street_name}'."}

    cameras = []
    for cam in matched:
        cameras.append({
            "street_name": cam.get("name"),
            "is_flooded": cam.get("is_flooded"),
        })

    return {"count": len(cameras), "cameras": cameras}


async def get_camera_future_status(street_name: str, time_delta: int = 1) -> dict:
    """Lấy trạng thái dự báo camera theo tên đường và số giờ trong tương lai."""
    results = _search_cameras(street_name)

    if results.empty:
        return {"found": False, "message": f"Không tìm thấy camera nào trên đường '{street_name}'."}

    cam_ids = results["CamId"].tolist()

    # Gọi backend API để lấy dự báo
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{BACKEND_URL}/predict",
                params={"hour": time_delta},
                timeout=10,
            )
            response.raise_for_status()
            predictions = response.json()
    except Exception as e:
        return {"found": True, "error": f"Không thể lấy dữ liệu dự báo: {str(e)}"}

    # Lọc predictions cho các camera tìm được
    camera_predictions = []
    pred_data = predictions.get("predictions", predictions)
    if isinstance(pred_data, list):
        for pred in pred_data:
            if pred.get("cam_id") in cam_ids or pred.get("CamId") in cam_ids:
                camera_predictions.append(pred)

    return {
        "found": True,
        "time_delta_hours": time_delta,
        "count": len(camera_predictions),
        "predictions": camera_predictions if camera_predictions else f"Đã tìm thấy {len(cam_ids)} camera nhưng chưa có dữ liệu dự báo.",
    }


async def get_camera_history_frequency(street_name: str) -> dict:
    """Lấy lịch sử tần suất ngập của camera theo tên đường."""
    results = _search_cameras(street_name)

    if results.empty:
        return {"found": False, "message": f"Không tìm thấy camera nào trên đường '{street_name}'."}

    cameras = []
    for _, row in results.iterrows():
        coef = row["Coef"]
        # Phân loại tần suất dựa trên hệ số ngập
        if coef >= 0.6:
            frequency = "Rất thường xuyên"
        elif coef >= 0.4:
            frequency = "Thường xuyên"
        elif coef >= 0.3:
            frequency = "Trung bình"
        else:
            frequency = "Ít khi"

        cameras.append({
            "street_name": row["Street_Name"],
            "flood_frequency": frequency,
        })

    return {"count": len(cameras), "cameras": cameras}


async def get_current_condition() -> dict:
    """Lấy điều kiện thời tiết và thủy triều hiện tại."""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{BACKEND_URL}/weather/current",
                timeout=10,
            )
            response.raise_for_status()
            data = response.json()
    except Exception as e:
        return {"error": f"Không thể lấy dữ liệu thời tiết: {str(e)}"}

    weather = data.get("weather", {})
    return {
        "rain_3h": weather.get("rain_3h"),
        "rain_level": weather.get("rain_level"),
        "tide": weather.get("tide"),
        "tide_level": weather.get("tide_level"),
    }


async def get_all_flooded_streets() -> dict:
    """Lấy danh sách tất cả các đường đang bị ngập."""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{BACKEND_URL}/flood-status",
                timeout=10,
            )
            response.raise_for_status()
            data = response.json()
    except Exception as e:
        return {"error": f"Không thể lấy dữ liệu flood-status: {str(e)}"}

    all_cameras = data.get("cameras", [])
    flooded = [
        cam for cam in all_cameras
        if cam.get("is_flooded")
    ]

    flooded_streets = [cam.get("name") for cam in flooded]

    return {
        "total_cameras": len(all_cameras),
        "flooded_count": len(flooded_streets),
        "flooded_streets": flooded_streets,
    }


async def get_weather_forecast(hour: int) -> dict:
    """Lấy dự báo thời tiết (mưa, thủy triều) sau N giờ."""
    if hour < 1 or hour > 12:
        return {"error": "Số giờ phải từ 1 đến 12."}

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{BACKEND_URL}/weather/{hour}",
                timeout=10,
            )
            response.raise_for_status()
            data = response.json()
    except Exception as e:
        return {"error": f"Không thể lấy dự báo thời tiết: {str(e)}"}

    weather = data.get("weather", {})
    return {
        "hour": hour,
        "rain_3h": weather.get("rain_3h"),
        "rain_level": weather.get("rain_level"),
        "tide": weather.get("tide"),
        "tide_level": weather.get("tide_level"),
    }


async def geocode_address(address: str) -> dict:
    """Chuyển tên đường hoặc địa chỉ thành toạ độ bằng TomTom Geocoding API."""
    if not TOMTOM_API_KEY:
        return {"error": "TOMTOM_API_KEY chưa được cấu hình."}

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"https://api.tomtom.com/search/2/geocode/{address}.json",
                params={
                    "key": TOMTOM_API_KEY,
                    "countrySet": "VN",
                    "lat": 10.8231,
                    "lon": 106.6297,
                    "radius": 50000,
                    "limit": 3,
                },
                timeout=10,
            )
            response.raise_for_status()
            data = response.json()
    except Exception as e:
        return {"error": f"Không thể geocode địa chỉ: {str(e)}"}

    results = data.get("results", [])
    if not results:
        return {"found": False, "message": f"Không tìm thấy toạ độ cho '{address}'."}

    # Chỉ lấy kết quả đầu tiên (phù hợp nhất)
    best = results[0]
    pos = best.get("position", {})
    addr = best.get("address", {})
    return {
        "lat": pos.get("lat"),
        "lng": pos.get("lon"),
        "address": addr.get("freeformAddress", ""),
    }


async def set_route(start_coords: dict, end_coords: dict) -> str:
    """Đặt điểm bắt đầu và kết thúc rồi tìm đường trên bản đồ."""
    await manager.set_route_and_find(start_coords, end_coords)
    return "Đã gửi lệnh tìm đường tới bản đồ."


async def get_flood_risk_prediction(street_name: str, hour: int) -> dict:
    """Lấy mức độ rủi ro ngập chi tiết (risk score) cho đường cụ thể sau N giờ."""
    if hour < 1 or hour > 12:
        return {"error": "hour phải từ 1 đến 12."}

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{BACKEND_URL}/predictions/{hour}",
                timeout=15,
            )
            response.raise_for_status()
            data = response.json()
    except Exception as e:
        return {"error": f"Không thể lấy dữ liệu dự báo rủi ro: {str(e)}"}

    query = _normalize(street_name)
    cameras = data.get("cameras", [])
    matched = [
        cam for cam in cameras
        if query in _normalize(cam.get("name", ""))
    ]

    if not matched:
        return {"found": False, "message": f"Không tìm thấy camera nào trên đường '{street_name}'."}

    results = []
    for cam in matched:
        results.append({
            "street_name": cam.get("name"),
            "risk": round(cam.get("risk", 0), 2),
            "risk_level": cam.get("risk_level", "low"),
        })

    return {"hour": hour, "count": len(results), "cameras": results}


async def get_flood_risk_summary() -> dict:
    """Lấy tóm tắt rủi ro ngập 12 giờ tới — số đường nguy hiểm mỗi giờ."""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{BACKEND_URL}/predictions/summary",
                timeout=15,
            )
            response.raise_for_status()
            data = response.json()
    except Exception as e:
        return {"error": f"Không thể lấy tóm tắt dự báo: {str(e)}"}

    summary = data.get("summary", [])
    if not summary:
        return {"message": "Chưa có dữ liệu dự báo rủi ro. Hệ thống có thể chưa chạy job tính toán."}

    results = []
    for s in summary:
        results.append({
            "hour": s.get("hour"),
            "high_risk": s.get("high_risk", 0),
            "medium_risk": s.get("medium_risk", 0),
        })

    return {"summary": results}


async def show_camera_image(street_name: str) -> str:
    """Hiển thị hình ảnh camera giao thông của đường lên bản đồ."""
    results = _search_cameras(street_name)

    if results.empty:
        return f"Không tìm thấy camera nào trên đường '{street_name}'."

    cam_id = results.iloc[0]["CamId"]
    cam_name = results.iloc[0]["Street_Name"]
    await manager.show_camera_image(cam_id, cam_name)
    return f"Đã gửi hình ảnh camera tại {cam_name} lên bản đồ."


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Tính khoảng cách Haversine giữa 2 toạ độ (trả về km)."""
    R = 6371  # Earth radius in km
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng / 2) ** 2
    return R * 2 * math.asin(math.sqrt(a))


async def get_safe_streets_nearby(address: str, radius_km: float = 2.0) -> dict:
    """Tìm các đường an toàn (không ngập) trong bán kính quanh một địa chỉ."""
    # 1. Geocode địa chỉ
    geo = await geocode_address(address)
    if "error" in geo or geo.get("found") is False:
        return {"error": f"Không thể xác định toạ độ cho '{address}'."}

    center_lat = geo["lat"]
    center_lng = geo["lng"]

    # 2. Lấy danh sách đường ngập
    flood_data = await get_all_flooded_streets()
    flooded_set = set()
    for name in flood_data.get("flooded_streets", []):
        flooded_set.add(_normalize(name))

    # 3. Lọc cameras trong bán kính + không ngập
    safe = []
    seen_streets = set()
    for _, row in df.iterrows():
        cam_lat = row.get("Latitude", 0)
        cam_lng = row.get("Longitude", 0)
        street = row["Street_Name"]
        street_norm = _normalize(street)

        if street_norm in seen_streets:
            continue

        dist = _haversine_km(center_lat, center_lng, cam_lat, cam_lng)
        if dist <= radius_km and street_norm not in flooded_set:
            safe.append({"street_name": street, "distance_km": round(dist, 1)})
            seen_streets.add(street_norm)

    safe.sort(key=lambda x: x["distance_km"])
    return {
        "center": geo.get("address", address),
        "radius_km": radius_km,
        "safe_count": len(safe),
        "safe_streets": safe[:15],  # Giới hạn 15 đường gần nhất
    }


async def get_area_flood_report(district: str) -> dict:
    """Báo cáo tổng hợp tình hình ngập lụt theo quận/khu vực."""
    query = _normalize(district)

    # 1. Lọc cameras thuộc quận
    area_cameras = []
    for _, row in df.iterrows():
        street_norm = _normalize(row["Street_Name"])
        if query in street_norm:
            area_cameras.append(row["Street_Name"])

    if not area_cameras:
        return {"found": False, "message": f"Không tìm thấy dữ liệu camera nào tại '{district}'."}

    # 2. Lấy danh sách đường đang ngập
    flood_data = await get_all_flooded_streets()
    flooded_set = set()
    for name in flood_data.get("flooded_streets", []):
        flooded_set.add(_normalize(name))

    # 3. Đối chiếu
    flooded_in_area = [s for s in area_cameras if _normalize(s) in flooded_set]
    safe_in_area = [s for s in area_cameras if _normalize(s) not in flooded_set]

    # 4. Lấy thời tiết
    weather = await get_current_condition()

    return {
        "district": district,
        "total_streets": len(area_cameras),
        "flooded_count": len(flooded_in_area),
        "flooded_streets": flooded_in_area,
        "safe_count": len(safe_in_area),
        "weather": weather,
    }


# ── StructuredTools ──────────────────────────────────────────────────────────

get_camera_status_tool = StructuredTool.from_function(
    coroutine=get_camera_status,
    name="get_camera_status",
    description="Lấy trạng thái ngập hiện tại của camera theo tên đường.",
    args_schema=GetCameraStatusInput,
)

get_camera_future_status_tool = StructuredTool.from_function(
    coroutine=get_camera_future_status,
    name="get_camera_future_status",
    description="Dự báo trạng thái ngập của camera theo tên đường sau N giờ.",
    args_schema=GetCameraFutureStatusInput,
)

get_camera_history_frequency_tool = StructuredTool.from_function(
    coroutine=get_camera_history_frequency,
    name="get_camera_history_frequency",
    description="Xem lịch sử tần suất ngập của camera theo tên đường.",
    args_schema=GetCameraHistoryFrequencyInput,
)

get_current_condition_tool = StructuredTool.from_function(
    coroutine=get_current_condition,
    name="get_current_condition",
    description="Lấy thông tin thời tiết và thủy triều hiện tại.",
)

get_all_flooded_streets_tool = StructuredTool.from_function(
    coroutine=get_all_flooded_streets,
    name="get_all_flooded_streets",
    description="Lấy danh sách tất cả các đường đang bị ngập hiện tại. Dùng khi user hỏi 'đường nào đang ngập' hoặc cần tổng quan tình hình ngập.",
)

get_weather_forecast_tool = StructuredTool.from_function(
    coroutine=get_weather_forecast,
    name="get_weather_forecast",
    description="Dự báo thời tiết (mưa, thủy triều) sau N giờ (1-12). Dùng khi user hỏi về thời tiết trong tương lai.",
    args_schema=GetWeatherForecastInput,
)

geocode_address_tool = StructuredTool.from_function(
    coroutine=geocode_address,
    name="geocode_address",
    description="Chuyển tên đường hoặc địa chỉ thành toạ độ (lat/lng). Dùng khi cần toạ độ cho set_route.",
    args_schema=GeocodeInput,
)

set_route_tool = StructuredTool.from_function(
    coroutine=set_route,
    name="set_route",
    description="Đặt điểm xuất phát và điểm đến để tìm đường tránh lũ trên bản đồ. Cần toạ độ lat/lng, dùng geocode_address nếu chỉ có tên đường.",
    args_schema=SetRouteInput,
)

get_flood_risk_prediction_tool = StructuredTool.from_function(
    coroutine=get_flood_risk_prediction,
    name="get_flood_risk_prediction",
    description="Lấy mức độ rủi ro ngập chi tiết (risk score 0-1) cho đường cụ thể sau N giờ. Khác get_camera_future_status vì trả risk score thay vì chỉ Yes/No.",
    args_schema=GetFloodRiskPredictionInput,
)

get_flood_risk_summary_tool = StructuredTool.from_function(
    coroutine=get_flood_risk_summary,
    name="get_flood_risk_summary",
    description="Tóm tắt rủi ro ngập 12 giờ tới — số đường rủi ro cao và trung bình mỗi giờ. Dùng khi user hỏi tổng quan rủi ro ngập.",
)

show_camera_image_tool = StructuredTool.from_function(
    coroutine=show_camera_image,
    name="show_camera_image",
    description="Hiển thị hình ảnh camera giao thông lên bản đồ. Dùng khi user muốn xem camera đường nào đó.",
    args_schema=ShowCameraImageInput,
)

get_safe_streets_nearby_tool = StructuredTool.from_function(
    coroutine=get_safe_streets_nearby,
    name="get_safe_streets_nearby",
    description="Tìm các đường an toàn (không ngập) trong bán kính quanh một địa chỉ. Dùng khi user hỏi 'đường nào an toàn quanh đây'.",
    args_schema=GetSafeStreetsNearbyInput,
)

get_area_flood_report_tool = StructuredTool.from_function(
    coroutine=get_area_flood_report,
    name="get_area_flood_report",
    description="Báo cáo tổng hợp ngập lụt theo quận/khu vực: số đường ngập, danh sách, thời tiết. Dùng khi user hỏi tình hình ngập ở một quận.",
    args_schema=GetAreaFloodReportInput,
)

# ── Exports dùng cho agent_node và tool_node ─────────────────────────────────

TOOLS = [
    get_camera_status_tool,
    get_camera_future_status_tool,
    get_camera_history_frequency_tool,
    get_current_condition_tool,
    get_all_flooded_streets_tool,
    get_weather_forecast_tool,
    geocode_address_tool,
    set_route_tool,
    get_flood_risk_prediction_tool,
    get_flood_risk_summary_tool,
    show_camera_image_tool,
    get_safe_streets_nearby_tool,
    get_area_flood_report_tool,
]

TOOL_MAP = {tool.name: tool for tool in TOOLS}