"""Code-controlled registry of permitted automated knowledge connectors.

Adapters use documented public APIs only. A source is not enabled merely because
its domain is reputable; its access method and reuse terms must also be suitable.
"""
from dataclasses import dataclass
from typing import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ai.knowledge_sync import sync_medlineplus, sync_pubmed
from app.modules.ai.source_policy import (
    PUBMED_ACQUISITION_ENABLED, PUBMED_USER_FACING_ENABLED,
)


@dataclass(frozen=True)
class SourceAdapter:
    key: str
    display_name: str
    source_url: str
    publisher: str
    integration_method: str
    policy_url: str
    acquisition_enabled: bool
    user_facing_enabled: bool
    synchronize: Callable[[AsyncSession], Awaitable[dict[str, int]]]


SOURCE_ADAPTERS = (
    SourceAdapter(
        key="medlineplus", display_name="MedlinePlus Web Service",
        source_url="https://medlineplus.gov/about/developers/webservices/",
        publisher="U.S. National Library of Medicine",
        integration_method="Official search Web Service (XML)",
        policy_url="https://medlineplus.gov/about/developers/webservices/",
        acquisition_enabled=True,
        user_facing_enabled=True,
        synchronize=sync_medlineplus,
    ),
    SourceAdapter(
        key="pubmed", display_name="PubMed via NCBI E-utilities",
        source_url="https://pubmed.ncbi.nlm.nih.gov/",
        publisher="U.S. National Library of Medicine, National Center for Biotechnology Information",
        integration_method="Official NCBI E-utilities (PubMed metadata and abstracts)",
        policy_url="https://www.ncbi.nlm.nih.gov/home/about/policies/",
        acquisition_enabled=PUBMED_ACQUISITION_ENABLED,
        user_facing_enabled=PUBMED_USER_FACING_ENABLED,
        synchronize=sync_pubmed,
    ),
)
