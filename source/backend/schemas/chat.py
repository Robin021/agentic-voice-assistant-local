from typing import Literal
from pydantic import BaseModel, Field
from datetime import datetime, timezone
from langchain_core.chat_history import InMemoryChatMessageHistory
from langchain_core.messages import ChatMessage as _ChatMessage


class MessageEvent(BaseModel):
    """Represents a message event containing content and its completion status."""

    is_partial: bool  # Flag indicating if the message is partially complete
    content: str  # The actual text content of the message


class ChatMessage(_ChatMessage):
    """Message that can be assigned an arbitrary speaker (i.e. role)."""

    role: str
    """The speaker / role of the Message."""

    type: Literal["chat"] = "chat"
    """The type of the message (used during serialization). Defaults to "chat"."""

    timestamp: datetime = datetime.now(tz=timezone.utc)


class HumanMessage(ChatMessage):
    role: str = "user"


class AIMessage(ChatMessage):
    role: str = "assistant"


class ChatMessageHistory(InMemoryChatMessageHistory):
    """
    Represents a chat message history with metadata.
    Extends InMemoryChatMessageHistory to add identity and timestamps.
    """

    id: str
    user_id: str
    name: str | None = None
    messages: list[ChatMessage] = Field(default_factory=list)
    created_at: datetime = datetime.now(tz=timezone.utc)
    updated_at: datetime = datetime.now(tz=timezone.utc)

    def add_user_message(self, message: HumanMessage | str) -> None:
        """Convenience method for adding a human message string to the store.

        Please note that this is a convenience method. Code should favor the
        bulk add_messages interface instead to save on round-trips to the underlying
        persistence layer.

        This method may be deprecated in a future release.

        Args:
            message: The human message to add to the store.
        """
        if isinstance(message, HumanMessage):
            self.add_message(message)
        else:
            self.add_message(HumanMessage(content=message))

    def add_ai_message(self, message: AIMessage | str) -> None:
        """Convenience method for adding an AI message string to the store.

        Please note that this is a convenience method. Code should favor the bulk
        add_messages interface instead to save on round-trips to the underlying
        persistence layer.

        This method may be deprecated in a future release.

        Args:
            message: The AI message to add.
        """
        if isinstance(message, AIMessage):
            self.add_message(message)
        else:
            self.add_message(AIMessage(content=message))
