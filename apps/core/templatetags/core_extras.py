from django import template

register = template.Library()


@register.filter(name="split")
def split(value, delimiter=","):
    """Split a string into a list. Usage: {{ value|split:"|" }}"""
    if not isinstance(value, str):
        return []
    return value.split(delimiter)
