from typing import Optional
from core.error_codes import AppErrorCode

class JARVISException(Exception):
    """Base exception for all JARVIS service-level errors."""
    def __init__(self, message: str, error_code: Optional[AppErrorCode] = None):
        super().__init__(message)
        self.message = message
        self.error_code = error_code or AppErrorCode.GENERIC_ERROR

class ResourceNotFound(JARVISException):
    """Raised when a requested resource (Session, Goal, File) is not found."""
    def __init__(self, message: str, error_code: AppErrorCode = AppErrorCode.RESOURCE_NOT_FOUND):
        super().__init__(message, error_code)

class ValidationException(JARVISException):
    """Raised when user input or business rules are violated."""
    def __init__(self, message: str, error_code: AppErrorCode = AppErrorCode.VALIDATION_ERROR):
        super().__init__(message, error_code)

class PermissionDenied(JARVISException):
    """Raised when an operation is forbidden (e.g., tool access control)."""
    def __init__(self, message: str, error_code: AppErrorCode = AppErrorCode.PERMISSION_DENIED):
        super().__init__(message, error_code)

class ProviderError(JARVISException):
    """Raised when an external provider (Gemini, ElevenLabs, etc.) fails."""
    def __init__(self, message: str, error_code: AppErrorCode = AppErrorCode.PROVIDER_ERROR):
        super().__init__(message, error_code)

class OrchestrationError(JARVISException):
    """Raised when agent routing or planning fails."""
    def __init__(self, message: str, error_code: AppErrorCode = AppErrorCode.AGENT_ROUTING_FAILED):
        super().__init__(message, error_code)
