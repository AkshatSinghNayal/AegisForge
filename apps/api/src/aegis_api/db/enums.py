from enum import StrEnum


class Role(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    DEVELOPER = "developer"
    VIEWER = "viewer"


class ScanMode(StrEnum):
    BASELINE = "baseline"
    PASSIVE = "passive"
    ACTIVE = "active"


class ScanState(StrEnum):
    DRAFT = "draft"
    QUEUED = "queued"
    VALIDATING_TARGET = "validating_target"
    PREPARING_SCANNER = "preparing_scanner"
    SPIDERING = "spidering"
    PASSIVE_SCANNING = "passive_scanning"
    ACTIVE_SCANNING = "active_scanning"
    COLLECTING_RESULTS = "collecting_results"
    NORMALIZING = "normalizing"
    ENRICHING = "enriching"
    EVALUATING_POLICY = "evaluating_policy"
    GENERATING_REPORT = "generating_report"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


class FindingState(StrEnum):
    NEW = "new"
    RECURRING = "recurring"
    REOPENED = "reopened"
    CHANGED = "changed"
    RESOLVED = "resolved"
    ACCEPTED_RISK = "accepted_risk"
    FALSE_POSITIVE = "false_positive"


class Severity(StrEnum):
    INFORMATIONAL = "informational"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class PolicyOutcome(StrEnum):
    INCOMPLETE = "incomplete"
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"


class ReportState(StrEnum):
    PENDING = "pending"
    GENERATING = "generating"
    COMPLETE = "complete"
    FAILED = "failed"
    EXPIRED = "expired"


class NotificationState(StrEnum):
    PENDING = "pending"
    SENDING = "sending"
    SENT = "sent"
    FAILED = "failed"
    DEAD_LETTER = "dead_letter"


class RecordState(StrEnum):
    ACTIVE = "active"
    DEACTIVATED = "deactivated"


class Completeness(StrEnum):
    UNKNOWN = "unknown"
    COMPLETE = "complete"
    PARTIAL = "partial"
    NONE = "none"


class EnrichmentState(StrEnum):
    PENDING = "pending"
    COMPLETE = "complete"
    DEGRADED = "degraded"
    DISABLED = "disabled"
    MOCK = "mock"
