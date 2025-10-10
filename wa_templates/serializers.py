from rest_framework import serializers
from .models import WhatsAppTemplate
from . import template_schemas


class WhatsAppTemplateSerializer(serializers.ModelSerializer):
    class Meta:
        model = WhatsAppTemplate
        fields = ('id', 'org_id', 'name', 'template_type', 'content', 'media_url', 'provider_metadata', 'status', 'created_at', 'updated_at', 'payload')

    def validate(self, data):
        ttype = data.get('template_type') or getattr(self.instance, 'template_type', None)
        if ttype not in dict(WhatsAppTemplate.TEMPLATE_TYPES):
            raise serializers.ValidationError({'template_type': 'Invalid template type'})
        # Add type-specific validations
        if ttype == 'TEXT' and not data.get('content'):
            raise serializers.ValidationError({'content': 'Text templates require content'})

        # Validate payload JSON against schema rules for the selected type
        payload = data.get('payload')
        if payload is not None:
            try:
                template_schemas.validate_payload(ttype, payload)
            except template_schemas.PayloadValidationError as pve:
                # return the structured errors to frontend
                raise serializers.ValidationError({'payload': pve.errors})
            except Exception as e:
                # fallback to string message
                raise serializers.ValidationError({'payload': str(e)})

        return data
