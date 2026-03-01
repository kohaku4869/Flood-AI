from pydantic import BaseModel, Field


class GetCameraStatusInput(BaseModel):
    street_name: str = Field(description="Tên đường cần kiểm tra trạng thái camera")


class GetCameraFutureStatusInput(BaseModel):
    street_name: str = Field(description="Tên đường cần kiểm tra trạng thái dự báo")
    time_delta: int = Field(description="Số giờ trong tương lai (ví dụ: 1, 6, 12) mặc định là 1")


class GetCameraHistoryFrequencyInput(BaseModel):
    street_name: str = Field(description="Tên đường cần xem lịch sử tần suất ngập")


class GeocodeInput(BaseModel):
    address: str = Field(description="Tên đường hoặc địa chỉ cần chuyển thành toạ độ (ví dụ: 'Nguyễn Huệ, Quận 1')")


class GetWeatherForecastInput(BaseModel):
    hour: int = Field(description="Số giờ trong tương lai cần dự báo thời tiết (1-12)")


class SetRouteInput(BaseModel):
    start_coords: dict = Field(description="Toạ độ điểm xuất phát, dạng {lat: float, lng: float}")
    end_coords: dict = Field(description="Toạ độ điểm đến, dạng {lat: float, lng: float}")


class GetFloodRiskPredictionInput(BaseModel):
    street_name: str = Field(description="Tên đường cần xem mức độ rủi ro ngập")
    hour: int = Field(description="Số giờ trong tương lai (1-12)")


class ShowCameraImageInput(BaseModel):
    street_name: str = Field(description="Tên đường cần xem hình ảnh camera")


class GetSafeStreetsNearbyInput(BaseModel):
    address: str = Field(description="Tên đường hoặc địa chỉ trung tâm cần tìm đường an toàn xung quanh")
    radius_km: float = Field(default=2.0, description="Bán kính tìm kiếm tính bằng km (mặc định 2km)")


class GetAreaFloodReportInput(BaseModel):
    district: str = Field(description="Tên quận/khu vực cần xem báo cáo ngập (ví dụ: 'Bình Thạnh', 'Quận 7')")