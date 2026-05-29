from pydantic import BaseModel


class ApiResponse(BaseModel):
    success: bool = True
    data: object | None = None
    error: str | None = None

