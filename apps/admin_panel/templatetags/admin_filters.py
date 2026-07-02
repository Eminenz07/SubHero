from django import template

register = template.Library()

@register.filter(name='dict_get')
def dict_get(dictionary, key):
    """
    Retrieves value from dictionary by key.
    Usage in templates: {{ dict_data|dict_get:key_name }}
    """
    if not isinstance(dictionary, dict):
        return None
    return dictionary.get(key)
