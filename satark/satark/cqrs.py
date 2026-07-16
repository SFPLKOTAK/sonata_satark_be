import logging

logger = logging.getLogger("cqrs")

class Command:
    """Base class for all commands (write operations)"""
    pass

class Query:
    """Base class for all queries (read operations)"""
    pass

class CommandHandler:
    """Base class for command handlers"""
    def execute(self, command: Command):
        raise NotImplementedError("Subclasses must implement execute")

class QueryHandler:
    """Base class for query handlers"""
    def execute(self, query: Query):
        raise NotImplementedError("Subclasses must implement execute")

class CQRSDispatcher:
    """Dispatcher to route commands and queries to their respective handlers"""
    def __init__(self):
        self._command_handlers = {}
        self._query_handlers = {}

    def register_command(self, command_class, handler_instance):
        self._command_handlers[command_class] = handler_instance
        return self

    def register_query(self, query_class, handler_instance):
        self._query_handlers[query_class] = handler_instance
        return self

    def send(self, command: Command):
        """Send a command to its registered handler"""
        command_class = command.__class__
        if command_class not in self._command_handlers:
            raise ValueError(f"No handler registered for command {command_class.__name__}")
        
        handler = self._command_handlers[command_class]
        logger.debug(f"Dispatching command {command_class.__name__} to {handler.__class__.__name__}")
        return handler.execute(command)

    def query(self, query: Query):
        """Send a query to its registered handler"""
        query_class = query.__class__
        if query_class not in self._query_handlers:
            raise ValueError(f"No handler registered for query {query_class.__name__}")
        
        handler = self._query_handlers[query_class]
        logger.debug(f"Dispatching query {query_class.__name__} to {handler.__class__.__name__}")
        return handler.execute(query)

# Global dispatcher instance
dispatcher = CQRSDispatcher()
