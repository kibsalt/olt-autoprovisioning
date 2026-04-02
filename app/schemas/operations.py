from pydantic import BaseModel


class OperationResponse(BaseModel):
    success: bool
    message: str
    onu_id: int
    previous_state: str | None = None
    new_state: str | None = None
