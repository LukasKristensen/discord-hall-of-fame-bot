import time


class ExpiringSet:
    """
    A set whose entries drop out again after a fixed number of seconds.

    Used to remember what has recently been done without asking Discord or the database about it,
    which keeps repeated work off the hot paths. The time source is injectable so that the expiry
    behaviour can be tested without sleeping.
    """

    def __init__(self, ttl_seconds: float, time_source=time.monotonic):
        self.ttl_seconds = ttl_seconds
        self.time_source = time_source
        self.expiry_times = {}

    def add_if_absent(self, value) -> bool:
        """
        Add a value to the set and report whether it was new
        :param value: The value to add
        :return: True when the value was not held, False when it is still present and not expired
        """
        now = self.time_source()
        self.discard_expired(now)
        if value in self.expiry_times:
            return False
        self.expiry_times[value] = now + self.ttl_seconds
        return True

    def discard_expired(self, now=None):
        """
        Drop every value whose lifetime has passed
        :param now: The current time, taken from the time source when not supplied
        """
        now = self.time_source() if now is None else now
        for value in [value for value, expires_at in self.expiry_times.items() if expires_at <= now]:
            del self.expiry_times[value]

    def __contains__(self, value) -> bool:
        self.discard_expired()
        return value in self.expiry_times

    def __len__(self) -> int:
        self.discard_expired()
        return len(self.expiry_times)
