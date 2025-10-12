import logging
from rest_framework.views import APIView
from celery.result import AsyncResult
from rest_framework import viewsets, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.decorators import action, api_view
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied, ValidationError, NotFound, AuthenticationFailed
from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi

from .models import WhatsAppTemplate, Organisation, ProviderAppInstance
from .serializers import WhatsAppTemplateSerializer, OrganisationSerializer, ProviderAppInstanceSerializer
from .tasks import delete_template_with_provider, submit_template_for_approval, update_template_with_provider
from .auth import JWTAuthentication
from . import template_schemas

logger = logging.getLogger(__name__)

# ---------------------------
# Base ViewSet for org & app
# ---------------------------
class OrgAppAwareViewSet(viewsets.ModelViewSet):
    def get_org_and_app(self):
        # If schema generation, return dummy values to avoid errors
        if getattr(self, "swagger_fake_view", False):
            return "org_dummy", "app_dummy"

        # Extract org_id and app_id from request
        org_id = getattr(self.request.user, "org_id", None)
        app_id = self.kwargs.get("app_id")
        logger.debug('Extracting org_id and app_id from request: %s, %s', org_id, app_id)

        if not org_id:
            raise PermissionDenied("Missing org_id in JWT")
        if not app_id:
            raise ValidationError({"app_id": "Path parameter 'app_id' is required."})
        return org_id, app_id

# ---------------------------
# WhatsAppTemplate ViewSet
# ---------------------------
class WhatsAppTemplateViewSet(OrgAppAwareViewSet):
    queryset = WhatsAppTemplate.objects.all()
    serializer_class = WhatsAppTemplateSerializer
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return WhatsAppTemplate.objects.none()

        logger.debug('Getting queryset for WhatsAppTemplateViewSet')
        qs = super().get_queryset()
        org_id, app_id = self.get_org_and_app()

        is_debug = self.request.query_params.get('debug', 'false').lower() == 'true'
        if is_debug:
            logger.debug('Debug mode enabled, returning all templates for org_id %s and app_id %s', org_id, app_id)
            return qs.filter(org_id=org_id, provider_app_instance_app_id=app_id)

        return qs.filter(org_id=org_id, provider_app_instance_app_id=app_id, isDeleted='none')

    @swagger_auto_schema(
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            properties={
                'org_id': openapi.Schema(type=openapi.TYPE_STRING, description='External org identifier'),
                'elementName': openapi.Schema(type=openapi.TYPE_STRING),
                'template_type': openapi.Schema(type=openapi.TYPE_STRING, description='TEXT|IMAGE|VIDEO|DOCUMENT|CAROUSEL|CATALOG'),
                'content': openapi.Schema(type=openapi.TYPE_STRING),
                'media_url': openapi.Schema(type=openapi.TYPE_STRING),
                'payload': openapi.Schema(type=openapi.TYPE_OBJECT)
            },
            example={
                'org_id': 'org_abc',
                'elementName': 'otp_template',
                'template_type': 'TEXT',
                'content': 'your otp is {{1}}',
                'media_url': None,
                'payload': {'elementName': 'text_element1', 'languageCode': 'en', 'content': 'your otp is {{1}}', 'category': 'MARKETING', 'vertical': 'Internal_vertical', 'example': 'your otp is {{1}}'}
            }
        )
    )
    def perform_create(self, serializer):
        logger.debug('Performing create for WhatsAppTemplate')
        org_id, app_id = self.get_org_and_app()

        # Get the queryset filtered by org and app instance (using your existing logic)
        qs = WhatsAppTemplate.objects.filter(org_id=org_id, provider_app_instance_app_id__app_id=app_id)

        organisation_instance = Organisation.objects.get(id=org_id)
        if not organisation_instance:
            raise NotFound(f"Organisation with id '{org_id}' not found.")
        
        provider_instance = ProviderAppInstance.objects.filter(organisation_id=org_id, app_id=app_id).first()
        if not provider_instance:
            raise NotFound(f"ProviderAppInstance with app_id '{app_id}' not found for organisation '{org_id}'.")
        serializer.validated_data['org_id'] = organisation_instance
        serializer.validated_data['provider_app_instance_app_id'] = provider_instance
        
        # Check if a template with the same name already exists in the filtered queryset
        template_elementName = serializer.validated_data.get('elementName')
        template_language = serializer.validated_data.get('languageCode', 'en')
        if qs.filter(elementName=template_elementName, languageCode=template_language).exists():
            raise ValidationError(
                {"elementName": f"A WhatsApp template with the name '{template_elementName}' and languageCode '{template_language}' already exists for this organization and app."}
            )

        # Find related provider instance
        try:
            provider_instance = ProviderAppInstance.objects.get(
                organisation_id=org_id,
                app_id=app_id
            )
            
            # set status to draft on create and default org_id to authenticated user's org_id
            serializer.save(
                status='draft', 
                org_id=Organisation.objects.get(pk=org_id), 
                provider_app_instance_app_id=provider_instance
            )
        except Organisation.DoesNotExist:
            raise ValidationError({"org_id": f"Organization '{org_id}' not found."})
        except ProviderAppInstance.DoesNotExist:
            raise ValidationError({"app_id": f"Provider app '{app_id}' not found for this org"})
        
    def perform_update(self, serializer):
        logger.debug('Performing update for WhatsAppTemplate and submitting for approval')
        org_id, app_id = self.get_org_and_app()
        # Save local changes first
        instance = serializer.save()
        try:
            # Enqueue celery task for update
            res = update_template_with_provider.delay(instance.id, app_id, org_id )
            return Response({'message': 'Task enqueued', 'task_id': res.id}, status=status.HTTP_202_ACCEPTED)

        except ProviderAppInstance.DoesNotExist:
            raise ValidationError({"app_id": f"Provider app '{app_id}' not found for this org"})
    
    def perform_destroy(self, instance):
        logger.debug('Performing destroy for WhatsAppTemplate and notifying provider')
        org_id, app_id = self.get_org_and_app()
        try:
            # Enqueue celery task for deletion
            res = delete_template_with_provider.delay(instance.id, app_id, org_id)
            # Delete local instance *after* task is successfully enqueued
            
            instance.isDeleted = 'Processing'
            instance.save()
            return Response({'message': 'Task enqueued', 'task_id': res.id}, status=status.HTTP_202_ACCEPTED)

        except ProviderAppInstance.DoesNotExist:
            # If provider is missing, delete locally and log warning
            logger.warning("ProviderAppInstance missing for org %s, app %s. Deleting local template only.", org_id, app_id)
            instance.delete()
        except Exception as e:
            logger.error("Error during template deletion process: %s", e)
            raise
        

    @action(detail=True, methods=['post'])
    @swagger_auto_schema(
        operation_description='Upload media if present and submit template to provider for approval.',
        responses={
            202: openapi.Response(
                description='Accepted',
                schema=openapi.Schema(
                    type=openapi.TYPE_OBJECT,
                    properties={'detail': openapi.Schema(type=openapi.TYPE_STRING)}
                ),
                examples={'application/json': {'detail': 'Submitted for approval'}}
            ),
        }
    )
    def send_for_approval(self, request, app_id=None, pk=None):
        logger.debug('Sending template %s for approval (app_id=%s)', pk, app_id)
        org_id, app_id = self.get_org_and_app()
        try:
            # enqueue celery task
            logger.debug('Enqueuing submit_template_for_approval task for template %s', pk)
            res = submit_template_for_approval.delay(pk, app_id, org_id)
            if not res:
                logger.error('Failed to enqueue submit_template_for_approval task for template %s', pk)
                return Response({'detail': 'Failed to enqueue task'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            logger.info('Template %s submitted for approval, task id: %s', pk, res.id)
            return Response({'message': 'Task enqueued', 'task_id': res.id}, status=status.HTTP_202_ACCEPTED)

        except ProviderAppInstance.DoesNotExist:
            logger.error('ProviderAppInstance not found for org_id %s and app_id %s', org_id, app_id)
            return Response({"error": "Invalid organisation or app_id"}, status=404)

# ---------------------------
# Template types endpoint
# ---------------------------
@api_view(['GET'])
@swagger_auto_schema(
    operation_description="Return available template types and schemas",
    responses={
        200: openapi.Response(
            description="Template types and schemas",
            schema=openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    'types': openapi.Schema(
                        type=openapi.TYPE_ARRAY,
                        items=openapi.Items(type=openapi.TYPE_OBJECT)
                    ),
                    'schemas': openapi.Schema(type=openapi.TYPE_OBJECT)
                }
            )
        )
    }
)
def template_types(request):
    types = [{'key': k, 'label': v} for k, v in WhatsAppTemplate.TEMPLATE_TYPES]
    schemas = template_schemas.SCHEMAS
    return Response({'types': types, 'schemas': schemas})

# ---------------------------
# Gupshup webhook endpoint
# ---------------------------
@api_view(['POST'])
@swagger_auto_schema(
    request_body=openapi.Schema(
        type=openapi.TYPE_OBJECT,
        properties={
            'template_id': openapi.Schema(type=openapi.TYPE_INTEGER),
            'status': openapi.Schema(type=openapi.TYPE_STRING, description='approved|rejected'),
            'extra': openapi.Schema(type=openapi.TYPE_OBJECT)
        },
        example={'template_id': 1, 'status': 'approved', 'extra': {'provider_id': 'abc123'}}
    ),
    responses={
        200: openapi.Response(
            'ok',
            schema=openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={'detail': openapi.Schema(type=openapi.TYPE_STRING)}
            ),
            examples={'application/json': {'detail': 'updated'}}
        ),
        404: 'not found'
    }
)
def gupshup_webhook(request):
    logger.debug('Received Gupshup webhook: %s', request.data)
    data = request.data
    template_id = data.get('template_id')
    status_ = data.get('status')
    try:
        logger.debug('Fetching WhatsAppTemplate with id: %s', template_id)
        t = WhatsAppTemplate.objects.get(id=template_id)
    except WhatsAppTemplate.DoesNotExist:
        logger.error('WhatsAppTemplate not found with id: %s', template_id)
        return Response({'detail': 'not found'}, status=404)

    if status_ == 'approved':
        t.status = 'approved'
    elif status_ == 'rejected':
        t.status = 'rejected'

    logger.debug('Updating template %s status to %s', template_id, t.status)
    t.provider_metadata.update({'last_webhook': data})
    t.save()
    return Response({'detail': 'updated'})

# ---------------------------
# Organisation ViewSet
# ---------------------------
class OrganisationViewSet(viewsets.ModelViewSet):
    queryset = Organisation.objects.all()
    serializer_class = OrganisationSerializer
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        ##return all Organisation
        return Organisation.objects.all()


# ---------------------------
# ProviderAppInstance ViewSet
# ---------------------------
class ProviderAppInstanceViewSet(viewsets.ModelViewSet):
    serializer_class = ProviderAppInstanceSerializer
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get_serializer_context(self):
        """
        Injects the organization ID from the JWT/request into the serializer context.
        """
        context = super().get_serializer_context()
        try:
            context['org_id'] = self.request.user.org_id  
        except AttributeError:
            # Handle case where user or org_id is missing (should be caught by IsAuthenticated earlier)
            pass 
            
        return context

    def get_queryset(self):
        logger.debug('Getting queryset for ProviderAppInstanceViewSet')
        org_id = getattr(self.request.user, "org_id", None)
        if not org_id:
            raise PermissionDenied("Missing org_id in JWT")
        return ProviderAppInstance.objects.filter(organisation_id=org_id)

    def perform_create(self, serializer):
        logger.debug('Performing create for ProviderAppInstance')
        org_id = getattr(self.request.user, "org_id", None)
        if not org_id:
            raise PermissionDenied("Missing org_id in JWT")
        serializer.save(organisation_id=org_id)


class TaskStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, task_id):
        """
        Retrieves the status and result of a Celery task.
        """
        # Get the task object using the ID
        task = AsyncResult(str(task_id))

        response_data = {
            'task_id': task.id,
            'status': task.status,
            'ready': task.ready(),
        }

        # If the task is finished (SUCCESS, FAILURE, RETRY, etc.), include the result/error
        if task.state == 'SUCCESS':
            response_data['result'] = task.result
        elif task.state in ('FAILURE', 'REVOKED'):
            # Celery stores the exception/traceback in task.info
            response_data['result'] = str(task.info)
        
        # You can add custom handling for PENDING, STARTED, RETRY states if needed

        return Response(response_data)
