from rest_framework import viewsets, status
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response
from .models import WhatsAppTemplate
from .serializers import WhatsAppTemplateSerializer
from .tasks import submit_template_for_approval
from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi
from .auth import IsTenantMember
from . import template_schemas


class WhatsAppTemplateViewSet(viewsets.ModelViewSet):
    queryset = WhatsAppTemplate.objects.all()
    serializer_class = WhatsAppTemplateSerializer
    permission_classes = [IsTenantMember]

    def get_queryset(self):
        qs = super().get_queryset()
        org_id = self.request.query_params.get('org_id') or self.request.query_params.get('tenant')
        if org_id:
            qs = qs.filter(org_id=org_id)
        return qs

    @swagger_auto_schema(
            request_body=openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    'org_id': openapi.Schema(type=openapi.TYPE_STRING, description='External org identifier'),
                    'name': openapi.Schema(type=openapi.TYPE_STRING),
                    'template_type': openapi.Schema(type=openapi.TYPE_STRING, description='TEXT|IMAGE|VIDEO|DOCUMENT|CAROUSEL|CATALOG'),
                    'content': openapi.Schema(type=openapi.TYPE_STRING),
                    'media_url': openapi.Schema(type=openapi.TYPE_STRING),
                    'payload': openapi.Schema(type=openapi.TYPE_OBJECT)
                },
                example={
                    'org_id': 'org_abc',
                    'name': 'otp_template',
                    'template_type': 'TEXT',
                    'content': 'your otp is {{1}}',
                    'media_url': None,
                    'payload': {'elementName': 'text_element1', 'languageCode': 'en', 'content': 'your otp is {{1}}', 'category': 'MARKETING', 'vertical': 'Internal_vertical', 'example': 'your otp is {{1}}'}
                }
            )
    )
    def perform_create(self, serializer):
        # set status to draft on create and default org_id to authenticated user's org_id
        org_id = None
        if getattr(self.request, 'user', None) and hasattr(self.request.user, 'org_id'):
            org_id = self.request.user.org_id
        if org_id:
            serializer.save(status='draft', org_id=org_id)
        else:
            serializer.save(status='draft')

    @action(detail=True, methods=['post'])
    @swagger_auto_schema(
        operation_description='Upload media if present and submit template to provider for approval.',
        responses={
            202: openapi.Response(description='Accepted', schema=openapi.Schema(type=openapi.TYPE_OBJECT, properties={'detail': openapi.Schema(type=openapi.TYPE_STRING)}), examples={'application/json': {'detail': 'Submitted for approval'}}),
        }
    )
    def send_for_approval(self, request, pk=None):
        template = self.get_object()
        # enqueue celery task
        submit_template_for_approval.delay(template.id)
        template.status = 'pending'
        template.save()
        return Response({'detail': 'Submitted for approval'}, status=status.HTTP_202_ACCEPTED)


@api_view(['GET'])
def template_types(request):
    # expose available template types for front-end selection
    types = [{'key': k, 'label': v} for k, v in WhatsAppTemplate.TEMPLATE_TYPES]
    # also provide schema for each type to help frontend build forms
    schemas = template_schemas.SCHEMAS
    return Response({'types': types, 'schemas': schemas})


@api_view(['POST'])
@swagger_auto_schema(
    method='post',
    request_body=openapi.Schema(
        type=openapi.TYPE_OBJECT,
        properties={
            'template_id': openapi.Schema(type=openapi.TYPE_INTEGER),
            'status': openapi.Schema(type=openapi.TYPE_STRING, description='approved|rejected'),
            'extra': openapi.Schema(type=openapi.TYPE_OBJECT)
        },
        example={'template_id': 1, 'status': 'approved', 'extra': {'provider_id': 'abc123'}}
    ),
    responses={200: openapi.Response('ok', schema=openapi.Schema(type=openapi.TYPE_OBJECT, properties={'detail': openapi.Schema(type=openapi.TYPE_STRING)}), examples={'application/json': {'detail': 'updated'}}), 404: 'not found'}
)
@api_view(['POST'])
def gupshup_webhook(request):
    # Example webhook receiver - expects JSON with template id and status
    data = request.data
    template_id = data.get('template_id')
    status_ = data.get('status')
    try:
        t = WhatsAppTemplate.objects.get(id=template_id)
    except WhatsAppTemplate.DoesNotExist:
        return Response({'detail': 'not found'}, status=404)
    if status_ == 'approved':
        t.status = 'approved'
    elif status_ == 'rejected':
        t.status = 'rejected'
    t.provider_metadata.update({'last_webhook': data})
    t.save()
    return Response({'detail': 'updated'})
