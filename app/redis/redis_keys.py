class RedisKeys:
    """Centralized Redis key patterns for the application"""

    @staticmethod
    def USER_RATE(phone_number: str) -> str:
        return f"rate:user:{phone_number}"

    GLOBAL_RATE = "rate:global"
