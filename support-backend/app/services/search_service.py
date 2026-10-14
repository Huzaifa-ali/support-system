"""Full-text search service."""

import re
from typing import Any, Optional
from uuid import UUID, uuid4

from app.core.exceptions import NotFoundError
from app.core.logging import get_logger
from app.db.repositories.ticket_repo import TicketRepo
from app.db.repositories.user_repo import UserRepo

logger = get_logger(__name__)

# Length of the description snippet returned in search highlights.
_SNIPPET_LEN = 160


class SearchService:
    """Business logic for full-text search and saved filters.

    Search runs against PostgreSQL's ``tsvector`` (``tickets.search_vector``)
    via the repository. Because PostgREST does not return ``ts_rank`` or
    ``ts_headline`` output directly, the service computes a lightweight
    client-side relevance score and builds ``<mark>``-annotated highlights so
    the frontend can render matched terms without a second round-trip.

    Saved filters are stored per user in the ``users.saved_filters`` JSONB
    column as a list of ``{id, name, filters}`` objects.
    """

    def __init__(self) -> None:
        self.repo = TicketRepo()
        self.user_repo = UserRepo()

    async def search(
        self,
        query: str,
        project_id: UUID,
        filters: dict[str, Any],
        page: int = 1,
        page_size: int = 20,
        viewer: Optional[dict] = None,
    ) -> tuple[list[dict], int]:
        """Full-text search across tickets in a project.

        Args:
            query: Raw user search string (already validated, min 2 chars).
            project_id: Project to search within (scopes all results).
            filters: Optional exact-match filters (status, type, priority).
            page: Page number (1-indexed).
            page_size: Items per page (capped at 100).
            viewer: The acting user record. Admins see all tickets; everyone
                else sees only approved tickets plus their own pending ones.

        Returns:
            Tuple of (search results, total count). Each result includes a
            ``relevance_score`` and a ``highlight`` block with marked terms.
        """
        page_size = min(max(page_size, 1), 100)
        page = max(page, 1)

        # Turn the free-text query into a PostgreSQL websearch-style string so
        # multi-word queries match on all terms rather than the literal phrase.
        ts_query = self._build_ts_query(query)

        # Scope approval visibility: admins see everything, others are limited
        # to approved tickets or their own pending ones.
        is_admin = viewer.get("role") == "admin" if viewer else False
        viewer_id = None if (viewer is None or is_admin) else viewer.get("id")

        results, total = await self.repo.search_fulltext(
            query=ts_query,
            project_id=project_id,
            page=page,
            page_size=page_size,
            status=filters.get("status"),
            ticket_type=filters.get("type"),
            priority=filters.get("priority"),
            viewer_id=UUID(str(viewer_id)) if viewer_id else None,
            include_all_approval=is_admin,
        )

        terms = self._extract_terms(query)
        enriched = [self._enrich_result(ticket, terms) for ticket in results]

        logger.info(
            "search_executed",
            extra={
                "resource": {"project_id": str(project_id)},
                "context": {"results": total, "page": page},
            },
        )
        return enriched, total

    async def get_saved_filters(self, user_id: UUID) -> list[dict]:
        """Get saved filters for a user.

        Args:
            user_id: UUID of the user whose filters to load.

        Returns:
            List of saved filter dicts ({id, name, filters}); empty if none.
        """
        user = await self.user_repo.get_by_id(user_id)
        if not user:
            return []
        return self._normalize_filters(user.get("saved_filters"))

    async def save_filter(
        self, user_id: UUID, name: str, filters: dict[str, Any]
    ) -> dict:
        """Save a filter combination for a user.

        Appends the new filter to the user's ``saved_filters`` list, assigning
        it a generated id. If a filter with the same name already exists it is
        replaced so names stay unique and re-saving updates in place.

        Args:
            user_id: UUID of the user saving the filter.
            name: Human-friendly filter name.
            filters: The filter combination to persist.

        Returns:
            The saved filter object ({id, name, filters}).

        Raises:
            NotFoundError: If the user does not exist.
        """
        user = await self.user_repo.get_by_id(user_id)
        if not user:
            raise NotFoundError(message="User not found")

        existing = self._normalize_filters(user.get("saved_filters"))
        # Replace any filter with the same (case-insensitive) name.
        existing = [f for f in existing if f.get("name", "").lower() != name.lower()]

        new_filter = {"id": str(uuid4()), "name": name, "filters": filters}
        existing.append(new_filter)

        await self.user_repo.update_saved_filters(str(user_id), existing)
        logger.info(
            "saved_filter_created",
            extra={"resource": {"user_id": str(user_id), "filter_id": new_filter["id"]}},
        )
        return new_filter

    async def delete_filter(self, filter_id: UUID, user_id: UUID) -> None:
        """Delete a saved filter.

        Args:
            filter_id: UUID of the saved filter to remove.
            user_id: UUID of the owning user.

        Raises:
            NotFoundError: If the user or the filter does not exist.
        """
        user = await self.user_repo.get_by_id(user_id)
        if not user:
            raise NotFoundError(message="User not found")

        existing = self._normalize_filters(user.get("saved_filters"))
        remaining = [f for f in existing if str(f.get("id")) != str(filter_id)]

        if len(remaining) == len(existing):
            raise NotFoundError(message="Saved filter not found")

        await self.user_repo.update_saved_filters(str(user_id), remaining)
        logger.info(
            "saved_filter_deleted",
            extra={"resource": {"user_id": str(user_id), "filter_id": str(filter_id)}},
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_filters(raw: Any) -> list[dict]:
        """Coerce a stored saved_filters value into a list of dicts."""
        if isinstance(raw, list):
            return [f for f in raw if isinstance(f, dict)]
        return []

    @staticmethod
    def _extract_terms(query: str) -> list[str]:
        """Extract distinct word tokens (len >= 2) from a raw query."""
        tokens = re.findall(r"\w+", query.lower())
        seen: list[str] = []
        for token in tokens:
            if len(token) >= 2 and token not in seen:
                seen.append(token)
        return seen

    @staticmethod
    def _build_ts_query(query: str) -> str:
        """Build a websearch-style tsquery string from a raw query.

        Joins word tokens so a multi-word query matches rows containing all
        terms. Falls back to the trimmed input when no word tokens are found.
        """
        tokens = re.findall(r"\w+", query.lower())
        if not tokens:
            return query.strip()
        return " ".join(tokens)

    def _enrich_result(self, ticket: dict, terms: list[str]) -> dict:
        """Attach a relevance score and highlight block to a search result."""
        title = ticket.get("title") or ""
        description = ticket.get("description") or ""

        ticket["relevance_score"] = self._relevance(title, description, terms)
        ticket["highlight"] = {
            "title": self._mark(title, terms),
            "description": self._mark(self._snippet(description, terms), terms),
        }
        return ticket

    @staticmethod
    def _relevance(title: str, description: str, terms: list[str]) -> float:
        """Compute a 0..1 relevance score weighting title matches higher.

        This is an approximation of ts_rank for display/sorting hints only;
        the authoritative match set comes from the database tsvector query.
        """
        if not terms:
            return 0.0
        title_l = title.lower()
        desc_l = description.lower()
        score = 0.0
        for term in terms:
            if term in title_l:
                score += 1.0  # Title matches are weighted highest (weight 'A').
            elif term in desc_l:
                score += 0.4  # Description matches weighted lower (weight 'B').
        # Normalize by the maximum achievable score (all terms in the title).
        return round(min(score / len(terms), 1.0), 2)

    @classmethod
    def _snippet(cls, text: str, terms: list[str]) -> str:
        """Return a snippet of text centered on the first matched term."""
        if not text:
            return ""
        if len(text) <= _SNIPPET_LEN:
            return text

        lowered = text.lower()
        idx = -1
        for term in terms:
            found = lowered.find(term)
            if found != -1 and (idx == -1 or found < idx):
                idx = found

        if idx == -1:
            return text[:_SNIPPET_LEN].rstrip() + "..."

        # Center the window on the match, clamped to the text bounds.
        half = _SNIPPET_LEN // 2
        start = max(0, idx - half)
        end = min(len(text), start + _SNIPPET_LEN)
        snippet = text[start:end].strip()
        prefix = "..." if start > 0 else ""
        suffix = "..." if end < len(text) else ""
        return f"{prefix}{snippet}{suffix}"

    @staticmethod
    def _mark(text: str, terms: list[str]) -> str:
        """Wrap matched terms in <mark> tags (case-insensitive).

        Escapes any existing markup characters first so the returned string is
        safe to render, then inserts <mark> around each matched term.
        """
        if not text or not terms:
            return text
        escaped = (
            text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        )
        # Match the longest terms first to avoid partial nested replacements.
        pattern = "|".join(
            re.escape(term) for term in sorted(terms, key=len, reverse=True)
        )
        return re.sub(
            f"({pattern})",
            r"<mark>\1</mark>",
            escaped,
            flags=re.IGNORECASE,
        )
