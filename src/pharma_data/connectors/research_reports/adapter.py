from pharma_data.connectors.base import ManifestSourceAdapter
from pharma_data.contracts import DocumentType, LicenseStatus


class ResearchReportManifestAdapter(ManifestSourceAdapter):
    source_name = "authorized_research_reports"
    adapter_name = "ResearchReportManifestAdapter"
    authority_tier = "B1"
    document_type = DocumentType.RESEARCH_REPORT
    default_license_status = LicenseStatus.AUTHORIZED_RESTRICTED
    allowed_media_types = {"application/pdf"}
