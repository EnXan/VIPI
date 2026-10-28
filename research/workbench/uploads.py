"""An uploaded original image, exposed through the existing batch input contract."""

from pathlib import Path


class UploadCatalog:
    def __init__(self, path, name):
        self.source = Path(path)
        self.items = {"upload": {"id": "upload", "image": name, "category": "uploaded"}}

    def get(self, identifier):
        return self.items[identifier]

    def path(self, identifier):
        self.get(identifier)
        return self.source

    def reference(self, identifier):
        self.get(identifier)
        return None
