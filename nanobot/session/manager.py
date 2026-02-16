"""Session management for conversation history."""

import json
from pathlib import Path
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from collections import OrderedDict

from loguru import logger

from nanobot.utils.helpers import ensure_dir, safe_filename


@dataclass
class Session:
    """
    A conversation session.

    Stores messages in JSONL format for easy reading and persistence.

    Important: Messages are append-only for LLM cache efficiency.
    The consolidation process writes summaries to MEMORY.md/HISTORY.md
    but does NOT modify the messages list or get_history() output.
    """

    key: str  # channel:chat_id
    messages: list[dict[str, Any]] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    metadata: dict[str, Any] = field(default_factory=dict)
    last_consolidated: int = 0  # Number of messages already consolidated to files
    
    def add_message(self, role: str, content: str, **kwargs: Any) -> None:
        """Add a message to the session."""
        msg = {
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat(),
            **kwargs
        }
        self.messages.append(msg)
        self.updated_at = datetime.now()
    
    def get_history(self, max_messages: int = 500) -> list[dict[str, Any]]:
        """Get recent messages in LLM format (role + content only)."""
        return [{"role": m["role"], "content": m["content"]} for m in self.messages[-max_messages:]]
    
    def clear(self) -> None:
        """Clear all messages and reset session to initial state."""
        self.messages = []
        self.last_consolidated = 0
        self.updated_at = datetime.now()


class SessionManager:
    """
    Manages conversation sessions.

    Sessions are stored as JSONL files in the sessions directory.
    Uses LRU cache to prevent memory leaks.
    """

    def __init__(self, workspace: Path, max_cache_size: int = 100):
        self.workspace = workspace
        self.sessions_dir = ensure_dir(Path.home() / ".nanobot" / "sessions")
        self._cache: OrderedDict[str, Session] = OrderedDict()
        self.max_cache_size = max_cache_size
    
    def _get_session_path(self, key: str) -> Path:
        """Get the file path for a session."""
        safe_key = safe_filename(key.replace(":", "_"))
        return self.sessions_dir / f"{safe_key}.jsonl"
    
    def get_or_create(self, key: str) -> Session:
        """
        Get an existing session or create a new one.

        Args:
            key: Session key (usually channel:chat_id).

        Returns:
            The session.
        """
        # Check cache (and move to end for LRU)
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]

        # Try to load from disk
        session = self._load(key)
        if session is None:
            session = Session(key=key)

        # Add to cache with LRU eviction
        self._cache[key] = session
        self._cache.move_to_end(key)

        # Evict oldest if cache is full
        if len(self._cache) > self.max_cache_size:
            # Save and remove oldest session
            oldest_key, oldest_session = self._cache.popitem(last=False)
            self._save(oldest_session)
            logger.debug(f"Evicted session {oldest_key} from cache (LRU)")

        return session
    
    def _load(self, key: str) -> Session | None:
        """Load a session from disk."""
        path = self._get_session_path(key)

        if not path.exists():
            return None

        try:
            messages = []
            metadata = {}
            created_at = None
            last_consolidated = 0

            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue

                    data = json.loads(line)

                    if data.get("_type") == "metadata":
                        metadata = data.get("metadata", {})
                        created_at = datetime.fromisoformat(data["created_at"]) if data.get("created_at") else None
                        last_consolidated = data.get("last_consolidated", 0)
                    else:
                        messages.append(data)

            return Session(
                key=key,
                messages=messages,
                created_at=created_at or datetime.now(),
                metadata=metadata,
                last_consolidated=last_consolidated
            )
        except Exception as e:
            logger.warning(f"Failed to load session {key}: {e}")
            return None
    
    def save(self, session: Session) -> None:
        """Save a session to disk."""
        self._save(session)
        # Update cache position for LRU
        if session.key in self._cache:
            self._cache.move_to_end(session.key)

    def _save(self, session: Session) -> None:
        """Internal save method."""
        path = self._get_session_path(session.key)

        with open(path, "w") as f:
            metadata_line = {
                "_type": "metadata",
                "created_at": session.created_at.isoformat(),
                "updated_at": session.updated_at.isoformat(),
                "metadata": session.metadata,
                "last_consolidated": session.last_consolidated
            }
            f.write(json.dumps(metadata_line) + "\n")

            # Write messages
            for msg in session.messages:
                f.write(json.dumps(msg) + "\n")

        self._cache[session.key] = session
    
    def invalidate(self, key: str) -> None:
        """Remove a session from the in-memory cache."""
        self._cache.pop(key, None)
    
    def list_sessions(self) -> list[dict[str, Any]]:
        """
        List all sessions.
        
        Returns:
            List of session info dicts.
        """
        sessions = []
        
        for path in self.sessions_dir.glob("*.jsonl"):
            try:
                # Read just the metadata line
                with open(path) as f:
                    first_line = f.readline().strip()
                    if first_line:
                        data = json.loads(first_line)
                        if data.get("_type") == "metadata":
                            sessions.append({
                                "key": path.stem.replace("_", ":"),
                                "created_at": data.get("created_at"),
                                "updated_at": data.get("updated_at"),
                                "path": str(path)
                            })
            except Exception:
                continue
        
        return sorted(sessions, key=lambda x: x.get("updated_at", ""), reverse=True)

    def flush_cache(self) -> None:
        """
        Save all cached sessions to disk and clear the cache.
        Useful for periodic cleanup to prevent memory leaks.
        """
        logger.info(f"Flushing {len(self._cache)} sessions from cache")
        for session in self._cache.values():
            try:
                self._save(session)
            except Exception as e:
                logger.error(f"Failed to save session {session.key}: {e}")
        self._cache.clear()

    def get_cache_stats(self) -> dict[str, Any]:
        """Get cache statistics for monitoring."""
        return {
            "cached_sessions": len(self._cache),
            "max_cache_size": self.max_cache_size,
            "cache_usage_percent": (len(self._cache) / self.max_cache_size * 100) if self.max_cache_size > 0 else 0
        }
