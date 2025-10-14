import uuid
from rest_framework import serializers
from .models import WhatsAppTemplate, Organisation, ProviderAppInstance
from . import template_schemas
import logging
from django.core.exceptions import ObjectDoesNotExist

logger = logging.getLogger(__name__)

class WhatsAppTemplateSerializer(serializers.ModelSerializer):
    class Meta:
        model = WhatsAppTemplate
        fields = ('id', 'languageCode','vertical', 'footer', 
                  'allowTemplateCategoryChange', 'example', 'exampleHeader', 
                  'header','enableSample', 'templateType', 'category', 'content', 
                  'media_url','file_type', 'provider_metadata', 'status', 'created_at', 
                  'updated_at', 'payload', 'provider_template_id', 'containerMeta', 'createdOn', 'data', 'elementName', 'languagePolicy', 'meta',
                  'namespace', 'modifiedOn', 'priority', 'quality', 'retry', 'stage', 'wabaId', 'errorMessage', 'isDeleted',)
        

    def validate(self, data):
        # Validate templateType-specific rules
        logger.debug('Validating WhatsAppTemplate data: %s', data)
        ttype = data.get('templateType') or getattr(self.instance, 'templateType', None)
        if ttype not in dict(WhatsAppTemplate.templateTypeS):
            logger.error('Invalid template type: %s', ttype)
            raise serializers.ValidationError({'templateType': 'Invalid template type'})
        # Add type-specific validations
        if ttype == 'TEXT' and not data.get('content'):
            logger.error('Text templates require content')
            raise serializers.ValidationError({'content': 'Text templates require content'})

        # Validate payload JSON against schema rules for the selected type
        payload = data.get('payload')
        if payload is not None:
            logger.debug('Validating payload for template type %s: %s', ttype, payload)
            try:
                template_schemas.validate_payload(ttype, data)
            except template_schemas.PayloadValidationError as pve:
                # return the structured errors to frontend
                logger.error('Payload validation error: %s', pve.errors)
                raise serializers.ValidationError({'payload': pve.errors})
            except Exception as e:
                # fallback to string message
                logger.error('Payload validation exception: %s', str(e))    
                raise serializers.ValidationError({'payload': str(e)})

        return data

class OrganisationListSerializer(serializers.ModelSerializer):
    class Meta:
        model = Organisation
        fields = ['id', 'name']  # minimal info for list
        

class OrganisationSerializer(serializers.ModelSerializer):
    id = serializers.CharField(read_only=False, required=True)
    class Meta:
        model = Organisation
        fields = ["id", "name", "created_at"]
        read_only_fields = ['created_at']

    def validate_id(self, value):
        # Only run this check on creation (POST request, self.instance is None)
        if self.instance is None:
            try:
                # Check if an Organisation with this ID already exists
                self.Meta.model.objects.get(pk=value)
                
                # If it exists, raise a validation error
                raise serializers.ValidationError(
                    "Organization ID already exists. Use a PUT request to update."
                )
            except ObjectDoesNotExist:
                # If it doesn't exist, the ID is unique and valid for creation
                pass
                
        return value
    
    def validate(self, data):
        # to ensure Django doesn't try to change the PK or create a new object.
        if self.instance and 'id' in data:
            if data['id'] != self.instance.id:
                raise serializers.ValidationError({"id": "The organization ID cannot be changed."})
            # Remove 'id' from validated_data so ORM only saves other fields (like 'name')
            data.pop('id') 
            
        return data
    
    def update(self, instance, validated_data):
        # The PK is implicitly used from the URL/instance object.
        # Only update the fields intended for modification, like 'name'.
        instance.name = validated_data.get('name', instance.name)
        instance.save()
        return instance


class ProviderAppInstanceSerializer(serializers.ModelSerializer):
    app_id = serializers.CharField(read_only=False, required=False)
    app_token = serializers.CharField(write_only=True, required=True)
    phone_number = serializers.CharField(read_only=False, required=False)
    provider_name = serializers.CharField(read_only=False, required=True)

    class Meta:
        model = ProviderAppInstance
        fields = ["app_id", "created_at", "app_token", "provider_name", "phone_number"]
        read_only_fields = ['created_at']
    
    def validate_app_id(self, value):
        # Only run this check on creation (POST request, self.instance is None)
        if self.instance is None:
            if not value:
                raise serializers.ValidationError("app ID is required for creation.")
            
            try:
                # Check if an Organisation with this ID already exists
                self.Meta.model.objects.get(pk=value)
                
                # If it exists, raise a validation error
                raise serializers.ValidationError(
                    "app ID already exists. Use a PUT request to update."
                )
            except ObjectDoesNotExist:
                # If it doesn't exist, the ID is unique and valid for creation
                pass
                
        return value
    
    def validate(self, data):
        # 💡 FIX: Prevent 'id' from being included in the update data 
        # to ensure Django doesn't try to change the PK or create a new object.
        if self.instance and 'app_id' in data:
            if data['app_id'] != self.instance.app_id:
                raise serializers.ValidationError({"app_id": "The app ID cannot be changed."})
            # Remove 'app_id' from validated_data so ORM only saves other fields (like 'name')
            data.pop('app_id') 
        if self.instance is None and not data.get('app_id'):
            raise serializers.ValidationError({"app_id": "This field is required."})
            
        return data

    def create(self, validated_data):
        logger.debug('Creating ProviderAppInstance with data')
        # 1. Retrieve org_id passed from the ViewSet context
        org_id = self.context.get('org_id')
        if not org_id:
            raise serializers.ValidationError("Organisation ID is missing from the request context.")
        
        app_token = validated_data.pop('app_token') # Remove app_token from validated_data to avoid ORM issues and returns app_token
        try:
            organisation_instance = Organisation.objects.get(pk=org_id)
            logger.debug(f"Organisation {org_id} found.")
        except Organisation.DoesNotExist:
            # Auto-create the Organisation with a unique default name
            default_name = f"DefaultOrg_{org_id}_{uuid.uuid4().hex[:6]}"
            logger.info(f"Organisation {org_id} not found. Auto-creating with name: {default_name}")
            
            organisation_instance = Organisation.objects.create(
                id=org_id,
                name=default_name
            )
            
        instance = ProviderAppInstance(organisation=organisation_instance, **validated_data)
        instance.set_app_token(app_token)
        instance.save()
        return instance

    def update(self, instance, validated_data):
        logger.debug('Updating ProviderAppInstance %s with data: %s', instance.app_id, validated_data)
        app_token = validated_data.pop('app_token', None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        if app_token:
            instance.set_app_token(app_token)
        instance.save()
        return instance
