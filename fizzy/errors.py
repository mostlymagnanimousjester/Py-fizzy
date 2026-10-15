class FizzyError(Exception):
    def __init__(self, message: str, status: int = 400, errors: dict | None = None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.errors = errors or {"error": [message]}


def not_found(message: str = "Not found") -> FizzyError:
    return FizzyError(message, 404)


def forbidden(message: str = "You don't have permission to do that") -> FizzyError:
    return FizzyError(message, 403)


def unauthorized(message: str = "Authentication required") -> FizzyError:
    return FizzyError(message, 401)


def invalid(errors: dict, message: str = "Validation failed") -> FizzyError:
    return FizzyError(message, 422, errors)
