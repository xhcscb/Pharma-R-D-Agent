from pharma_data.connectors.base import FetchResult, SourceAdapter
from pharma_data.connectors.clinical import (
    CdeManifestAdapter,
    ChinaDrugTrialsManifestAdapter,
    ClinicalDocumentAdapter,
    ClinicalTrialsGovAdapter,
    OpenFdaDrugAdapter,
)
from pharma_data.connectors.earnings_calls import EarningsCallAdapter
from pharma_data.connectors.financial_reports import (
    FinancialReportAdapter,
    SecCompanyFactsAdapter,
    SecEdgarFilingsAdapter,
)
from pharma_data.connectors.news import FdaNewsAdapter, NewsAdapter
from pharma_data.connectors.research_reports import ResearchReportManifestAdapter

__all__ = [
    "CdeManifestAdapter",
    "ChinaDrugTrialsManifestAdapter",
    "ClinicalDocumentAdapter",
    "ClinicalTrialsGovAdapter",
    "EarningsCallAdapter",
    "FdaNewsAdapter",
    "FetchResult",
    "FinancialReportAdapter",
    "NewsAdapter",
    "OpenFdaDrugAdapter",
    "ResearchReportManifestAdapter",
    "SecCompanyFactsAdapter",
    "SecEdgarFilingsAdapter",
    "SourceAdapter",
]
