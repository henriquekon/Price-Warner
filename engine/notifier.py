import os
import time

class Notifier:
    def __init__(self):
        pass

    def send(self, message: str):
        print(f"\n[ALERT] Notification sent: {message}")
        with open("notifications.log", "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} - {message}\n")