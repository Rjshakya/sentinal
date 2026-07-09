from pydantic import BaseModel, Field


class CodeSearchRequest(BaseModel):
    repo_id: str
    repo_name: str
    query: str = Field(min_length=1)
    limit: int = Field(default=20, ge=1, le=50)
