"""
In-memory stand-in for a Firestore client.

The project has no Firestore emulator or mock, and tests must not use the network, so the
Firestore store is exercised against this fake. It implements only the calls
``FirestoreDocumentStore`` makes: collection().document().set()/get() and
collection().limit().stream(). It proves the store's logic, not real Firestore behaviour.
"""

import copy
from typing import Any, Dict, Iterator, Optional


class FakeSnapshot:
    def __init__(self, data: Optional[Dict[str, Any]]):
        self._data = data
        self.exists = data is not None

    def to_dict(self) -> Optional[Dict[str, Any]]:
        return copy.deepcopy(self._data)


class FakeDocument:
    def __init__(self, documents: Dict[str, Dict[str, Any]], doc_id: str, client: "FakeFirestoreClient"):
        self._documents = documents
        self._doc_id = doc_id
        self._client = client

    def set(self, data: Dict[str, Any]) -> None:
        self._client.check_available()
        self._documents[self._doc_id] = copy.deepcopy(data)

    def get(self) -> FakeSnapshot:
        self._client.check_available()
        return FakeSnapshot(self._documents.get(self._doc_id))


class FakeQuery:
    def __init__(self, documents: Dict[str, Dict[str, Any]], client: "FakeFirestoreClient", count: Optional[int] = None):
        self._documents = documents
        self._client = client
        self._count = count

    def limit(self, count: int) -> "FakeQuery":
        return FakeQuery(self._documents, self._client, count)

    def stream(self) -> Iterator[FakeSnapshot]:
        self._client.check_available()
        for index, doc_id in enumerate(sorted(self._documents)):
            if self._count is not None and index >= self._count:
                return
            yield FakeSnapshot(self._documents[doc_id])


class FakeCollection(FakeQuery):
    def document(self, doc_id: str) -> FakeDocument:
        return FakeDocument(self._documents, doc_id, self._client)


class FakeFirestoreClient:
    def __init__(self) -> None:
        self.data: Dict[str, Dict[str, Dict[str, Any]]] = {}
        self.available = True

    def check_available(self) -> None:
        if not self.available:
            raise ConnectionError("Firestore unavailable (simulated)")

    def collection(self, name: str) -> FakeCollection:
        return FakeCollection(self.data.setdefault(name, {}), self)
