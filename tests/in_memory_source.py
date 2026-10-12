from media_sources import (ByteRangeRequest, CatalogPage, InvalidByteRange, MediaItem,
                           MediaItemNotFound, OpenedResource, ResourceNotFound)


class InMemorySource:
    """Small contract-compatible source for transport and caller tests."""
    def __init__(self, pages=None, items=None, resources=None):
        self.pages = pages or {None: CatalogPage(())}
        self.items = items or {}
        self.resources = resources or {}

    async def browse(self, parent_id=None, cursor=None):
        return self.pages.get(parent_id, CatalogPage(()))

    async def get_item(self, media_id):
        try: return self.items[media_id]
        except KeyError as exc: raise MediaItemNotFound("item não encontrado") from exc

    async def open_resource(self, resource_id, byte_range: ByteRangeRequest | None = None):
        try: content, content_type = self.resources[resource_id]
        except KeyError as exc: raise ResourceNotFound("recurso não encontrado") from exc
        size = len(content); start, end = 0, size - 1
        if byte_range:
            if byte_range.suffix_length is not None: start = max(0, size - byte_range.suffix_length)
            else: start = byte_range.start or 0; end = byte_range.end if byte_range.end is not None else end
            if start >= size or end < start: raise InvalidByteRange("intervalo inválido")
            end = min(end, size - 1)
        async def chunks(): yield content[start:end + 1]
        return OpenedResource(chunks(), size, content_type, start, end)
