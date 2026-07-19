"""ChromaDB async wrapper for OmniCast knowledge base."""

from __future__ import annotations

import asyncio

import structlog

from omnicast.shared.errors import AgentError

logger = structlog.get_logger()


class KBClient:
    """Async ChromaDB client for storing/retrieving embeddings.

    Collections:
    - "scripts": past script texts + metadata
    - "patterns": engagement patterns with decay
    - "lessons": agent lessons (per agent_name)
    """

    def __init__(self, persist_directory: str = "./chromadb_data") -> None:
        """Initialize ChromaDB client. Lazy — creates on first use."""
        self._persist_directory = persist_directory
        self._client = None

    def _get_client(self):
        """Lazy ChromaDB client creation."""
        if self._client is None:
            import chromadb
            self._client = chromadb.PersistentClient(path=self._persist_directory)
        return self._client

    async def add_document(
        self,
        collection: str,
        doc_id: str,
        text: str,
        metadata: dict | None = None,
    ) -> None:
        """Add or update a document in a collection."""
        try:
            client = self._get_client()
            coll = client.get_or_create_collection(collection)
            await asyncio.to_thread(
                coll.upsert,
                documents=[text],
                ids=[doc_id],
                metadatas=[metadata] if metadata else None,
            )
            logger.info("Document added to KB", collection=collection, doc_id=doc_id)
        except Exception as exc:
            raise AgentError(f"Failed to add document to KB: {exc}") from exc

    async def query(
        self,
        collection: str,
        query_text: str,
        n_results: int = 5,
        where: dict | None = None,
    ) -> list[dict]:
        """Query similar documents. Returns list of {id, text, metadata, distance}."""
        try:
            client = self._get_client()
            coll = client.get_or_create_collection(collection)
            results = await asyncio.to_thread(
                coll.query,
                query_texts=[query_text],
                n_results=n_results,
                where=where,
            )

            if not results["ids"][0]:
                return []

            output = []
            for i in range(len(results["ids"][0])):
                output.append({
                    "id": results["ids"][0][i],
                    "text": results["documents"][0][i],
                    "metadata": results["metadatas"][0][i],
                    "distance": results["distances"][0][i],
                })
            return output
        except Exception as exc:
            raise AgentError(f"Failed to query KB: {exc}") from exc

    async def delete_document(self, collection: str, doc_id: str) -> None:
        """Delete a document by ID."""
        try:
            client = self._get_client()
            coll = client.get_or_create_collection(collection)
            await asyncio.to_thread(coll.delete, ids=[doc_id])
            logger.info("Document deleted from KB", collection=collection, doc_id=doc_id)
        except Exception as exc:
            raise AgentError(f"Failed to delete document from KB: {exc}") from exc

    async def count(self, collection: str) -> int:
        """Return document count in collection."""
        try:
            client = self._get_client()
            coll = client.get_or_create_collection(collection)
            return await asyncio.to_thread(coll.count)
        except Exception as exc:
            raise AgentError(f"Failed to count documents in KB: {exc}") from exc
