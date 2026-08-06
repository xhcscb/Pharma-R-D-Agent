# Controlled source catalog

| Family | Adapter | Authority preference | Supported inputs | Default policy |
|---|---|---|---|---|
| Sell-side research | ResearchReportManifestAdapter | Licensed institution or explicitly authorized file | PDF | authorized_restricted / team_internal |
| Clinical | ClinicalTrialsGovAdapter | ClinicalTrials.gov API v2 | full JSON | public |
| China clinical | ChinaDrugTrialsManifestAdapter | Official registry URL or reviewed manifest | HTML, JSON | public |
| Regulatory | CdeManifestAdapter | CDE/NMPA official publication | PDF, HTML, JSON | public |
| Financial | FinancialReportAdapter | Exchange, CNInfo, HKEX, or issuer IR | XBRL/XML, XLSX, PDF | public |
| News | NewsAdapter | Regulator, exchange, or issuer IR | RSS, HTML, JSON | public |
| Calls | EarningsCallAdapter | Issuer transcript, IR record, authorized recording | TXT, HTML, PDF, MP3, WAV, MP4 | public unless restricted by manifest |

Every discovered record must include source ID, title, license status, and access class.
Records marked metadata_only, prohibited, or unknown are retained as source metadata,
set to QUARANTINED, and never fetched. A non-public license cannot declare public
access. The system never implements an unrestricted brokerage-site crawler.
