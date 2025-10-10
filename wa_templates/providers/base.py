from abc import ABC, abstractmethod


class BaseProvider(ABC):
    @abstractmethod
    def submit_template(self, template):
        raise NotImplementedError()

    @abstractmethod
    def upload_media(self, template):
        raise NotImplementedError()
