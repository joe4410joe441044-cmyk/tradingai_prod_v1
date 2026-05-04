from pydantic import BaseModel

class ResetRequest(BaseModel):
    balance: float