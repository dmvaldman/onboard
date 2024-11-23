from typing import Protocol
from utils.classes import Message

class MessageHandler(Protocol):
    name: str
    def handle_message(self, message: Message) -> str:
        pass

class CommsBotBase:
    def __init__(self):
        self._message_handler: MessageHandler = None

    def handle_message(self, *args, **kwargs):
        """Route messages to appropriate handlers"""
        pass

    @property
    def message_handler(self) -> MessageHandler:
        if self._message_handler is None:
            raise ValueError("No message handler set")
        return self._message_handler

    @message_handler.setter
    def message_handler(self, handler: MessageHandler):
        if not hasattr(handler, 'handle_message'):
            raise ValueError("Handler must implement handle_message")
        self._message_handler = handler