from pydantic import BaseModel


class IndexingRepo(BaseModel):
    id: str
    name: str
    full_name: str
    html_url: str
    private: bool
    default_branch: str
    clone_url: str
    owner: str
    github_installation_id: int | None = None


class IndexingRequest(BaseModel):
    repos: list[IndexingRepo]


class IndexingAck(BaseModel):
    accepted: int
    repos: list[IndexingRepo]
    message: str
