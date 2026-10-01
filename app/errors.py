class ServiceError(Exception):
    """Ошибка, безопасное описание которой можно показать пользователю."""

    def __init__(self, code: str, message: str, status_code: int = 503):
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)
