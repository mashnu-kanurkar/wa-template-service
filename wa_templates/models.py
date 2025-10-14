from datetime import datetime
import hashlib
import json
from django.db import models
import logging

from django.forms import model_to_dict
try:
    # Django 3.1+
    from django.db.models import JSONField
except Exception:
    from django.contrib.postgres.fields import JSONField

from cryptography.fernet import Fernet
import base64
import os
import uuid

logger = logging.getLogger(__name__)


def generate_app_secret():
    """Generate a new random secret for encrypting app tokens."""
    logger.debug('Generating new encryption secret for ProviderAppInstance')
    return base64.urlsafe_b64encode(os.urandom(32)).decode()

class Organisation(models.Model):
    id = models.CharField(primary_key=True, max_length=100, editable=False, unique=True)
    name = models.CharField(max_length=255, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

class ProviderAppInstance(models.Model):
    app_id = models.CharField(primary_key=True, editable=False, max_length=100, unique=True)
    provider_name = models.CharField(max_length=100, default='gupshup')
    organisation = models.ForeignKey(
        Organisation, related_name="provider_apps", on_delete=models.CASCADE
    )
    encrypted_app_token = models.BinaryField()
    encryption_secret = models.BinaryField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)
    phone_number = models.CharField(max_length=20, blank=True, null=True)
    

    class Meta:
        unique_together = ("organisation", "app_id", "phone_number")

    def __str__(self):
        return f"{self.organisation.name} - {self.app_name} ({self.app_id})"

    # -----------------
    # Encryption helpers
    # -----------------
    def set_app_token(self, raw_app_token: str):
        """Encrypt and store the API key securely using app's own secret."""
        logger.debug('Encrypting app token for ProviderAppInstance %s', self.app_id)
        if not self.encryption_secret:
            logger.debug('No encryption secret found, generating new one')
            self.encryption_secret = Fernet.generate_key()
        f = Fernet(self.encryption_secret)
        self.encrypted_app_token = f.encrypt(raw_app_token.encode('utf-8'))

    def get_app_token(self) -> str:
        """Decrypt API key for runtime usage."""
        logger.debug('Decrypting app token for ProviderAppInstance %s', self.app_id)
        if not self.encryption_secret or not self.encrypted_app_token:
            logger.debug('No encryption secret or encrypted token found, cannot decrypt')
            return None
        
        secret_key = bytes(self.encryption_secret)
        encrypted_token_bytes = bytes(self.encrypted_app_token)
        logger.debug('Using existing encryption secret for ProviderAppInstance %s', self.app_id)
        f = Fernet(secret_key)
        return f.decrypt(encrypted_token_bytes).decode('utf-8')
    
    def set_phone_number(self, phone_number: str):
        """Set the phone number associated with this app instance."""
        logger.debug('Setting phone number for ProviderAppInstance %s', self.app_id)
        self.phone_number = phone_number

    def get_phone_number(self) -> str:
        """Get the phone number associated with this app instance."""
        logger.debug('Getting phone number for ProviderAppInstance %s', self.app_id)
        return self.phone_number



class WhatsAppTemplate(models.Model):
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('failed', 'Failed'),
        ('paused', 'Paused'),
        ('deleted', 'Deleted'),
        ('disabled', 'Disabled'),
        ('in_appeal', 'In_appeal')
        
    ]

    templateTypeS = [
        ('TEXT', 'Text'),
        ('IMAGE', 'Image'),
        ('VIDEO', 'Video'),
        ('DOCUMENT', 'Document'),
        ('CAROUSEL', 'Carousel'),
        ('CATALOG', 'Catalog'),
    ]
    CATEGORY_CHOICES = [
        ('MARKETING', 'Marketing'),
        ('TRANSACTIONAL', 'Transactional'),
        ('OTP', 'One-Time Password'),
        ('UTILITY', 'Utility'),
        ('AUTHENTICATION', 'AUTHENTICATION'),
        ('NULL', 'Null')
    ]


    LANGUAGE_CHOICES = [
        ('af', 'Afrikaans'),
        ('sq', 'Albanian'),
        ('ar', 'Arabic'),
        ('az', 'Azerbaijani'),
        ('bn', 'Bengali'),
        ('bg', 'Bulgarian'),
        ('ca', 'Catalan'),
        ('zh_CN', 'Chinese (CHN)'),
        ('zh_HK', 'Chinese (HKG)'),
        ('zh_TW', 'Chinese (TAI)'),
        ('hr', 'Croatian'),
        ('cs', 'Czech'),
        ('da', 'Danish'),
        ('nl', 'Dutch'),
        ('en', 'English'),
        ('en_GB', 'English (UK)'),
        ('en_US', 'English (US)'),
        ('et', 'Estonian'),
        ('fil', 'Filipino'),
        ('fi', 'Finnish'),
        ('fr', 'French'),
        ('ka', 'Georgian'),
        ('de', 'German'),
        ('el', 'Greek'),
        ('gu', 'Gujarati'),
        ('ha', 'Hausa'),
        ('he', 'Hebrew'),
        ('hi', 'Hindi'),
        ('hu', 'Hungarian'),
        ('id', 'Indonesian'),
        ('ga', 'Irish'),
        ('it', 'Italian'),
        ('ja', 'Japanese'),
        ('kn', 'Kannada'),
        ('kk', 'Kazakh'),
        ('rw_RW', 'Kinyarwanda'),
        ('ko', 'Korean'),
        ('ky_KG', 'Kyrgyz (Kyrgyzstan)'),
        ('lo', 'Lao'),
        ('lv', 'Latvian'),
        ('lt', 'Lithuanian'),
        ('mk', 'Macedonian'),
        ('ms', 'Malay'),
        ('ml', 'Malayalam'),
        ('mr', 'Marathi'),
        ('nb', 'Norwegian'),
        ('fa', 'Persian'),
        ('pl', 'Polish'),
        ('pt_BR', 'Portuguese (BR)'),
        ('pt_PT', 'Portuguese (POR)'),
        ('pa', 'Punjabi'),
        ('ro', 'Romanian'),
        ('ru', 'Russian'),
        ('sr', 'Serbian'),
        ('sk', 'Slovak'),
        ('sl', 'Slovenian'),
        ('es', 'Spanish'),
        ('es_AR', 'Spanish (ARG)'),
        ('es_ES', 'Spanish (SPA)'),
        ('es_MX', 'Spanish (MEX)'),
        ('sw', 'Swahili'),
        ('sv', 'Swedish'),
        ('ta', 'Tamil'),
        ('te', 'Telugu'),
        ('th', 'Thai'),
        ('tr', 'Turkish'),
        ('uk', 'Ukrainian'),
        ('ur', 'Urdu'),
        ('uz', 'Uzbek'),
        ('vi', 'Vietnamese'),
        ('zu', 'Zulu'),
    ]

    DELETE_CHOICES = [
        ("None", 'none'),
        ("Processing", 'processing'),
        ("Deleted", 'deleted'),
    ]

    # VALID_MIME_TYPES = (
    #             ('audio/aac', 'audio/aac'),
    #             ('audio/mp4', 'audio/mp4'),
    #             ('audio/mpeg', 'audio/mpeg'),
    #             ('audio/amr', 'audio/amr'),
    #             ('audio/ogg', 'audio/ogg'),
    #             ('audio/opus', 'audio/opus'),
                
    #             # Documents
    #             ('application/pdf', 'application/pdf'),
    #             ('text/plain', 'text/plain'),
    #             ('application/msword', 'application/msword'),
    #             ('application/vnd.ms-excel', 'application/vnd.ms-excel'),
    #             ('application/vnd.ms-powerpoint', 'application/vnd.ms-powerpoint'),
    #             ('application/vnd.openxmlformats-officedocument.wordprocessingml.document', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'),
    #             ('application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
    #             ('application/vnd.openxmlformats-officedocument.presentationml.presentation', 'application/vnd.openxmlformats-officedocument.presentationml.presentation'),

    #             # Images
    #             ('image/jpeg', 'image/jpeg'),
    #             ('image/png', 'image/png'),
    #             ('image/webp', 'image/webp'),
                
    #             # Videos
    #             ('video/mp4', 'video/mp4'),
    #             ('video/3gpp', 'video/3gpp'),
    #         )

    templateType = models.CharField(max_length=20, choices=templateTypeS)
    languageCode = models.CharField(max_length=10, choices=LANGUAGE_CHOICES, default='en')
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default='MARKETING')
    oldCategory = models.CharField(max_length=20, choices=CATEGORY_CHOICES, null=True)
    content = models.TextField(blank=True)
    media_url = models.URLField(blank=True, null=True)
    # file_type = models.CharField(
    #     max_length=90,
    #     choices=VALID_MIME_TYPES,
    #     blank=True, 
    #     null=True
    # )
    vertical = models.CharField(max_length=180, blank=True, null=True)
    footer = models.CharField(max_length=180, blank=True, null=True)
    allowTemplateCategoryChange = models.BooleanField(default=False)
    example = models.TextField(blank=True, null=True)
    exampleHeader = models.TextField(blank=True, null=True)
    header = models.CharField(max_length=180, blank=True, null=True)
    enableSample = models.BooleanField(default=False)
    provider_metadata = JSONField(default=dict, blank=True)
    exampleMedia = models.TextField(blank=True, null=True)
    # structured payload containing template-type-specific fields (buttons, cards, exampleMedia, etc.)
    payload = JSONField(default=dict, blank=True)
    # External tenant/org identifier from upstream identity provider (do not duplicate tenant DB)
    org_id = models.ForeignKey(
        Organisation, related_name="organisation", on_delete=models.CASCADE
    )
    provider_app_instance_app_id = models.ForeignKey(
        ProviderAppInstance, related_name="provider_app_instance", on_delete=models.CASCADE
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    provider_template_id = models.CharField(max_length=100, blank=True, null=True)
    containerMeta = JSONField(default=dict, blank=True)
    buttonSupported = models.CharField(max_length=180, blank=True, null=True)
    createdOn = models.BigIntegerField(null=True, blank=True)
    data = models.TextField(blank=True, null=True)
    elementName = models.CharField(max_length=200, blank=True, null=True)
    externalId = models.CharField(max_length=200, blank=True, null=True)
    internalCategory = models.CharField(max_length=200, blank=True, null=True)
    internalType = models.CharField(max_length=200, blank=True, null=True)
    languagePolicy = models.CharField(max_length=50, blank=True, null=True)
    meta = models.TextField(blank=True, null=True)
    namespace = models.CharField(max_length=100, blank=True, null=True)
    modifiedOn = models.BigIntegerField(null=True, blank=True)
    priority = models.IntegerField(default=0)
    quality = models.CharField(max_length=50, blank=True, null=True)
    retry = models.IntegerField(default=0)
    stage = models.CharField(max_length=100, blank=True, null=True)
    wabaId = models.CharField(max_length=100, blank=True, null=True)
    errorMessageMeta = models.JSONField(default=dict, blank=True)
    isDeleted = models.CharField(max_length=10, choices=DELETE_CHOICES, default='none')
    hash = models.CharField(max_length=64, blank=True, null=True)
    webhookMeta = models.JSONField(default=dict, blank=True)

    class Meta:
        unique_together = ("org_id", "elementName", "languageCode", "provider_app_instance_app_id")
        ordering = ['-created_at']


    def __str__(self):
        return f"{self.elementName} ({self.org_id})"
    
    def generate_hash(self):
        # Only include fields that matter for detecting changes
        template_dict = {
            "appId": str(self.provider_app_instance_app_id.app_id),
            "buttonSupported": self.buttonSupported,
            "category": self.category,
            "containerMeta": self.containerMeta,
            "createdOn": self.createdOn,
            "data": self.data,
            "elementName": self.elementName,
            "externalId": self.externalId,
            "id": self.provider_template_id,
            "internalCategory": self.internalCategory,
            "internalType": self.internalType,
            "languageCode": self.languageCode,
            "languagePolicy": self.languagePolicy,
            "meta": self.meta,
            "modifiedOn": self.modifiedOn,
            "namespace": self.namespace,
            "oldCategory": self.oldCategory,
            "priority": self.priority,
            "quality": self.quality,
            "retry": self.retry,
            "stage": self.stage,
            "status": self.status,
            "templateType": self.templateType,
            "wabaId": self.wabaId
        }
        sorted_json = json.dumps(template_dict, sort_keys=True)
        return hashlib.md5(sorted_json.encode('utf-8')).hexdigest()

    def save(self, *args, **kwargs):
        # Always update hash before saving
        self.hash = self.generate_hash()
        super().save(*args, **kwargs)
    
    @classmethod
    def get_templates_by_element_name(cls, name):
        """Returns a QuerySet of all templates matching the given elementName."""
        # cls refers to the WhatsAppTemplate class
        return cls.objects.filter(elementName=name)
    
    @classmethod
    def get_templates_by_status(cls, status):
        """Returns a QuerySet of all templates matching the given status."""
        return cls.objects.filter(status=status)
    
    @classmethod
    def get_provider_template_id(cls, provider_template_id):
        """Returns a QuerySet of all templates matching the given provider_template_id."""
        return cls.objects.filter(provider_template_id=provider_template_id)
    

    
    def mark_as_deleted(self):
        """Mark the template as deleted."""
        self.isDeleted = 'Deleted'
        self.save()
    
    def update_error_meta(self, key, value):
        """
        Updates an existing JSONField by reading the current value, 
        modifying the dictionary, and saving the instance.
        """
        
        # 1. Read: Get the current dictionary
        meta = self.errorMessageMeta or {}
        
        # 2. Modify: Update the dictionary in memory
        error = {}
        error['payload'] = value
        error['ts'] = str(datetime.now().timestamp())
        meta[key] = error
        
        
        # 3. Write: Assign the modified dictionary back to the field
        self.errorMessageMeta = meta
        
        # 4. Save: Persist the change to the database
        self.save()
    
    def _update_and_log_webhook_event(self, event_type: str, main_field_value:str, event_payload: dict):
        """
        Helper to perform two operations atomically:
        1. Update the main model fields (status, category, quality).
        2. Replace the event details in webhookMeta[event_type] with the latest data.
        """
        if event_type == 'status-update':
            self.status = main_field_value
        elif event_type == "category-update":
            self.category = main_field_value
        elif event_type == 'quality-update':
            self.quality = main_field_value
        
        # Add timestamp and source payload
        event_payload['ts'] = str(datetime.now().timestamp())
        # event_data['raw_payload'] = event_payload # Optional: store raw payload for debugging
        
        # 3. Replace the entry in webhookMeta
        meta = self.webhookMeta or {}
        # This replaces the entire dictionary associated with event_type
        meta[event_type] = event_payload 
        self.webhookMeta = meta
        
        # 4. Save the instance to persist changes
        self.save()
    
    

    
    
    
