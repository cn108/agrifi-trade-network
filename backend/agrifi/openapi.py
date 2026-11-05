"""Optional OpenAPI annotations.

`drf-spectacular` is a build/documentation dependency. These fallbacks keep the application
importable (and behaviour identical) when it is not installed."""
try:
    from drf_spectacular.types import OpenApiTypes
    from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_field
except ImportError:
    class _Types:
        def __getattr__(self, name):
            return name

    OpenApiTypes = _Types()

    def OpenApiParameter(*args, **kwargs):  # noqa: N802
        return None

    def extend_schema(*args, **kwargs):
        return lambda target: target

    def extend_schema_field(*args, **kwargs):
        return lambda target: target

__all__ = ['OpenApiParameter', 'OpenApiTypes', 'extend_schema', 'extend_schema_field']
