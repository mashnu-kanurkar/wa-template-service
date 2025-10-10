from .gupshup import GupshupProvider


def get_provider(name, **kwargs):
    if name == 'gupshup':
        return GupshupProvider(**kwargs)
    raise ValueError('Unknown provider')
