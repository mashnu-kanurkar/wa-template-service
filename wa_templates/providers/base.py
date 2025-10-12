from abc import ABC, abstractmethod


class BaseProvider(ABC):
    @abstractmethod
    def submit_template(self, template):
        raise NotImplementedError()

    @abstractmethod
    def upload_media(self, template):
        raise NotImplementedError()
    
    @abstractmethod
    def get_templates(self):
        raise NotImplementedError()
    
    @abstractmethod
    def update_template(self, template):
        raise NotImplementedError()
    
    @abstractmethod
    def delete_template(self, template):
        raise NotImplementedError()
