class AgentError(Exception): pass
class ConfigurationError(AgentError): pass
class ToolNotFoundError(AgentError): pass
class PermissionDeniedError(AgentError): pass
class ParseError(AgentError): pass
class ContextWindowError(AgentError): pass
