from pydantic import BaseModel, Field
from langchain_core import StructuredTool

class GetCameraStatusByName(BaseModel):
    name: str = Field(description="Name of the camera")