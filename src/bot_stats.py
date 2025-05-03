class BotStats:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(BotStats, cls).__new__(cls)
            cls._instance.total_messages = 0
        return cls._instance
