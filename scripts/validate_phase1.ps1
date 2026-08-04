[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$errors = [System.Collections.Generic.List[string]]::new()
$warnings = [System.Collections.Generic.List[string]]::new()

function Add-ValidationError {
    param([string]$Message)
    $script:errors.Add($Message)
}

function Assert-RequiredFile {
    param([string]$RelativePath)
    $fullPath = Join-Path $repoRoot $RelativePath
    if (-not (Test-Path -LiteralPath $fullPath -PathType Leaf)) {
        Add-ValidationError "Missing required file: $RelativePath"
    }
}

function Assert-CsvHeader {
    param(
        [string]$RelativePath,
        [string[]]$ExpectedColumns
    )

    $fullPath = Join-Path $repoRoot $RelativePath
    if (-not (Test-Path -LiteralPath $fullPath -PathType Leaf)) {
        return
    }

    $firstLine = Get-Content -LiteralPath $fullPath -TotalCount 1
    $actualColumns = @(($firstLine -split ',') | ForEach-Object { $_.Trim('"') })
    if ($actualColumns.Count -ne $ExpectedColumns.Count) {
        Add-ValidationError "$RelativePath header count is $($actualColumns.Count); expected $($ExpectedColumns.Count)."
        return
    }

    for ($index = 0; $index -lt $ExpectedColumns.Count; $index++) {
        if ($actualColumns[$index] -ne $ExpectedColumns[$index]) {
            Add-ValidationError "$RelativePath column $($index + 1) is '$($actualColumns[$index])'; expected '$($ExpectedColumns[$index])'."
        }
    }
}

$requiredFiles = @(
    'README.md',
    'CONTRIBUTING.md',
    'docs/research/phase1_literature_research_plan.md',
    'research/protocol.md',
    'research/search/query_catalog.md',
    'research/search/search_log.csv',
    'research/search/seed_set.csv',
    'research/screening/screening_decisions.csv',
    'research/screening/quality_appraisal.csv',
    'research/screening/prisma_flow.csv',
    'research/evidence/literature_matrix.csv',
    'research/evidence/metric_candidates.csv',
    'research/evidence/cards/_template.md',
    'research/references/references.bib',
    'research/synthesis/thematic_synthesis.md',
    'research/synthesis/research_gaps_and_hypotheses.md',
    'research/decisions/decision_register.md',
    'research/phase2/phase2_data_requirements.md'
)

foreach ($relativePath in $requiredFiles) {
    Assert-RequiredFile $relativePath
}

$csvShapeValidator = Join-Path $repoRoot 'scripts/validate_csv_shape.py'
$pythonCommand = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonCommand) {
    Add-ValidationError 'Python is required for RFC 4180 CSV shape validation.'
} else {
    & $pythonCommand.Source $csvShapeValidator
    if ($LASTEXITCODE -ne 0) {
        Add-ValidationError 'CSV shape validation failed.'
    }
}

Assert-CsvHeader 'research/search/search_log.csv' @(
    'search_id','topic_cluster','database','query_version','actual_query','date_run',
    'date_from','date_to','language','result_count','export_file','export_sha256',
    'operator','status','notes'
)

Assert-CsvHeader 'research/search/seed_set.csv' @(
    'literature_id','title','year','topic_cluster','url','is_seed','is_anchor',
    'expected_database','search_hit_source','recall_status','primary_reviewer','secondary_reviewer'
)

Assert-CsvHeader 'research/screening/screening_decisions.csv' @(
    'decision_id','literature_id','screening_stage','reviewer','decision','exclusion_code',
    'decision_note','decision_date','is_double_screen','conflict_status','adjudicator','final_decision'
)

Assert-CsvHeader 'research/evidence/literature_matrix.csv' @(
    'literature_id','citekey','title','authors','year','venue','url_or_doi','language',
    'topic_cluster','research_question','task_definition','dataset_name','data_source',
    'sample_size','license','input_modality','method','baselines','evaluation_metrics',
    'human_evaluation','statistical_test','main_results','ablation','error_types',
    'limitations','code_url','data_url','quality_score','evidence_level','project_component',
    'design_implication','reviewer','review_status'
)

$seedPath = Join-Path $repoRoot 'research/search/seed_set.csv'
$matrixPath = Join-Path $repoRoot 'research/evidence/literature_matrix.csv'

if (Test-Path -LiteralPath $seedPath) {
    $seedRows = @(Import-Csv -LiteralPath $seedPath)
    $seedPapers = @($seedRows | Where-Object { $_.is_seed -eq 'true' })
    $anchorPapers = @($seedRows | Where-Object { $_.is_anchor -eq 'true' })

    if ($seedPapers.Count -lt 15) {
        Add-ValidationError "Seed set has $($seedPapers.Count) papers; at least 15 are required."
    }
    if ($anchorPapers.Count -ne 15) {
        Add-ValidationError "Anchor set has $($anchorPapers.Count) papers; exactly 15 are required."
    }

    $badIds = @($seedRows | Where-Object { $_.literature_id -notmatch '^LIT-\d{4}-\d{3}$' })
    if ($badIds.Count -gt 0) {
        Add-ValidationError "Seed set contains invalid literature IDs: $($badIds.literature_id -join ', ')"
    }

    $duplicateSeedIds = @($seedRows | Group-Object literature_id | Where-Object Count -gt 1)
    if ($duplicateSeedIds.Count -gt 0) {
        Add-ValidationError "Duplicate seed literature IDs: $($duplicateSeedIds.Name -join ', ')"
    }

    $duplicateSeedTitles = @($seedRows | Group-Object title | Where-Object Count -gt 1)
    if ($duplicateSeedTitles.Count -gt 0) {
        Add-ValidationError "Duplicate seed titles: $($duplicateSeedTitles.Name -join ' | ')"
    }
}

if (Test-Path -LiteralPath $matrixPath) {
    $matrixRows = @(Import-Csv -LiteralPath $matrixPath)
    $duplicateMatrixIds = @($matrixRows | Group-Object literature_id | Where-Object Count -gt 1)
    if ($duplicateMatrixIds.Count -gt 0) {
        Add-ValidationError "Duplicate matrix literature IDs: $($duplicateMatrixIds.Name -join ', ')"
    }

    $allowedClusters = @('A','B','C','D','E','F','G')
    $allowedComponents = @(
        'Data Layer','PDF Parser','Metric Ontology','Claim Graph','Evidence Gate',
        'Compare Agent','Summarize Agent','Agent Orchestration','Evaluation','Dataset Paper'
    )

    foreach ($row in $matrixRows) {
        foreach ($cluster in @($row.topic_cluster -split ';')) {
            if ($cluster -and $cluster -notin $allowedClusters) {
                Add-ValidationError "$($row.literature_id) has invalid topic cluster '$cluster'."
            }
        }
        foreach ($component in @($row.project_component -split ';')) {
            if ($component -and $component -notin $allowedComponents) {
                Add-ValidationError "$($row.literature_id) has invalid project component '$component'."
            }
        }
    }

    if (Test-Path -LiteralPath $seedPath) {
        $seedRows = @(Import-Csv -LiteralPath $seedPath)
        $matrixIds = @($matrixRows.literature_id)
        $missingSeedIds = @($seedRows | Where-Object { $_.literature_id -notin $matrixIds })
        if ($missingSeedIds.Count -gt 0) {
            Add-ValidationError "Seed papers missing from evidence matrix: $($missingSeedIds.literature_id -join ', ')"
        }
    }

    $prematureClaims = @($matrixRows | Where-Object {
        $_.review_status -eq 'full_text_verified' -and [string]::IsNullOrWhiteSpace($_.quality_score)
    })
    if ($prematureClaims.Count -gt 0) {
        Add-ValidationError "Rows marked full_text_verified without quality score: $($prematureClaims.literature_id -join ', ')"
    }
}

$trackedPdf = @(& git -C $repoRoot ls-files '*.pdf' 2>$null)
if ($trackedPdf.Count -gt 0) {
    Add-ValidationError "PDF files are tracked by Git: $($trackedPdf -join ', ')"
}

$currentBranch = (& git -C $repoRoot branch --show-current 2>$null)
if ($currentBranch -ne 'research/phase1-literature') {
    $warnings.Add("Current branch is '$currentBranch'; expected 'research/phase1-literature' during phase 1.")
}

Write-Host "Phase 1 validation summary"
Write-Host "  errors:   $($errors.Count)"
Write-Host "  warnings: $($warnings.Count)"

foreach ($warning in $warnings) {
    Write-Warning $warning
}

if ($errors.Count -gt 0) {
    foreach ($validationError in $errors) {
        Write-Error $validationError
    }
    exit 1
}

Write-Host 'Validation passed.'
