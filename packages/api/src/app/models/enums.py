import enum


class PRStatus(str, enum.Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    MERGED = "MERGED"


class AnalysisStatus(str, enum.Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


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
