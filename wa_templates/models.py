from django.db import models
import logging
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
        ('pending', 'Pending Approval'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]

    TEMPLATE_TYPES = [
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

    template_type = models.CharField(max_length=20, choices=TEMPLATE_TYPES)
    languageCode = models.CharField(max_length=10, choices=LANGUAGE_CHOICES, default='en')
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default='MARKETING')
    content = models.TextField(blank=True)
    media_url = models.URLField(blank=True, null=True)
    file_type = models.CharField(max_length=20, blank=True, null=True)  # e.g., 'image/jpeg', 'video/mp4'
    vertical = models.CharField(max_length=180, blank=True, null=True)
    footer = models.CharField(max_length=180, blank=True, null=True)
    allowTemplateCategoryChange = models.BooleanField(default=False)
    example = models.TextField(blank=True, null=True)
    exampleHeader = models.TextField(blank=True, null=True)
    header = models.CharField(max_length=180, blank=True, null=True)
    enableSample = models.BooleanField(default=False)
    provider_metadata = JSONField(default=dict, blank=True)
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
    createdOn = models.DateTimeField(auto_now_add=False,blank=True, null=True)
    data = models.TextField(blank=True, null=True)
    elementName = models.CharField(max_length=200, blank=True, null=True)
    languagePolicy = models.CharField(max_length=50, blank=True, null=True)
    meta = models.TextField(blank=True, null=True)
    namespace = models.CharField(max_length=100, blank=True, null=True)
    modifiedOn = models.DateTimeField(auto_now_add=False, blank=True, null=True)
    priority = models.IntegerField(default=0)
    quality = models.CharField(max_length=50, blank=True, null=True)
    retry = models.IntegerField(default=0)
    stage = models.CharField(max_length=100, blank=True, null=True)
    wabaId = models.CharField(max_length=100, blank=True, null=True)
    errorMessage = models.TextField(blank=True, null=True)
    isDeleted = models.CharField(max_length=10, choices=DELETE_CHOICES, default='none')

    class Meta:
        unique_together = ("org_id", "elementName", "languageCode", "provider_app_instance_app_id")
        ordering = ['-created_at']


    def __str__(self):
        return f"{self.elementName} ({self.org_id})"
    
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
    
    def json(self):
        """Return a JSON-serializable representation of the template."""
        return {
            "id": self.id,
            "template_type": self.template_type,
            "languageCode": self.languageCode,
            "category": self.category,
            "content": self.content,
            "media_url": self.media_url,
            "file_type": self.file_type,
            "vertical": self.vertical,
            "footer": self.footer,
            "allowTemplateCategoryChange": self.allowTemplateCategoryChange,
            "example": self.example,
            "exampleHeader": self.exampleHeader,
            "header": self.header,
            "enableSample": self.enableSample,
            "provider_metadata": self.provider_metadata,
            "payload": self.payload,
            "org_id": self.org_id.id if self.org_id else None,
            "provider_app_instance_app_id": self.provider_app_instance_app_id.app_id if self.provider_app_instance_app_id else None,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "provider_template_id": self.provider_template_id,
            "containerMeta": self.containerMeta,
            "createdOn": self.createdOn.isoformat() if self.createdOn else None,
            "data": self.data,
            "elementName": self.elementName,
            "languagePolicy": self.languagePolicy,
            "meta": self.meta,
            "namespace": self.namespace,
            "modifiedOn": self.modifiedOn.isoformat() if self.modifiedOn else None,
            "priority": self.priority,
            "quality": self.quality,
            "retry": self.retry,
            "stage": self.stage,
            "wabaId": self.wabaId,
            "errorMessage": self.errorMessage,
            "isDeleted": self.isDeleted,
        }
    
    def mark_as_deleted(self):
        """Mark the template as deleted."""
        self.isDeleted = 'Deleted'
        self.save()
    

    
    
    
