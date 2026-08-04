[CmdletBinding()]
param(
    [switch]$Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$outputPath = Join-Path $repoRoot 'research/evidence/literature_matrix.csv'

if ((Test-Path -LiteralPath $outputPath) -and -not $Force) {
    throw 'The evidence matrix already exists. Use -Force only when intentionally rebuilding the bootstrap data.'
}

function New-LiteratureRow {
    param(
        [string]$Id,
        [string]$Citekey,
        [string]$Title,
        [string]$Authors,
        [int]$Year,
        [string]$Venue,
        [string]$Url,
        [string]$Cluster,
        [string]$Rq,
        [string]$Task,
        [string]$Dataset = '',
        [string]$DataSource = '',
        [string]$SampleSize = '',
        [string]$InputModality = 'text',
        [string]$Method = '',
        [string]$Metrics = '',
        [string]$EvidenceLevel = 'pending',
        [string]$Component,
        [string]$Implication,
        [string]$CodeUrl = '',
        [string]$DataUrl = ''
    )

    [pscustomobject][ordered]@{
        literature_id = $Id
        citekey = $Citekey
        title = $Title
        authors = $Authors
        year = $Year
        venue = $Venue
        url_or_doi = $Url
        language = 'en'
        topic_cluster = $Cluster
        research_question = $Rq
        task_definition = $Task
        dataset_name = $Dataset
        data_source = $DataSource
        sample_size = $SampleSize
        license = ''
        input_modality = $InputModality
        method = $Method
        baselines = ''
        evaluation_metrics = $Metrics
        human_evaluation = ''
        statistical_test = ''
        main_results = ''
        ablation = ''
        error_types = ''
        limitations = ''
        code_url = $CodeUrl
        data_url = $DataUrl
        quality_score = ''
        evidence_level = $EvidenceLevel
        project_component = $Component
        design_implication = $Implication
        reviewer = ''
        review_status = 'metadata_verified'
    }
}

$rows = @(
    New-LiteratureRow -Id 'LIT-2021-001' -Citekey 'page2021prisma' -Title 'The PRISMA 2020 statement: an updated guideline for reporting systematic reviews' -Authors 'Matthew J. Page et al.' -Year 2021 -Venue 'BMJ' -Url 'https://doi.org/10.1136/bmj.n71' -Cluster 'A' -Rq 'RQ2;RQ8' -Task 'Systematic-review reporting guideline' -Method '27-item reporting guideline and flow diagrams' -EvidenceLevel 'foundational_standard' -Component 'Dataset Paper;Evaluation' -Implication '用于检索筛选流程和报告透明性；待全文复核'
    New-LiteratureRow -Id 'LIT-2021-002' -Citekey 'gebru2021datasheets' -Title 'Datasheets for Datasets' -Authors 'Timnit Gebru;Jamie Morgenstern;Briana Vecchione;Jennifer Wortman Vaughan;Hanna Wallach;Hal Daumé III;Kate Crawford' -Year 2021 -Venue 'Communications of the ACM' -Url 'https://arxiv.org/abs/1803.09010' -Cluster 'A' -Rq 'RQ2' -Task 'Dataset documentation framework' -Method 'Datasheet questions covering the dataset lifecycle' -EvidenceLevel 'foundational_standard' -Component 'Data Layer;Dataset Paper' -Implication '用于定义数据来源、采样、用途和维护披露；待全文复核'
    New-LiteratureRow -Id 'LIT-2022-001' -Citekey 'wohlin2022hybrid' -Title 'Successful Combination of Database Search and Snowballing for Identification of Primary Studies in Systematic Literature Studies' -Authors 'Claes Wohlin;Marcos Kalinowski;Katia Romero Felizardo;Emilia Mendes' -Year 2022 -Venue 'Information and Software Technology' -Url 'https://doi.org/10.1016/j.infsof.2022.106908' -Cluster 'A' -Rq 'RQ2;RQ8' -Task 'Hybrid database search and snowballing' -Method 'Hybrid systematic-search strategy' -Component 'Dataset Paper;Evaluation' -Implication '用于前向后向滚雪球与边界文献处理；待全文复核'
    New-LiteratureRow -Id 'LIT-2023-001' -Citekey 'islam2023financebench' -Title 'FinanceBench: A New Benchmark for Financial Question Answering' -Authors 'Pranab Islam;Anand Kannappan;Douwe Kiela;Rebecca Qian;Nino Scherrer;Bertie Vidgen' -Year 2023 -Venue 'arXiv' -Url 'https://arxiv.org/abs/2311.11944' -Cluster 'B' -Rq 'RQ1;RQ2' -Task 'Open-book financial question answering' -Dataset 'FinanceBench' -DataSource 'Public-company financial documents' -SampleSize '10231 questions' -Method 'Benchmark with answers and evidence strings' -Component 'Data Layer;Evidence Gate;Evaluation' -Implication '用于证据定位、拒答和金融问答最低能力评测；待全文复核'
    New-LiteratureRow -Id 'LIT-2021-003' -Citekey 'chen2021finqa' -Title 'FinQA: A Dataset of Numerical Reasoning over Financial Data' -Authors 'Zhiyu Chen et al.' -Year 2021 -Venue 'EMNLP' -Url 'https://doi.org/10.18653/v1/2021.emnlp-main.300' -Cluster 'B' -Rq 'RQ1;RQ2' -Task 'Numerical reasoning over financial reports' -Dataset 'FinQA' -DataSource 'Financial reports' -InputModality 'table;text' -Method 'Gold reasoning programs and QA' -Component 'Data Layer;Compare Agent;Evaluation' -Implication '用于数值推理、可解释计算链和程序正确性；待全文复核' -CodeUrl 'https://github.com/czyssrs/FinQA'
    New-LiteratureRow -Id 'LIT-2021-004' -Citekey 'zhu2021tatqa' -Title 'TAT-QA: A Question Answering Benchmark on a Hybrid of Tabular and Textual Content in Finance' -Authors 'Fengbin Zhu;Wenqiang Lei;Youcheng Huang;Chao Wang;Shuo Zhang;Jiancheng Lv;Fuli Feng;Tat-Seng Chua' -Year 2021 -Venue 'ACL-IJCNLP' -Url 'https://doi.org/10.18653/v1/2021.acl-long.254' -Cluster 'B' -Rq 'RQ1;RQ2;RQ6' -Task 'QA over hybrid financial tables and text' -Dataset 'TAT-QA' -DataSource 'Financial reports' -InputModality 'table;text' -Method 'Sequence tagging plus symbolic aggregation' -Component 'PDF Parser;Compare Agent;Evaluation' -Implication '用于表文混合抽取和聚合运算评测；待全文复核'
    New-LiteratureRow -Id 'LIT-2024-001' -Citekey 'xie2024finben' -Title 'FinBen: A Holistic Financial Benchmark for Large Language Models' -Authors 'Qianqian Xie et al.' -Year 2024 -Venue 'NeurIPS Datasets and Benchmarks' -Url 'https://doi.org/10.52202/079017-3033' -Cluster 'B;G' -Rq 'RQ1;RQ2;RQ7' -Task 'Holistic financial LLM evaluation' -Dataset 'FinBen' -DataSource '42 datasets across financial tasks' -SampleSize '42 datasets;24 tasks' -InputModality 'text;structured data' -Method 'Multi-task financial benchmark' -Component 'Evaluation;Agent Orchestration;Dataset Paper' -Implication '用于构建金融任务覆盖面和分项指标；待全文复核'
    New-LiteratureRow -Id 'LIT-2025-001' -Citekey 'long2025finlfqa' -Title 'FinLFQA: Evaluating Attributed Text Generation of LLMs in Financial Long-Form Question Answering' -Authors 'Yitao Long;Tiansheng Hu;Yilun Zhao;Arman Cohan;Chen Zhao' -Year 2025 -Venue 'Findings of EMNLP' -Url 'https://doi.org/10.18653/v1/2025.findings-emnlp.908' -Cluster 'B;D' -Rq 'RQ1;RQ4' -Task 'Attributed long-form financial QA' -Dataset 'FinLFQA' -DataSource 'Financial reports' -Method 'Long-form answer generation with evidence and reasoning attribution' -Component 'Claim Graph;Evidence Gate;Summarize Agent;Evaluation' -Implication '用于分离答案质量、证据、数值中间步骤与领域知识归因；待全文复核'
    New-LiteratureRow -Id 'LIT-2025-002' -Citekey 'lin2025mebench' -Title 'MEBench: Benchmarking Large Language Models for Cross-Document Multi-Entity Question Answering' -Authors 'Teng Lin;Yuyu Luo;Honglin Zhang;Jicheng Zhang;Chunlin Liu;Kaishun Wu;Nan Tang' -Year 2025 -Venue 'EMNLP' -Url 'https://doi.org/10.18653/v1/2025.emnlp-main.77' -Cluster 'C' -Rq 'RQ1;RQ3' -Task 'Cross-document multi-entity QA' -Dataset 'MEBench' -DataSource 'Multi-document benchmark' -SampleSize '4780 questions' -Method 'Comparative statistical and relational reasoning benchmark' -Metrics 'Accuracy;EA-F1' -Component 'Compare Agent;Evidence Gate;Evaluation' -Implication '用于实体级完整性、事实精度和归因有效性；待全文复核'
    New-LiteratureRow -Id 'LIT-2025-003' -Citekey 'nikishina2025compare' -Title 'How to Compare Things Properly? A Study of Argument Relevance in Comparative Question Answering' -Authors 'Irina Nikishina;Saba Anwar;Nikolay Dolgov;Maria Manina;Daria Ignatenko;Artem Shelmanov;Chris Biemann' -Year 2025 -Venue 'ACL' -Url 'https://doi.org/10.18653/v1/2025.acl-long.765' -Cluster 'C' -Rq 'RQ1;RQ3' -Task 'Comparative QA with argument provenance' -DataSource 'Manually curated comparative arguments' -Method 'Argument relevance annotations and ideal-comparison criteria' -Component 'Claim Graph;Compare Agent;Evidence Gate;Evaluation' -Implication '用于比较维度、论据相关性和来源追溯；待全文复核'
    New-LiteratureRow -Id 'LIT-2022-002' -Citekey 'fabbri2022qafacteval' -Title 'QAFactEval: Improved QA-Based Factual Consistency Evaluation for Summarization' -Authors 'Alexander Fabbri;Chien-Sheng Wu;Wenhao Liu;Caiming Xiong' -Year 2022 -Venue 'NAACL' -Url 'https://doi.org/10.18653/v1/2022.naacl-main.187' -Cluster 'D' -Rq 'RQ1;RQ4' -Task 'Factual consistency evaluation for summaries' -Method 'QA-based factuality metric' -Component 'Evidence Gate;Summarize Agent;Evaluation' -Implication '用于事实一致性自动评价，需与蕴含及人工评价结合；待全文复核'
    New-LiteratureRow -Id 'LIT-2023-002' -Citekey 'gao2023alce' -Title 'Enabling Large Language Models to Generate Text with Citations' -Authors 'Tianyu Gao;Howard Yen;Jiatong Yu;Danqi Chen' -Year 2023 -Venue 'EMNLP' -Url 'https://doi.org/10.18653/v1/2023.emnlp-main.398' -Cluster 'D' -Rq 'RQ1;RQ4' -Task 'Retrieval and long-form generation with citations' -Dataset 'ALCE' -DataSource 'Multiple QA datasets and retrieval corpora' -Method 'Automatic LLM citation evaluation' -Metrics 'Fluency;correctness;citation quality' -Component 'Claim Graph;Evidence Gate;Summarize Agent;Evaluation' -Implication '用于引用正确性与引用完整性指标；待全文复核'
    New-LiteratureRow -Id 'LIT-2026-001' -Citekey 'yuan2026confrag' -Title "Benchmarking LLM's Capability in Reasoning over Conflicting Web References" -Authors 'Yizhen Yuan;Rui Kong;Dongze Li;Yuanchun Li;Yunxin Liu' -Year 2026 -Venue 'ACL' -Url 'https://aclanthology.org/2026.acl-long.11/' -Cluster 'D' -Rq 'RQ1;RQ4' -Task 'Reasoning over conflicting references' -Dataset 'ConfRAG' -DataSource 'Heterogeneous web references' -SampleSize '1814 questions;9.58 paragraphs average' -Method 'Answer clustering and conflict-aware reasoning benchmark' -Metrics 'Answer clustering;answer coverage;reason coverage' -Component 'Claim Graph;Evidence Gate;Summarize Agent;Evaluation' -Implication '用于共识、分歧和冲突理由覆盖评测；待全文复核'
    New-LiteratureRow -Id 'LIT-2024-002' -Citekey 'edge2024graphrag' -Title 'From Local to Global: A Graph RAG Approach to Query-Focused Summarization' -Authors 'Darren Edge;Ha Trinh;Newman Cheng;Joshua Bradley;Alex Chao;Apurva Mody;Steven Truitt;Dasha Metropolitansky;Robert Osazuwa Ness;Jonathan Larson' -Year 2024 -Venue 'arXiv' -Url 'https://arxiv.org/abs/2404.16130' -Cluster 'E' -Rq 'RQ4;RQ5' -Task 'Global query-focused summarization over document corpora' -SampleSize 'Corpora around one million tokens' -Method 'Entity graph;community detection;community summaries' -Metrics 'Comprehensiveness;diversity' -Component 'Metric Ontology;Claim Graph;Summarize Agent;Evaluation' -Implication '用于全局主题综合；必须与向量和扁平图基线比较；待全文复核'
    New-LiteratureRow -Id 'LIT-2024-003' -Citekey 'gutierrez2024hipporag' -Title 'HippoRAG: Neurobiologically Inspired Long-Term Memory for Large Language Models' -Authors 'Bernal Jiménez Gutiérrez;Yiheng Shu;Yu Gu;Michihiro Yasunaga;Yu Su' -Year 2024 -Venue 'NeurIPS' -Url 'https://doi.org/10.52202/079017-1902' -Cluster 'E' -Rq 'RQ5' -Task 'Knowledge integration and multi-hop retrieval' -Method 'Knowledge graph plus Personalized PageRank retrieval' -Component 'Metric Ontology;Claim Graph;Evaluation' -Implication '用于多跳图检索基线和成本/时延比较；待全文复核'
    New-LiteratureRow -Id 'LIT-2024-004' -Citekey 'liu2024agentbench' -Title 'AgentBench: Evaluating LLMs as Agents' -Authors 'Xiao Liu et al.' -Year 2024 -Venue 'ICLR' -Url 'https://arxiv.org/abs/2308.03688' -Cluster 'G' -Rq 'RQ7' -Task 'LLM agents in interactive environments' -Dataset 'AgentBench' -DataSource 'Eight interactive environments' -SampleSize '8 environments' -InputModality 'text;tool interaction' -Method 'Multi-environment agent benchmark' -Component 'Agent Orchestration;Evaluation' -Implication '用于任务完成、长期推理、决策和指令遵循评测；待全文复核'
    New-LiteratureRow -Id 'LIT-2025-004' -Citekey 'zhu2025multiagentbench' -Title 'MultiAgentBench: Evaluating the Collaboration and Competition of LLM agents' -Authors 'Kunlun Zhu et al.' -Year 2025 -Venue 'ACL' -Url 'https://doi.org/10.18653/v1/2025.acl-long.421' -Cluster 'G' -Rq 'RQ7' -Task 'Multi-agent collaboration and competition' -Dataset 'MultiAgentBench' -DataSource 'Interactive multi-agent scenarios' -InputModality 'text;agent trajectories' -Method 'Milestone KPIs and coordination topologies' -Component 'Agent Orchestration;Evaluation' -Implication '用于里程碑、协作质量和拓扑消融；待全文复核' -CodeUrl 'https://github.com/ulab-uiuc/MARBLE'
    New-LiteratureRow -Id 'LIT-2023-003' -Citekey 'mialon2023gaia' -Title 'GAIA: a benchmark for General AI Assistants' -Authors 'Grégoire Mialon;Clémentine Fourrier;Craig Swift;Thomas Wolf;Yann LeCun;Thomas Scialom' -Year 2023 -Venue 'arXiv' -Url 'https://arxiv.org/abs/2311.12983' -Cluster 'G' -Rq 'RQ7' -Task 'Real-world assistant tasks requiring reasoning multimodality and tools' -Dataset 'GAIA' -DataSource 'Curated real-world questions' -SampleSize '466 questions' -InputModality 'text;multimodal;tool interaction' -Method 'Three-level assistant benchmark' -Component 'Agent Orchestration;Evaluation' -Implication '用于端到端工具使用和鲁棒性评测；待全文复核'
)

$rows | Export-Csv -LiteralPath $outputPath -NoTypeInformation -Encoding utf8
Write-Host "Wrote $($rows.Count) bootstrap literature rows to $outputPath"
