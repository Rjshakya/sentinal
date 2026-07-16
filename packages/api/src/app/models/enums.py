import enum


class PRStatus(str, enum.Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    MERGED = "MERGED"


class CommentSeverity(str, enum.Enum):
    P1_CRITICAL = "P1_CRITICAL"
    P2_WARNING = "P2_WARNING"
    P3_NITPICK = "P3_NITPICK"


class CommentSide(str, enum.Enum):
    RIGHT = "RIGHT"
    LEFT = "LEFT"


class CommentState(str, enum.Enum):
    ACTIVE = "ACTIVE"
    OUTDATED = "OUTDATED"
    RESOLVED = "RESOLVED"


class ReviewVerdict(str, enum.Enum):
    APPROVE = "APPROVE"
    COMMENT = "COMMENT"
    REQUEST_CHANGES = "REQUEST_CHANGES"


class SandboxState(str, enum.Enum):
    STARTED = "STARTED"
    PAUSED = "PAUSED"
    STOPPED = "STOPPED"
    DELETED = "DELETED"
    ARCHIVED = "ARCHIVED"


class SetupRunStatus(str, enum.Enum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class SetupErrorCode(str, enum.Enum):
    INSTALLATION_NOT_FOUND = "INSTALLATION_NOT_FOUND"
    INSTALL_TOKEN_MINT_FAILED = "INSTALL_TOKEN_MINT_FAILED"
    GIT_CLONE_FAILED = "GIT_CLONE_FAILED"
    AGENT_CRASHED = "AGENT_CRASHED"
    NO_STRUCTURED_RESPONSE = "NO_STRUCTURED_RESPONSE"
