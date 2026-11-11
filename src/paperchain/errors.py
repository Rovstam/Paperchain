from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Finding:
    """One machine-readable result, used for both errors and warnings."""

    code: str
    message: str
    severity: str = "error"
    file: str | None = None
    line: int | None = None
    hint: str | None = None
    data: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
        }
        if self.file:
            out["file"] = self.file
        if self.line is not None:
            out["line"] = self.line
        if self.hint:
            out["hint"] = self.hint
        if self.data:
            out["data"] = self.data
        return out


class PaperchainError(Exception):
    """A failure that should be reported as one finding, not a traceback."""

    def __init__(self, code: str, message: str, hint: str | None = None, **data: Any):
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint
        self.data = data

    def as_finding(self) -> Finding:
        return Finding(
            code=self.code,
            message=self.message,
            hint=self.hint,
            data=self.data,
        )
