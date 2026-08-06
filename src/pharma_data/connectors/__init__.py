from pharma_data.connectors.base import FetchResult, SourceAdapter
from pharma_data.connectors.clinical import (
    CdeManifestAdapter,
    ChinaDrugTrialsManifestAdapter,
    ClinicalDocumentAdapter,
    ClinicalTrialsGovAdapter,
)
from pharma_data.connectors.earnings_calls import EarningsCallAdapter
from pharma_data.connectors.financial_reports import FinancialReportAdapter
from pharma_data.connectors.news import NewsAdapter
from pharma_data.connectors.research_reports import ResearchReportManifestAdapter

__all__ = [
    "CdeManifestAdapter",
    "ChinaDrugTrialsManifestAdapter",
    "ClinicalDocumentAdapter",
    "ClinicalTrialsGovAdapter",
    "EarningsCallAdapter",
    "FetchResult",
    "FinancialReportAdapter",
    "NewsAdapter",
    "ResearchReportManifestAdapter",
    "SourceAdapter",
]
