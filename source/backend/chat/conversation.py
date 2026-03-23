import uuid
from abc import ABC, abstractmethod
from typing import Dict, Set
from datetime import datetime, timezone
from threading import RLock
from cachetools import LRUCache
from collections import defaultdict
from schemas import ChatMessageHistory


class BaseConversationStorage(ABC):
    """
    Abstract base class defining the interface for conversation storage implementations.
    Provides methods to manage user conversations and their messages.
    """

    @abstractmethod
    def list(self, user_id: str) -> list[ChatMessageHistory]:
        """
        Retrieve all conversations belonging to a specific user.

        Args:
            user_id: The ID of the user

        Returns:
            A list of ChatMessageHistory objects associated with the user
        """
        raise NotImplementedError

    @abstractmethod
    def create(
        self, user_id: str, conversation_id: str | None = None, name: str | None = None
    ) -> ChatMessageHistory:
        """
        Create a new conversation for a user.

        Args:
            user_id: The ID of the user
            conversation_id: The ID for the new conversation
            name: Optional name for the conversation

        Returns:
            The newly created ChatMessageHistory object
        """
        raise NotImplementedError

    @abstractmethod
    def get(self, conversation_id: str) -> ChatMessageHistory:
        """
        Retrieve the message history for a specific conversation.

        Args:
            conversation_id: The ID of the conversation to retrieve

        Returns:
            The ChatMessageHistory object for the requested conversation
        """
        raise NotImplementedError

    @abstractmethod
    def delete(self, conversation_id: str) -> None:
        """
        Delete a specific conversation.

        Args:
            conversation_id: The ID of the conversation to delete
        """
        raise NotImplementedError

    @abstractmethod
    def update(self, conversation_id: str, name: str) -> None:
        """
        Update metadata for a specific conversation.

        Args:
            conversation_id: The ID of the conversation to update
            name: The new name for the conversation
        """
        raise NotImplementedError

    def save(self, conversation_id: str) -> None:
        """
        Flush the conversation history from memory to the persistent storage.

        This method should be called after appending new messages to a conversation history
        object, typically before a connection closes, to ensure changes are persisted.

        Args:
            conversation_id: The ID of the conversation with updated messages to persist
        """
        pass


class InMemoryConversationStorage(BaseConversationStorage):
    """
    In-memory implementation of the BaseConversationStorage interface.
    Uses an LRU cache for efficient storage and retrieval of conversations.
    """

    def __init__(self, max_cache_size: int = 1000):
        """
        Initialize the in-memory conversation storage.

        Args:
            max_cache_size: Maximum number of conversations to store in memory
        """
        # Use LRU cache for efficient memory usage
        self._storage: LRUCache[str, ChatMessageHistory] = LRUCache(
            maxsize=max_cache_size
        )
        # Index to map users to their conversations
        self._user_conversation_index: Dict[str, Set[str]] = defaultdict(set)
        # Thread safety lock
        self._lock = RLock()

    def list(self, user_id: str) -> list[ChatMessageHistory]:
        """
        Retrieve all conversations for a user, sorted by creation date.
        Cleans up the index if conversations are no longer in cache.
        """
        conversations = []
        stale_conversation_ids = set()

        with self._lock:
            # Get the set of conversation IDs for this user
            conversation_ids = self._user_conversation_index.get(user_id, set())

            # Collect valid conversations and track stale conversation IDs
            for conversation_id in conversation_ids:
                conversation = self._storage.get(conversation_id)
                if conversation is not None:
                    conversations.append(conversation)
                else:
                    stale_conversation_ids.add(conversation_id)

            # Efficiently remove stale conversations from the index if found
            if stale_conversation_ids:
                conversation_ids.difference_update(stale_conversation_ids)

        # Return conversations sorted by creation timestamp
        return sorted(conversations, key=lambda x: x.created_at)

    def create(
        self, user_id: str, conversation_id: str | None = None, name: str | None = None
    ) -> ChatMessageHistory:
        """
        Create a new conversation and add it to the storage.

        Args:
            user_id: The ID of the user
            conversation_id: The ID for the new conversation
            name: Optional name for the conversation

        Returns:
            The newly created ChatMessageHistory object
        """
        conversation_id = conversation_id or str(uuid.uuid4())
        with self._lock:
            # Create new conversation
            conversation = ChatMessageHistory(
                id=conversation_id, name=name, user_id=user_id
            )

            # Store the conversation
            self._storage[conversation_id] = conversation
            self._user_conversation_index[user_id].add(conversation_id)

            return conversation

    def get(self, conversation_id: str) -> ChatMessageHistory:
        """
        Retrieve a specific conversation by ID.
        Raises KeyError if conversation doesn't exist.
        """
        with self._lock:
            conv = self._storage.get(conversation_id)

        if conv is None:
            raise KeyError(f"Conversation with ID {conversation_id}) not found")
        return conv

    def delete(self, conversation_id: str) -> None:
        """
        Delete a conversation from both the index and storage.
        """
        with self._lock:
            conversation = self.get(conversation_id)  # Ensure the conversation exists
            # Remove from user's conversation set
            self._user_conversation_index[conversation.user_id].discard(conversation_id)
            # Remove from storage, ignore if not found
            self._storage.pop(conversation_id, None)

    def update(self, conversation_id: str, name: str) -> None:
        """
        Update a conversation's name.
        """
        with self._lock:
            conv = self.get(conversation_id=conversation_id)
            conv.name = name
            conv.updated_at = datetime.now(tz=timezone.utc)


class ConversationManager:
    """
    A manager class that provides a simplified interface for conversation operations.

    This class acts as a facade over the storage implementation, providing
    additional convenience methods while maintaining the core functionality.
    """

    def __init__(self, storage: BaseConversationStorage | None = None):
        """
        Initialize the ConversationManager with a storage backend.

        Args:
            storage: The storage implementation to use. Defaults to InMemoryConversationStorage
                    if not provided.
        """
        self._storage = storage or InMemoryConversationStorage()

    def list(self, user_id: str) -> list[ChatMessageHistory]:
        """
        List all conversations for a user.

        Args:
            user_id: The ID of the user whose conversations to retrieve

        Returns:
            A list of ChatMessageHistory objects belonging to the user
        """
        return self._storage.list(user_id=user_id)

    def create(
        self, user_id: str, conversation_id: str | None = None, name: str | None = None
    ) -> ChatMessageHistory:
        """
        Create a new conversation for a user.

        Args:
            user_id: The ID of the user who will own the conversation
            conversation_id: The ID for the new conversation
            name: Optional name for the conversation

        Returns:
            The newly created ChatMessageHistory object
        """
        return self._storage.create(
            user_id=user_id, conversation_id=conversation_id, name=name
        )

    def get(self, conversation_id: str) -> ChatMessageHistory:
        """
        Retrieve a specific conversation.

        Args:
            conversation_id: The ID of the conversation to retrieve

        Returns:
            The requested ChatMessageHistory object

        Raises:
            KeyError: If the conversation doesn't exist in the storage
        """
        return self._storage.get(conversation_id=conversation_id)

    def get_or_create(self, conversation_id: str, user_id: str = "user"):
        if self.exists(conversation_id=conversation_id):
            return self.get(conversation_id=conversation_id)
        else:
            return self.create(user_id=user_id, conversation_id=conversation_id)

    def delete(self, conversation_id: str) -> None:
        """
        Delete a conversation.

        Args:
            user_id: The ID of the user who owns the conversation
            conversation_id: The ID of the conversation to delete
        """
        self._storage.delete(conversation_id=conversation_id)

    def update(self, conversation_id: str, name: str) -> None:
        """
        Update a conversation's metadata.

        Args:
            user_id: The ID of the user who owns the conversation
            conversation_id: The ID of the conversation to update
            name: The new name for the conversation
        """
        self._storage.update(conversation_id=conversation_id, name=name)

    def exists(self, conversation_id: str) -> bool:
        """
        Check if a conversation exists for the given user.

        This method verifies whether a conversation with the specified ID
        exists and belongs to the specified user.

        Args:
            conversation_id: The ID of the conversation to check

        Returns:
            True if the conversation exists, False otherwise
        """
        try:
            self._storage.get(conversation_id=conversation_id)
            return True
        except KeyError:
            return False

    def save(self, conversation_id: str) -> None:
        """
        Persist the current state of a conversation to the storage backend.

        This method ensures that all messages in the conversation are written
        to the persistent storage. It should be called after adding new messages
        and before ending a session to prevent data loss.

        Args:
            conversation_id: The ID of the conversation to persist

        Raises:
            KeyError: If the conversation with the given ID doesn't exist
        """
        self._storage.save(conversation_id=conversation_id)

    def set_storage(self, storage: BaseConversationStorage) -> None:
        """
        Update the storage backend used by this manager.

        This method allows changing the storage implementation at runtime,
        which can be useful for testing or migration scenarios.

        Args:
            storage: The new storage implementation to use
        """
        self._storage = storage


conversations = ConversationManager()
