"""Stable support codes with short, actionable user messages."""
class SalemError(RuntimeError):
    def __init__(self, code: str, message: str, details: str = "") -> None:
        super().__init__(message)
        self.code, self.details = code, details

    def __str__(self) -> str:
        return f"[{self.code}] {super().__str__()}"
