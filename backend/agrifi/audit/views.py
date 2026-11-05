from rest_framework import mixins, serializers, viewsets
from rest_framework.permissions import IsAuthenticated

from agrifi.accounts.models import UserRole
from agrifi.accounts.permissions import role_required

from .models import AuditEvent


class AuditEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = AuditEvent
        fields = (
            'id', 'created_at', 'actor', 'action', 'object_type', 'object_id',
            'request_id', 'metadata',
        )
        read_only_fields = fields


class AuditEventViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Read-only audit trail for operations administrators."""

    serializer_class = AuditEventSerializer
    permission_classes = [IsAuthenticated, role_required(UserRole.Role.OPERATIONS_ADMIN)]
    http_method_names = ['get', 'head', 'options']

    def get_queryset(self):
        queryset = AuditEvent.objects.all()
        params = self.request.query_params
        for field in ('action', 'object_type', 'object_id', 'request_id'):
            value = params.get(field)
            if value:
                queryset = queryset.filter(**{field: value})
        actor = params.get('actor')
        if actor:
            queryset = queryset.filter(actor=serializers.UUIDField().to_internal_value(actor))
        for param, lookup in (('created_after', 'created_at__gte'), ('created_before', 'created_at__lt')):
            value = params.get(param)
            if value:
                parsed = serializers.DateTimeField().to_internal_value(value)
                queryset = queryset.filter(**{lookup: parsed})
        return queryset
