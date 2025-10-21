import json
import logging
import os
from django.shortcuts import get_object_or_404
from rest_framework.views import APIView
from celery.result import AsyncResult
from rest_framework import viewsets, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.decorators import action, api_view
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied, ValidationError, NotFound
from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi
from django.db import IntegrityError, transaction
from django.core.files.storage import default_storage
from wa_templates.utils.google_sheets import REQUIRED_FIELDS

from .models import CatalogMetadata, WhatsAppTemplate, Organisation, ProviderAppInstance
from .serializers import CatalogMetadataSerializer, WhatsAppTemplateSerializer, OrganisationSerializer, ProviderAppInstanceSerializer
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
        provider_app_instance_app_id = self.kwargs.get("provider_app_instance_app_id")
        logger.debug('Extracting org_id and app_id from request: %s, %s', org_id, app_id or provider_app_instance_app_id)

        if not org_id:
            raise PermissionDenied("Missing org_id in JWT")
        if not app_id and not provider_app_instance_app_id:
                raise ValidationError({"app_id": "Path parameter 'app_id' is required."})
        return org_id, app_id if app_id else provider_app_instance_app_id

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
            return qs.filter(org_id=org_id, provider_app_instance_app_id__app_id=app_id)

        return qs.filter(org_id=org_id, provider_app_instance_app_id__app_id=app_id, isDeleted='none')

    @swagger_auto_schema(
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            properties={
                'org_id': openapi.Schema(type=openapi.TYPE_STRING, description='External org identifier'),
                'elementName': openapi.Schema(type=openapi.TYPE_STRING),
                'templateType': openapi.Schema(type=openapi.TYPE_STRING, description='TEXT|IMAGE|VIDEO|DOCUMENT|CAROUSEL|CATALOG'),
                'content': openapi.Schema(type=openapi.TYPE_STRING),
                'media_url': openapi.Schema(type=openapi.TYPE_STRING),
                'payload': openapi.Schema(type=openapi.TYPE_OBJECT)
            },
            example={
                'org_id': 'org_abc',
                'elementName': 'otp_template',
                'templateType': 'TEXT',
                'content': 'your otp is {{1}}',
                'media_url': None,
                'payload': {'elementName': 'text_element1', 'languageCode': 'en', 'content': 'your otp is {{1}}', 'category': 'MARKETING', 'vertical': 'Internal_vertical', 'example': 'your otp is {{1}}'}
            }
        )
    )
    def perform_create(self, serializer):
        logger.debug('Performing create for WhatsAppTemplate')
        org_id, app_id = self.get_org_and_app()

        user_id = getattr(self.request.user, "user_id", None)
        if not user_id:
            raise PermissionDenied("Missing user_id in JWT")

        try:
            organisation_instance = Organisation.objects.get(id=org_id)
        except Organisation.DoesNotExist:
            raise ValidationError(f"Organisation with id '{org_id}' not found.")
        
        try:
            provider_instance = ProviderAppInstance.objects.filter(organisation_id=org_id, app_id=app_id).first()
        except ProviderAppInstance.DoesNotExist:
            raise ValidationError(f"ProviderAppInstance with app_id '{app_id}' not found for organisation '{org_id}'.")
        
        serializer.validated_data['org_id'] = organisation_instance
        serializer.validated_data['provider_app_instance_app_id'] = provider_instance
        serializer.validated_data['created_by'] = user_id
        
        # Check if a template with the same name already exists in the filtered queryset
        template_elementName = serializer.validated_data.get('elementName')
        template_language = serializer.validated_data.get('languageCode', 'en')
                # Get the queryset filtered by org and app instance (using your existing logic)
        
        qs = WhatsAppTemplate.objects.filter(org_id=org_id, provider_app_instance_app_id__app_id=app_id)
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
        from .tasks import update_template_with_provider
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
        from .tasks import delete_template_with_provider
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
        from .tasks import submit_template_for_approval
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
    
    def sync_from_provider(self, request, app_id=None):
        from .tasks import sync_templates_for_app_id
        logger.debug('Syncing templates from provider (app_id=%s)', app_id)
        org_id, app_id = self.get_org_and_app()
        try:
            # enqueue celery task
            logger.debug('Enqueuing sync task for templates')
            res = sync_templates_for_app_id.delay( app_id, org_id)
            if not res:
                logger.error('Failed to enqueue sync_templates_for_app_id task for appId %s', app_id)
                return Response({'detail': 'Failed to enqueue task'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            logger.info('Templates syn operation queued for appId %s, task id: %s',app_id, res.id)
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
def templateTypes(request):
    types = [{'key': k, 'label': v} for k, v in WhatsAppTemplate.templateTypeS]
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
    from .tasks import process_gupshup_webhook
    logger.debug('Received Gupshup webhook: %s', request.data)
    data = request.data
    event_type = data.get('type')
    if not event_type == 'template-event':
        return Response({'detail': 'template-event'}, status=202)
    try:
        processed = process_gupshup_webhook.delay(data)
        if processed:
            return Response({'detail': 'updated'}, status=202)
        else:
            return Response({'detail': 'Failed'}, status=404)
    except Exception as e:
        logger.error('Exception while processing payload')
        return Response({'detail': 'Failed'}, status=404)

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
        user_id = getattr(self.request.user, "user_id", None)
        if not user_id:
            raise PermissionDenied("Missing user_id in JWT")
        if not org_id:
            raise PermissionDenied("Missing org_id in JWT")
        serializer.validated_data['organisation_id'] = org_id
        serializer.validated_data['created_by'] = user_id
        serializer.save()


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
    
class CatalogMetadataViewSet(OrgAppAwareViewSet):
    """
    Provides CRUD operations for Catalog Metadata.
    """
    queryset = CatalogMetadata.objects.all()
    serializer_class = CatalogMetadataSerializer
    #lookup_field = 'provider_app_instance_app_id'
    # permission_classes = [IsAuthenticated] # Add proper permissions

    ermission_classes = [IsAuthenticated]

    def get_metadata(self):
        app_id = self.kwargs.get("app_id")
        return get_object_or_404(CatalogMetadata, provider_app_instance_app_id=app_id)
    
    def retrieve(self, request, *args, **kwargs):
        catalog = self.get_metadata()
        serializer = CatalogMetadataSerializer(catalog)
        return Response(serializer.data)
    
    def update(self,  request, *args, **kwargs):
        catalog = self.get_metadata()
        mutable_data = request.data.copy()
        serializer = CatalogMetadataSerializer(catalog, data=mutable_data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(serializer.data)


    def perform_create(self, serializer):
        logger.debug('Performing create for catalog metadata')

        org_id, app_id = self.get_org_and_app()

        try:
            organisation_instance = Organisation.objects.get(id=org_id)
        except Organisation.DoesNotExist:
            raise ValidationError(f"Organisation with id '{org_id}' not found.")
        
        provider_instance = ProviderAppInstance.objects.filter(
            organisation_id=organisation_instance.id, app_id=app_id
        ).first()

        if not provider_instance:
            raise ValidationError(f"ProviderAppInstance with app_id '{app_id}' not found for organisation '{org_id}'.")

        user_id = getattr(self.request.user, "user_id", None)
        if user_id is None:
            raise ValidationError("Authenticated user required to create catalog metadata.")
        
        # Save with unique constraint handling
        try:
            with transaction.atomic():
                serializer.save(
                    created_by=user_id,
                    provider_app_instance_app_id=provider_instance
                )
        except IntegrityError as e:
            logger.warning(f"Duplicate catalog creation attempt for provider_app_instance_app_id={app_id}")
            raise ValidationError("Only one catalog can be created per WABA account.")


    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            self.perform_create(serializer)
        except ValidationError as e:
            # This will already be a nice message
            raise e
        except IntegrityError:
            # Just in case it bubbles up
            raise ValidationError("Only one catalog can be created per WABA account.")
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    def destroy(self, request, *args, **kwargs):
        """Custom destroy to log the deletion."""
        instance = self.get_metadata()
        logger.warning(f"Catalog metadata deletion initiated for ID: {instance.id} (URL: {instance.catalog_url})")
        instance.delete()
        return Response(status=204)
    

class CatalogDataViewSet(viewsets.ViewSet):
    """
    Handle catalog data CRUD via background tasks.
    All operations (GET, POST, PUT/PATCH, DELETE) return a Celery task ID immediately.
    """
    permission_classes = [IsAuthenticated]

    def get_metadata(self):
        app_id = self.kwargs.get("app_id")
        logger.debug('Fetching CatalogMetadata for app_id: %s', app_id)
        meta = get_object_or_404(CatalogMetadata, provider_app_instance_app_id=app_id)
        logger.debug('Found CatalogMetadata: %s', meta)
        return meta
    
    def retrieve(self, request, *args, **kwargs):
        """Read catalog data via background task."""
        from wa_templates.tasks import read_catalog_data_task
        logger.debug("reading catalog data")

        catalog = self.get_metadata()
        catalog_url = catalog.catalog_url
        service_file_content = catalog.google_service_file.read().decode('utf-8')
        logger.debug('Reading catalog data via task for catalog %s', catalog_url)
        logger.debug('service file content: %s', service_file_content)
        task = read_catalog_data_task.delay(
            catalog_url,
            service_file_content
        )
        return Response({"task_id": task.id}, status=status.HTTP_202_ACCEPTED)
    
    def batch(self, request, *args, **kwargs):
        from wa_templates.tasks import sync_catalog_product_batch_task
        payload = request.data
        add_list = payload.get("add", [])
        update_list = payload.get("update", [])
        delete_list = payload.get("delete", [])

        # --- VALIDATION ---
        for p in add_list:
            missing = [f for f in REQUIRED_FIELDS if not p.get(f)]
            if missing:
                return Response(
                    {"error": f"Missing required fields for add: {missing}", "product": p},
                    status=400
                )
        for p in update_list:
            if not p.get("id"):
                return Response({"error": "ID required for update", "product": p}, status=400)

        # --- TRIGGER TASK ---
        catalog = self.get_metadata()
        catalog_url = catalog.catalog_url
        service_file_content = catalog.google_service_file.read().decode("utf-8")

        payload = {"add": add_list, "update": update_list, "delete": delete_list}
        task = sync_catalog_product_batch_task.delay(
            catalog_url,
            service_file_content,
            json.dumps(payload)
        )
        logger.info(f"Triggered batch catalog task {task.id}")
        return Response({"task_id": task.id}, status=status.HTTP_202_ACCEPTED)

    def create(self, request, *args, **kwargs):
        """Add new product(s) to the catalog via task."""
        from wa_templates.tasks import sync_catalog_product_batch_task
        payload = request.data
        add_list = payload.get("add", [])

        # --- VALIDATION ---
        for p in add_list:
            missing = [f for f in REQUIRED_FIELDS if not p.get(f)]
            if missing:
                return Response(
                    {"error": f"Missing required fields for add: {missing}", "product": p},
                    status=400
                )
            
        logger.debug("adding catalog data")
        # --- TRIGGER TASK ---
        catalog = self.get_metadata()
        catalog_url = catalog.catalog_url
        service_file_content = catalog.google_service_file.read().decode("utf-8")
        payload = {"add": add_list, "update": None, "delete": None}

        task = sync_catalog_product_batch_task.delay(
            catalog_url,
            service_file_content,
            json.dumps(payload)
        )
        logger.info(f"Triggered batch catalog task {task.id}")
        return Response({"task_id": task.id}, status=status.HTTP_202_ACCEPTED)

    # def update(self, request, *args, **kwargs):
    #     from wa_templates.tasks import update_catalog_product_task
    #     logger.debug("updating catalog data")
    #     catalog = self.get_metadata()
    #     catalog_url = catalog.catalog_url
    #     service_file_content = catalog.google_service_file.read().decode('utf-8')
    #     logger.debug('Updating catalog product via task for catalog %s', catalog_url)
    #     logger.debug('service file content: %s', service_file_content)
    #     task = update_catalog_product_task.delay(
    #         catalog_url,
    #         service_file_content,
    #         request.data
    #     )
    #     return Response({"task_id": task.id}, status=status.HTTP_202_ACCEPTED)

    # def partial_update(self, request, *args, **kwargs):
    #     from wa_templates.tasks import update_catalog_product_task
    #     logger.debug("partially updating catalog data")
    #     catalog = self.get_metadata()
    #     catalog_url = catalog.catalog_url
    #     service_file_content = catalog.google_service_file.read().decode('utf-8')
    #     logger.debug('Patial updating catalog product via task for catalog %s', catalog_url)
    #     logger.debug('service file content: %s', service_file_content)
    #     task = update_catalog_product_task.delay(
    #         catalog_url,
    #         service_file_content,
    #         request.data,
    #         partial=True
    #     )
    #     return Response({"task_id": task.id}, status=status.HTTP_202_ACCEPTED)

    def destroy(self, request, *args, **kwargs):
        from wa_templates.tasks import sync_catalog_product_batch_task
        payload = request.data
        delete_list = payload.get("delete", [])

        logger.debug("deleting catalog data")
        catalog = self.get_metadata()
        catalog_url = catalog.catalog_url
        service_file_content = catalog.google_service_file.read().decode('utf-8')

        logger.debug('deleting %d catalog product via task for catalog %s',len(delete_list), catalog_url)
        logger.debug('service file content: %s', service_file_content)

        payload = {"add": None, "update": None, "delete": delete_list}
        task = sync_catalog_product_batch_task.delay(
            catalog_url,
            service_file_content,
            json.dumps(payload)
        )
        logger.info(f"Triggered batch catalog task {task.id}")
        return Response({"task_id": task.id}, status=status.HTTP_202_ACCEPTED)


    

    