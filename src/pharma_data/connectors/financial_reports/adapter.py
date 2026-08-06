from pharma_data.connectors.base import ManifestSourceAdapter
from pharma_data.contracts import DocumentType, LicenseStatus


class FinancialReportAdapter(ManifestSourceAdapter):
    source_name = "official_financial_reports"
    adapter_name = "FinancialReportAdapter"
    authority_tier = "A1"
    document_type = DocumentType.FINANCIAL_REPORT
    default_license_status = LicenseStatus.PUBLIC
    allowed_media_types = {
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/xml",
        "text/xml",
    }
