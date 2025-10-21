import uuid
from django.core.files.storage import FileSystemStorage


class OverwriteStorage(FileSystemStorage):
    """
    Custom storage that overwrites existing files instead of renaming them.
    Prevents random suffixes like _MienTEt.
    """
    def get_available_name(self, name, max_length=None):
        if self.exists(name):
            self.delete(name)
        return name


def temp_credential_path(instance, filename):
    """
    Generates a consistent, short upload path for Google service credentials.
    Example: catalog_credentials/<app_id>/<random>_catalog-service.json
    """
    return f"catalog_credentials/{instance.provider_app_instance_app_id.app_id}/{uuid.uuid4().hex[:8]}_catalog-service.json"
