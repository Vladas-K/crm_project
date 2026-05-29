from pathlib import Path

from django import template
from django.conf import settings
from django.templatetags.static import static

register = template.Library()


@register.simple_tag
def static_with_version(path):
    url = static(path)
    for static_dir in settings.STATICFILES_DIRS:
        file_path = Path(static_dir) / path
        if file_path.exists():
            return f"{url}?v={int(file_path.stat().st_mtime)}"
    return url
