from importlib import import_module

_REGISTRY = {
    'route_description': 'report_agents.route_description.agent:RouteDescriptionAgent',
    'route_comparison': 'report_agents.route_comparison.agent:RouteComparisonAgent',
    'route_compliance': 'report_agents.route_compliance.agent:RouteComplianceAgent',
}


def register_agent(identifier, entrypoint):
    """Python extension point; an agent exposes manifest and run(context)."""
    if identifier in _REGISTRY:
        raise ValueError('Agent ID已注册：'+identifier)
    if ':' not in entrypoint:
        raise ValueError('entrypoint格式为package.module:Class')
    _REGISTRY[identifier] = entrypoint


def agent_ids():
    return list(_REGISTRY)


def create_agent(identifier):
    if identifier not in _REGISTRY:
        raise ValueError('未注册Agent：'+identifier)
    module, classname = _REGISTRY[identifier].split(':', 1)
    return getattr(import_module(module), classname)()
