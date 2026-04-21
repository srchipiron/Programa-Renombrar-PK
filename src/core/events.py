"""
Event system for decoupled communication between components.
"""
from typing import Dict, List, Callable, Any
from dataclasses import dataclass
from enum import Enum
import threading
import queue
import logging

logger = logging.getLogger(__name__)

class EventType(Enum):
    """Application event types."""
    # File operations
    FOLDER_SELECTED = "folder_selected"
    KML_LOADED = "kml_loaded"
    PHOTOS_PROCESSED = "photos_processed"
    
    # Processing events
    ANALYSIS_STARTED = "analysis_started"
    ANALYSIS_PROGRESS = "analysis_progress"
    ANALYSIS_COMPLETED = "analysis_completed"
    ANALYSIS_FAILED = "analysis_failed"
    
    # Renaming events
    RENAME_STARTED = "rename_started"
    RENAME_PROGRESS = "rename_progress"
    RENAME_COMPLETED = "rename_completed"
    RENAME_FAILED = "rename_failed"
    
    # Configuration events
    CONFIG_CHANGED = "config_changed"
    
    # UI events
    STATUS_UPDATE = "status_update"
    LOG_MESSAGE = "log_message"
    
    # Error events
    ERROR_OCCURRED = "error_occurred"

@dataclass
class Event:
    """Event data container."""
    type: EventType
    data: Dict[str, Any] = None
    timestamp: float = None
    
    def __post_init__(self):
        if self.data is None:
            self.data = {}
        if self.timestamp is None:
            import time
            self.timestamp = time.time()

class EventManager:
    """Manages event-driven communication between components."""
    
    def __init__(self):
        self._listeners: Dict[EventType, List[Callable]] = {}
        self._event_queue = queue.Queue()
        self._running = False
        self._thread = None
        self._lock = threading.Lock()
    
    def subscribe(self, event_type: EventType, callback: Callable[[Event], None]) -> None:
        """Subscribe to an event type."""
        with self._lock:
            if event_type not in self._listeners:
                self._listeners[event_type] = []
            self._listeners[event_type].append(callback)
            logger.debug(f"Subscribed to {event_type.value}")
    
    def unsubscribe(self, event_type: EventType, callback: Callable[[Event], None]) -> None:
        """Unsubscribe from an event type."""
        with self._lock:
            if event_type in self._listeners:
                try:
                    self._listeners[event_type].remove(callback)
                    logger.debug(f"Unsubscribed from {event_type.value}")
                except ValueError:
                    pass  # Callback not found
    
    def emit(self, event_type: EventType, data: Dict[str, Any] = None) -> None:
        """Emit an event."""
        event = Event(event_type, data)
        self._event_queue.put(event)
        logger.debug(f"Emitted event: {event_type.value}")
    
    def start(self) -> None:
        """Start the event processing thread."""
        if self._running:
            return
        
        self._running = True
        self._thread = threading.Thread(target=self._process_events, daemon=True)
        self._thread.start()
        logger.info("Event manager started")
    
    def stop(self) -> None:
        """Stop the event processing thread."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=1.0)
        logger.info("Event manager stopped")
    
    def _process_events(self) -> None:
        """Process events from the queue."""
        while self._running:
            try:
                event = self._event_queue.get(timeout=0.1)
                self._dispatch_event(event)
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"Error processing event: {e}")
    
    def _dispatch_event(self, event: Event) -> None:
        """Dispatch event to all listeners."""
        with self._lock:
            listeners = self._listeners.get(event.type, [])
        
        for callback in listeners:
            try:
                callback(event)
            except Exception as e:
                logger.error(f"Error in event callback: {e}")

# Global event manager instance
_event_manager: EventManager = None

def get_event_manager() -> EventManager:
    """Get the global event manager instance."""
    global _event_manager
    if _event_manager is None:
        _event_manager = EventManager()
        _event_manager.start()
    return _event_manager

def emit_event(event_type: EventType, data: Dict[str, Any] = None) -> None:
    """Emit an event using the global event manager."""
    get_event_manager().emit(event_type, data)

def subscribe_to_event(event_type: EventType, callback: Callable[[Event], None]) -> None:
    """Subscribe to an event using the global event manager."""
    get_event_manager().subscribe(event_type, callback)
