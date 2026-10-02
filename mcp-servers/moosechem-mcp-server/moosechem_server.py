import json
import logging
logger = logging.getLogger(__name__)
import os
import re
import subprocess
import threading
import time
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional

import requests
from fastmcp import FastMCP

# ── Конфигурация (через переменные окружения, как в других серверах) ───────
LLM_API_KEY = os.getenv("OPENROUTER_API_KEY")
LLM_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
LLM_MODEL = os.getenv("MOOSECHEM_QUERY_MODEL", "openai/gpt-4o-mini")
# Имя модели для самого MOOSE-Chem (без слэша! см. _patch_main_sh ниже)
MOOSECHEM_MODEL = os.getenv("MOOSECHEM_MODEL", "gpt-4o-mini")
MOOSECHEM_PATH = os.getenv("MOOSECHEM_PATH", "/app/MOOSE-Chem")
MAX_PAPERS_PER_QUERY = int(os.getenv("MOOSECHEM_MAX_PAPERS_PER_QUERY", "10"))

# Стандартные имена файлов, под которые MOOSE-Chem сохраняет результаты —
# вычисляются по MOOSECHEM_MODEL, чтобы не собирать их руками в каждом вызове.
_SCREENING_FILENAME = f"coarse_inspiration_search_{MOOSECHEM_MODEL}_.json"
_HYPOTHESES_FILENAME = f"hypothesis_generation_{MOOSECHEM_MODEL}_.json"
_EVALUATION_FILENAME = f"evaluation_{MOOSECHEM_MODEL}_.json"

# Папка для job-статусов фоновых запусков run_moosechem
JOBS_DIR = Path(os.getenv("MOOSECHEM_JOBS_DIR", "/app/jobs"))
JOBS_DIR.mkdir(parents=True, exist_ok=True)

# Семафор — только один run_moosechem одновременно
_moosechem_lock = threading.Lock()

mcp = FastMCP("MooseChem")


# ── Вспомогательные функции: PubMed + LLM ───────────────────────────────────
def _generate_pubmed_queries(research_question: str, background_survey: str) -> list[str]:
    prompt = f"""You are a scientific literature search expert.

Given a research question and background survey, generate 12 PubMed search queries to build a relevant inspiration corpus.

Rules:
- First identify the key SUBJECT-SPECIFIC anchor terms in the question/background
  (e.g. the organism, taxon, family, or specific compound class named there).
- Every query MUST include at least one of these anchor terms (or a close synonym),
  so results stay grounded in the actual subject matter — do NOT drift into
  generic methodology unrelated to the subject.
- Within that constraint, queries must cover ADJACENT methodological/topical angles,
  NOT direct restatements of the research question itself.
- Do NOT repeat the exact phrasing already used in the question or background.
- Each query must be 3-6 words.
- Return ONLY a JSON array of strings, nothing else

Research question: {research_question}
Background survey: {background_survey}

Example: ["query one", "query two", "query three"]"""

    # [reliability] Increased timeout (30 -> 90s) + retry with backoff.
    # OpenRouter occasionally stalls past 30s on this call, forcing a full
    # build_corpus restart (~60-90s wasted per retry, observed multiple
    # times in practice). This costs nothing in hypothesis quality.
    last_exc = None
    for attempt in range(3):
        try:
            response = requests.post(
                f"{LLM_BASE_URL}/chat/completions",
                headers={"Authorization": f"Bearer {LLM_API_KEY}", "Content-Type": "application/json"},
                json={"model": LLM_MODEL, "max_tokens": 500,
                      "messages": [{"role": "user", "content": prompt}]},
                timeout=90,
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"].strip()
            start = content.find("[")
            end = content.rfind("]") + 1
            return json.loads(content[start:end])
        except Exception as exc:
            last_exc = exc
            if attempt < 2:
                time.sleep(2 ** attempt)  # 1s, 2s backoff
                continue
    raise last_exc


def _search_pubmed(query: str, max_results: int) -> list[str]:
    url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
    params = {"db": "pubmed", "term": query, "retmax": max_results,
              "retmode": "json", "sort": "relevance"}
    try:
        r = requests.get(url, params=params, timeout=20)
        r.raise_for_status()
        return r.json()["esearchresult"]["idlist"]
    except Exception as e:
        logging.warning(f"PubMed search failed for '{query}': {e}")
        return []


def _fetch_abstracts(pmids: list[str]) -> list[list[str]]:
    if not pmids:
        return []
    url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
    params = {"db": "pubmed", "id": ",".join(pmids), "rettype": "xml", "retmode": "xml"}
    try:
        r = requests.get(url, params=params, timeout=30)
        r.raise_for_status()
        root = ET.fromstring(r.content)
    except Exception as e:
        logging.warning(f"PubMed fetch failed: {e}")
        return []

    papers = []
    for article in root.findall(".//PubmedArticle"):
        title_el = article.find(".//ArticleTitle")
        title = "".join(title_el.itertext()).strip() if title_el is not None else ""
        abstract_parts = article.findall(".//AbstractText")
        abstract = " ".join("".join(el.itertext()).strip() for el in abstract_parts).strip()
        if title and abstract:
            papers.append([title, abstract])
    return papers


def _search_openalex(query: str, max_results: int) -> list[list[str]]:
    """Поиск статей через OpenAlex API (бесплатно, без ключа)."""
    url = "https://api.openalex.org/works"
    params = {
        "search": query,
        "per_page": max_results,
        "filter": "has_abstract:true",
        "select": "title,abstract_inverted_index",
    }
    try:
        r = requests.get(url, params=params, timeout=20,
                         headers={"User-Agent": "CoScientist/1.0 (mailto:david.kurbanov2003@mail.ru)"})
        r.raise_for_status()
        results = r.json().get("results", [])
        papers = []
        for item in results:
            title = item.get("title", "")
            inv_index = item.get("abstract_inverted_index", {})
            if not title or not inv_index:
                continue
            # Восстанавливаем абстракт из inverted index
            words = [""] * (max(max(positions) for positions in inv_index.values()) + 1)
            for word, positions in inv_index.items():
                for pos in positions:
                    words[pos] = word
            abstract = " ".join(words).strip()
            if abstract:
                papers.append([title, abstract])
        return papers
    except Exception as e:
        logging.warning(f"OpenAlex search failed for '{query}': {e}")
        return []


# ── Вспомогательные функции: подготовка main.sh перед запуском ─────────────
def _write_background_json(
    moosechem_path: Path,
    research_question: str,
    background_survey: str,
    dest: Optional[Path] = None,
) -> Path:
    """Пишет background JSON в формате, который ожидает MOOSE-Chem:
    просто список из двух строк [question, background_survey].

    dest must be per-job: a shared Data/my_background.json is overwritten by
    concurrent users and then silently reused as "the" background.
    """
    data_dir = moosechem_path / "Data"
    data_dir.mkdir(parents=True, exist_ok=True)
    background_path = dest or (data_dir / "my_background.json")
    background_path.parent.mkdir(parents=True, exist_ok=True)
    with open(background_path, "w", encoding="utf-8") as f:
        json.dump([research_question, background_survey], f, ensure_ascii=False, indent=2)
    return background_path



def _build_corpus_job(
    job_id: str,
    research_question: str,
    background_survey: str,
    output_path: str,
    write_background_json: bool,
):
    """Фоновый поток для build_corpus — пишет статус в JOBS_DIR/{job_id}.json."""
    status_path = JOBS_DIR / f"{job_id}.json"
    status_path.write_text(json.dumps({"status": "running", "type": "corpus"}))
    try:
        queries = _generate_pubmed_queries(research_question, background_survey)
        all_papers = []
        seen_titles = set()
        query_stats = []
        for query in queries:
            added = 0

            # PubMed
            pmids = _search_pubmed(query, MAX_PAPERS_PER_QUERY)
            pubmed_papers = _fetch_abstracts(pmids)
            for paper in pubmed_papers:
                if paper[0] not in seen_titles:
                    seen_titles.add(paper[0])
                    all_papers.append(paper)
                    added += 1
            time.sleep(0.4)

            # OpenAlex
            openalex_papers = _search_openalex(query, MAX_PAPERS_PER_QUERY)
            for paper in openalex_papers:
                if paper[0] not in seen_titles:
                    seen_titles.add(paper[0])
                    all_papers.append(paper)
                    added += 1

            query_stats.append({"query": query, "papers_added": added})
            time.sleep(0.2)

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(all_papers, f, ensure_ascii=False, indent=2)

        background_path = None
        if write_background_json:
            dest = Path(MOOSECHEM_PATH) / "Data" / f"background_{job_id}.json"
            background_path = str(_write_background_json(
                Path(MOOSECHEM_PATH), research_question, background_survey, dest=dest
            ))

        status_path.write_text(json.dumps({
            "status": "success",
            "type": "corpus",
            "corpus_path": output_path,
            "background_path": background_path,
            "total_papers": len(all_papers),
            "queries": query_stats,
        }))
    except Exception as e:
        status_path.write_text(json.dumps({
            "status": "failed",
            "type": "corpus",
            "error": str(e),
        }))


def _patch_main_sh(
    moosechem_path: Path,
    main_sh: str,
    checkpoint_dir: str,
    corpus_path: Optional[str],
    background_path: Optional[Path],
) -> None:
    """Приводит main.sh в рабочее состояние перед запуском:
    - проставляет checkpoint_root_dir / custom_inspiration_corpus_path /
      custom_research_background_path под значения этого запуска
    - чинит баг оригинального репозитория: лишний обратный слэш внутри
      кавычек ломает парсинг аргумента argparse
    - убирает слэш из имени модели в путях к файлам результатов (слэш в
      "openai/gpt-4o-mini" интерпретируется bash'ем как разделитель папок)
    - заполняет api_type/base_url/api_key/model_name_*, если это ещё пустые
      placeholder'ы из чистого клона репозитория (страховка — обычно это уже
      зашито в образ на этапе сборки, см. Dockerfile)
    """
    main_sh_path = moosechem_path / main_sh
    content = main_sh_path.read_text(encoding="utf-8")

    # 1) checkpoint_root_dir / custom_inspiration_corpus_path / background — под этот запуск
    content = re.sub(
        r'checkpoint_root_dir="[^"]*"',
        f'checkpoint_root_dir="./{checkpoint_dir}"',
        content,
    )
    if corpus_path:
        content = re.sub(
            r'custom_inspiration_corpus_path="[^"]*"',
            f'custom_inspiration_corpus_path="{corpus_path}"',
            content,
        )
    if background_path:
        content = re.sub(
            r'custom_research_background_path="[^"]*"',
            f'custom_research_background_path="{background_path}"',
            content,
        )

    # Ускорение без потери качества
    # Reverted to original MOOSE-Chem defaults (was patched to 1 for speed during dev/testing)
    content = re.sub(r'--num_self_explore_steps_each_line \d+', '--num_self_explore_steps_each_line 3', content)
    # Reverted to 3 for isolation testing (was patched to 5, caused pipeline
    # failures — investigating whether it's the keep_size change itself or
    # unrelated LLM question-reformulation between retries).
    content = re.sub(r'--num_screening_keep_size \d+', '--num_screening_keep_size 3', content)
    # num_screening_window_size оставляем оригинальным (15) — уменьшение до 8 ломает скрининг
    content = re.sub(r'--num_itr_self_refine \d+', '--num_itr_self_refine 3', content)

    # 2) Фикс известного бага кавычек (страховка, обычно уже пофикшено в образе)
    content = content.replace(
        '--custom_research_background_path "${custom_research_background_path} \\"',
        '--custom_research_background_path "${custom_research_background_path}" \\',
    )
    content = content.replace(
        '--custom_inspiration_corpus_path ${custom_inspiration_corpus_path}',
        '--custom_inspiration_corpus_path "${custom_inspiration_corpus_path}"',
    )
    content = content.replace(
        '--custom_research_background_path ${custom_research_background_path}',
        '--custom_research_background_path "${custom_research_background_path}"',
    )

    # 3) api_type / base_url / api_key / имя модели без слэша (страховка)
    content = re.sub(r'^api_type=\s*$', 'api_type=0', content, flags=re.M)
    if LLM_API_KEY:
        content = re.sub(r'^api_key=.*$', f'api_key="{LLM_API_KEY}"', content, flags=re.M)
    content = re.sub(r'^base_url=.*$', f'base_url="{LLM_BASE_URL}"', content, flags=re.M)
    content = re.sub(r'^model_name_insp_retrieval=.*$', f'model_name_insp_retrieval="{MOOSECHEM_MODEL}"', content, flags=re.M)
    content = re.sub(r'^model_name_gene=.*$', f'model_name_gene="{MOOSECHEM_MODEL}"', content, flags=re.M)
    content = re.sub(r'^model_name_eval=.*$', f'model_name_eval="{MOOSECHEM_MODEL}"', content, flags=re.M)

    main_sh_path.write_text(content, encoding="utf-8")


def _run_moosechem_job(
    job_id: str,
    moosechem_path: str,
    main_sh: str,
    checkpoint_dir: str,
    corpus_path: Optional[str],
    background_path: Optional[str],
):
    """Патчит main.sh, запускает его в фоновом потоке, пишет статус в
    JOBS_DIR/{job_id}.json вместе с готовыми путями к файлам результатов."""
    status_path = JOBS_DIR / f"{job_id}.json"
    checkpoint_full = f"{moosechem_path}/{checkpoint_dir}"
    result_paths = {
        "screening_path": f"{checkpoint_full}/{_SCREENING_FILENAME}",
        "hypotheses_path": f"{checkpoint_full}/{_HYPOTHESES_FILENAME}",
        "evaluation_path": f"{checkpoint_full}/{_EVALUATION_FILENAME}",
        "corpus_path": corpus_path,
        "background_path": background_path,
        "checkpoint_dir": checkpoint_dir,
    }

    # Ждём пока другой run_moosechem не завершится
    logger.info(f"[{job_id}] Waiting for lock...")
    status_path.write_text(json.dumps({"status": "queued", **result_paths}))

    with _moosechem_lock:
        logger.info(f"[{job_id}] Lock acquired, starting pipeline...")
        status_path.write_text(json.dumps({"status": "running", **result_paths}))

        try:
            _patch_main_sh(
                Path(moosechem_path),
                main_sh,
                checkpoint_dir,
                corpus_path,
                Path(background_path) if background_path else None,
            )

            # uv подменяет PATH для дочерних процессов
            env = os.environ.copy()
            env["PATH"] = "/usr/local/bin:" + env.get("PATH", "")

            # Создаём Logs заранее чтобы избежать race condition
            import pathlib
            pathlib.Path(os.path.join(moosechem_path, "Logs")).mkdir(exist_ok=True)

            # [profiling] Stream stdout line-by-line with timestamps so we can
            # see which generation stage (Inter-EA Step / Self-explore step /
            # mutations) takes the most time.
            from datetime import datetime as _dt
            timestamped_log_path = os.path.join(moosechem_path, "Logs", "timestamped_run.log")
            stdout_lines = []
            # [profiling] Append mode with a run separator — a single test
            # can trigger many retries of run_moosechem, and each overwrite
            # ("w" mode) would erase the log of a real, long-running attempt
            # once a fast cache-hit retry follows it.
            with open(timestamped_log_path, "a") as _logf:
                _logf.write(f"\n{'='*80}\n=== NEW RUN: {_dt.now().strftime('%Y-%m-%d %H:%M:%S')} ===\n{'='*80}\n")
                process = subprocess.Popen(
                    ["bash", main_sh],
                    cwd=moosechem_path,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    env=env,
                    bufsize=1,
                )
                for line in process.stdout:
                    ts = _dt.now().strftime("%H:%M:%S")
                    _logf.write(f"{ts} {line}")
                    _logf.flush()
                    stdout_lines.append(line)
                process.wait(timeout=3600)

            # Minimal shim matching the subprocess.CompletedProcess attributes
            # used below (result.returncode, result.stdout, result.stderr).
            class _Result:
                pass
            result = _Result()
            result.returncode = process.returncode
            result.stdout = "".join(stdout_lines)
            result.stderr = ""

            critic_results = {}

            status_path.write_text(json.dumps({
                "status": "success" if result.returncode == 0 else "failed",
                "returncode": result.returncode,
                "stdout_tail": result.stdout[-6000:] if result.stdout else "",
                "stderr_tail": result.stderr[-6000:] if result.stderr else "",
                "critic_results": critic_results,
                **result_paths,
            }))
        except Exception as e:
            status_path.write_text(json.dumps({"status": "failed", "error": str(e), **result_paths}))


def _load_job(job_id: Optional[str]) -> Optional[dict]:
    """Load a single job status file by id. Never scans other users' jobs."""
    if not job_id or not isinstance(job_id, str):
        return None
    if "/" in job_id or "\\" in job_id or ".." in job_id:
        return None
    status_path = JOBS_DIR / f"{job_id}.json"
    if not status_path.exists():
        return None
    try:
        return json.loads(status_path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def _resolve_result_path(
    *,
    job_id: Optional[str],
    explicit_path: Optional[str],
    path_key: str,
) -> tuple[Optional[str], Optional[dict], Optional[str]]:
    """Bind a result file to a specific job.

    Refuses the old "latest successful job on this container" fallback — that
    returned another user's hypotheses whenever evaluation_path/job_id was omitted.
    Returns (path, job_data, error_message).
    """
    job = _load_job(job_id) if job_id else None
    if explicit_path:
        return explicit_path, job, None
    if not job_id:
        return None, None, (
            f"job_id or {path_key} is required; refusing to use another run's results."
        )
    if job is None:
        return None, None, f"No job found with id {job_id}."
    if job.get("status") != "success":
        return None, job, (
            f"Job {job_id} is not complete (status={job.get('status')})."
        )
    path = job.get(path_key)
    if not path:
        return None, job, f"Job {job_id} has no {path_key}."
    return path, job, None


# ── Tool 1: сборка корпуса литературы ───────────────────────────────────────
@mcp.tool()
def build_corpus(
    research_question: str,
    background_survey: str,
    output_path: Optional[str] = None,
    write_background_json: bool = True,
) -> dict:
    """
    Start building a PubMed inspiration corpus as a background job (returns immediately
    with a corpus_job_id). Poll check_corpus_status(corpus_job_id) until status is
    "success", then call run_moosechem — it picks up the corpus automatically.

    Args:
        research_question: The scientific research question to build a corpus for
        background_survey: Short background survey describing existing methods/context
        output_path: Where to save the corpus JSON. Defaults to the standard location.
        write_background_json: Whether to also save question/background for run_moosechem.
    """
    if not LLM_API_KEY:
        return {"answer": "Error: OPENROUTER_API_KEY is not configured.", "metadata": {}}

    job_id = str(uuid.uuid4())[:8]
    output_path = output_path or f"{MOOSECHEM_PATH}/Data/corpus_{job_id}.json"

    thread = threading.Thread(
        target=_build_corpus_job,
        args=(job_id, research_question, background_survey, output_path, write_background_json),
        daemon=True,
    )
    thread.start()

    return {
        "answer": (
            f"Corpus build started (corpus_job_id={job_id}). "
            f"This takes ~60 seconds. "
            f"Poll check_corpus_status with this corpus_job_id, then call run_moosechem."
        ),
        "metadata": {
            "corpus_job_id": job_id,
            "corpus_path": output_path,
        },
    }


@mcp.tool()
def check_corpus_status(corpus_job_id: str) -> dict:
    """
    Check the status of a PubMed corpus build started via build_corpus.

    Once status is "success", corpus_path and background_path are ready —
    call run_moosechem immediately (it picks them up automatically).

    Args:
        corpus_job_id: The corpus_job_id returned by build_corpus
    """
    status_path = JOBS_DIR / f"{corpus_job_id}.json"
    if not status_path.exists():
        return {"answer": f"No corpus job found with id {corpus_job_id}.", "metadata": {"status": "unknown"}}

    status_data = json.loads(status_path.read_text())
    answer = f"Corpus job {corpus_job_id} status: {status_data.get('status')}"
    if status_data.get("status") == "success":
        answer += (
            f". {status_data.get('total_papers')} papers collected. "
            f"Ready — call run_moosechem now."
        )
    return {
        "answer": answer,
        "metadata": status_data,
    }


@mcp.tool()
def run_moosechem(
    checkpoint_dir: str,
    corpus_path: Optional[str] = None,
    background_path: Optional[str] = None,
    corpus_job_id: Optional[str] = None,
    main_sh: str = "main.sh",
) -> dict:
    """
    Start the MOOSE-Chem hypothesis generation pipeline (screening, generation,
    evaluation) as a background job, since a full run can take 10-60 minutes.

    Before launching, this patches main.sh to actually use the given
    checkpoint_dir / corpus_path / background_path (the upstream script reads
    these as static shell variables, not CLI args), and fixes known upstream
    main.sh bugs (quoting, slash-in-model-name path bug).

    Returns a job_id immediately; poll check_moosechem_status(job_id) for
    progress — once finished, that response includes the exact evaluation_path
    and screening_path needed for get_hypotheses/get_inspirations, no manual
    path assembly required.

    Args:
        checkpoint_dir: Output directory name for results, relative to the
            MOOSE-Chem root (e.g. "hyp_abc123_mcp"). Must be unique per
            research question — ASCII slugs of Cyrillic prompts collide.
        corpus_path: Path to a custom inspiration corpus JSON.
        background_path: Path to a my_background.json with [question, survey].
        corpus_job_id: Prefer this over shared defaults: load corpus_path /
            background_path from that build_corpus job.
        main_sh: Name of the bash entry script (default "main.sh")
    """
    moosechem_path = Path(MOOSECHEM_PATH)
    if not moosechem_path.exists():
        return {"answer": f"Error: MOOSE-Chem not found at {MOOSECHEM_PATH}", "metadata": {}}

    if corpus_job_id:
        corpus_job = _load_job(corpus_job_id)
        if corpus_job is None:
            return {
                "answer": f"Error: no corpus job found with id {corpus_job_id}.",
                "metadata": {},
            }
        if corpus_job.get("status") != "success":
            return {
                "answer": (
                    f"Error: corpus job {corpus_job_id} is not ready "
                    f"(status={corpus_job.get('status')})."
                ),
                "metadata": corpus_job,
            }
        corpus_path = corpus_path or corpus_job.get("corpus_path")
        background_path = background_path or corpus_job.get("background_path")

    checkpoint_full_path = moosechem_path / checkpoint_dir
    checkpoint_full_path.mkdir(parents=True, exist_ok=True)

    job_id = str(uuid.uuid4())[:8]

    thread = threading.Thread(
        target=_run_moosechem_job,
        args=(job_id, str(moosechem_path), main_sh, checkpoint_dir, corpus_path, background_path),
        daemon=True,
    )
    thread.start()

    return {
        "answer": (
            f"MOOSE-Chem run started (job_id={job_id}) using "
            f"corpus={corpus_path or 'main.sh default'}, "
            f"background={background_path or 'main.sh default'}. "
            f"This typically takes 10-60 minutes. "
            f"Poll check_moosechem_status with this job_id for progress and result paths."
        ),
        "metadata": {
            "job_id": job_id,
            "checkpoint_dir": str(checkpoint_full_path),
            "corpus_path": corpus_path,
            "background_path": background_path,
        },
    }


# ── Tool 3: статус фонового job'а ───────────────────────────────────────────
@mcp.tool()
def check_moosechem_status(job_id: str) -> dict:
    """
    Check the status of a MOOSE-Chem run started via run_moosechem.

    Once status is "success", the response includes evaluation_path and
    screening_path — pass these directly to get_hypotheses / get_inspirations,
    no manual path assembly needed.

    Args:
        job_id: The job_id returned by run_moosechem
    """
    status_path = JOBS_DIR / f"{job_id}.json"
    if not status_path.exists():
        return {"answer": f"No job found with id {job_id}.", "metadata": {"status": "unknown"}}

    status_data = json.loads(status_path.read_text())
    answer = f"Job {job_id} status: {status_data.get('status')}"
    if status_data.get("status") == "success":
        answer += (
            f". Results ready — evaluation_path: {status_data.get('evaluation_path')}, "
            f"screening_path: {status_data.get('screening_path')}"
        )
    return {
        "answer": answer,
        "metadata": status_data,
    }


# ── Tool 4: получить топ гипотез ────────────────────────────────────────────
@mcp.tool()
def get_hypotheses(
    job_id: Optional[str] = None,
    evaluation_path: Optional[str] = None,
    top_n: int = 5,
    min_score: float = 0.0,
) -> dict:
    """
    Retrieve the top-scored hypotheses generated by MOOSE-Chem.

    Args:
        job_id: The job_id returned by run_moosechem. Required unless
            evaluation_path is given. Never falls back to "the latest success
            on this container" — that leaked other users' results.
        evaluation_path: Path to evaluation_<model>_.json produced by MOOSE-Chem.
        top_n: Number of top hypotheses to return (by score, descending)
        min_score: Minimum score (0-4) to include a hypothesis
    """
    evaluation_path, job, err = _resolve_result_path(
        job_id=job_id, explicit_path=evaluation_path, path_key="evaluation_path"
    )
    if err:
        return {"answer": f"Error: {err}", "metadata": {}}

    try:
        with open(evaluation_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return {"answer": f"Error: evaluation file not found at {evaluation_path}", "metadata": {}}

    question = list(data[0].keys())[0]
    hypotheses_raw = data[0][question]

    # Critic annotations and corpus lookup must come from THIS job, not
    # whichever run last succeeded on the shared Docker volume.
    critic_results = (job or {}).get("critic_results", {}) or {}

    hypotheses = []
    for i, item in enumerate(hypotheses_raw):
        score = item[1]
        if score >= min_score:
            critic = critic_results.get(str(i), {})
            hypotheses.append({
                "text": item[0],
                "score": score,
                "criteria_scores": item[2],
                "inspiration": str(item[3]),
                "critic_passed": critic.get("passed"),
                "critic_scores": critic.get("scores"),
                "critic_feedback": critic.get("feedback"),
            })

    # Diversify by inspiration: first take each inspiration's best hypothesis,
    # then round-robin through remaining ones by score, so top_n hypotheses
    # aren't dominated by a single over-represented Inter-EA branch.
    from collections import defaultdict
    by_insp = defaultdict(list)
    for h in hypotheses:
        by_insp[h["inspiration"]].append(h)
    for insp in by_insp:
        by_insp[insp].sort(key=lambda h: h["score"], reverse=True)

    top = []
    round_idx = 0
    insp_keys = list(by_insp.keys())
    while len(top) < top_n and any(round_idx < len(by_insp[k]) for k in insp_keys):
        candidates = [(k, by_insp[k][round_idx]) for k in insp_keys if round_idx < len(by_insp[k])]
        candidates.sort(key=lambda kv: kv[1]["score"], reverse=True)
        for _, h in candidates:
            if len(top) >= top_n:
                break
            top.append(h)
        round_idx += 1

    # Загружаем корпус для поиска абстрактов вдохновений
    corpus_path = (job or {}).get("corpus_path") or os.path.join(
        MOOSECHEM_PATH, "Data", "smart_corpus.json"
    )
    corpus_index = {}
    if os.path.exists(corpus_path):
        try:
            with open(corpus_path) as f:
                corpus = json.load(f)
            corpus_index = {entry[0].lower(): entry[1] for entry in corpus if len(entry) >= 2}
        except Exception:
            pass

    # Добавляем абстракт и tools к каждой гипотезе
    default_tools = ["spectroscopy", "chromatography", "in_vitro_assay", "computational_modeling"]
    for h in top:
        insp_title = h.get("inspiration", "")
        if insp_title and insp_title.lower() in corpus_index:
            h["inspiration_abstract"] = corpus_index[insp_title.lower()]
        else:
            h["inspiration_abstract"] = None

        # Извлекаем tools через LLM из текста гипотезы
        try:
            prompt = (
                "Extract a list of specific experimental/analytical methods "
                "mentioned in this hypothesis text. Return ONLY a JSON array "
                "of short method names. If none mentioned, infer 2-4 standard "
                "methods needed to test this claim. Return ONLY JSON array.\n\n"
                f"Text: {h['text'][:1500]}"
            )
            resp = requests.post(
                f"{LLM_BASE_URL}/chat/completions",
                headers={"Authorization": f"Bearer {LLM_API_KEY}"},
                json={"model": LLM_MODEL, "messages": [{"role": "user", "content": prompt}],
                      "max_tokens": 200, "temperature": 0.2},
                timeout=20,
            )
            content_str = resp.json()["choices"][0]["message"]["content"].strip()
            start = content_str.find("[")
            end = content_str.rfind("]") + 1
            h["tools"] = json.loads(content_str[start:end]) if start != -1 else default_tools
        except Exception:
            h["tools"] = default_tools

        # Извлекаем variables (independent/dependent/covariates) через LLM.
        # Формат строго под Pydantic-модель: name, description, unit (или null),
        # scale из {nominal, ordinal, interval, ratio}.
        default_variables = {
            "independent": [{"name": "input feature", "description": "primary independent factor under study", "unit": None, "scale": "nominal"}],
            "dependent": [{"name": "outcome", "description": "measured response of the hypothesis", "unit": None, "scale": "ratio"}],
            "covariates": [],
        }
        try:
            v_prompt = (
                "Extract the scientific variables from this hypothesis. "
                "Return ONLY a JSON object with keys 'independent', 'dependent', 'covariates'. "
                "Each is an array of objects with EXACTLY these fields: "
                "'name' (string), 'description' (string, required, non-empty), "
                "'unit' (string or null), 'scale' (MUST be one of: nominal, ordinal, interval, ratio). "
                "Do not put units or measurement info into 'scale' — scale is only the statistical type. "
                "Return ONLY the JSON object, no markdown.\n\n"
                f"Hypothesis: {h['text'][:1500]}"
            )
            v_resp = requests.post(
                f"{LLM_BASE_URL}/chat/completions",
                headers={"Authorization": f"Bearer {LLM_API_KEY}"},
                json={"model": LLM_MODEL, "messages": [{"role": "user", "content": v_prompt}],
                      "max_tokens": 600, "temperature": 0.2},
                timeout=25,
            )
            v_str = v_resp.json()["choices"][0]["message"]["content"].strip()
            v_start = v_str.find("{")
            v_end = v_str.rfind("}") + 1
            parsed_vars = json.loads(v_str[v_start:v_end]) if v_start != -1 else default_variables

            # Валидация и нормализация: гарантируем корректный scale и наличие description
            valid_scales = {"nominal", "ordinal", "interval", "ratio"}
            def _clean_var_list(lst):
                cleaned = []
                for v in (lst or []):
                    if not isinstance(v, dict):
                        continue
                    name = str(v.get("name", "")).strip() or "variable"
                    desc = str(v.get("description", "")).strip() or name
                    unit = v.get("unit")
                    unit = str(unit) if unit not in (None, "", "null") else None
                    scale = str(v.get("scale", "nominal")).strip().lower()
                    if scale not in valid_scales:
                        scale = "nominal"
                    cleaned.append({"name": name, "description": desc, "unit": unit, "scale": scale})
                return cleaned

            h["variables"] = {
                "independent": _clean_var_list(parsed_vars.get("independent")) or default_variables["independent"],
                "dependent": _clean_var_list(parsed_vars.get("dependent")) or default_variables["dependent"],
                "covariates": _clean_var_list(parsed_vars.get("covariates")),
            }
        except Exception:
            h["variables"] = default_variables

    titles_preview = "\n".join(
        f"- (score {h['score']}, critic={'✓' if h.get('critic_passed') else '✗' if h.get('critic_passed') is False else '?'}) {h['text'][:100]}..."
        for h in top
    )
    answer = f"Found {len(hypotheses)} hypotheses above score {min_score}. Top {len(top)}:\n{titles_preview}"

    return {
        "answer": answer,
        "metadata": {
            "evaluation_path": evaluation_path,
            "job_id": job_id,
            "research_question": question,
            "total_hypotheses": len(hypotheses),
            "hypotheses": top,
        },
    }


# ── Tool 5: какие статьи легли в основу гипотез (screening funnel) ─────────
@mcp.tool()
def get_inspirations(
    job_id: Optional[str] = None,
    screening_path: Optional[str] = None,
) -> dict:
    """
    Show which papers MOOSE-Chem selected as inspiration during the screening
    funnel (from the full corpus down to the final 3-5 inspiration papers).

    Args:
        job_id: The job_id returned by run_moosechem. Required unless
            screening_path is given. Does not fall back to the latest job.
        screening_path: Path to coarse_inspiration_search_<model>_.json.
    """
    screening_path, _job, err = _resolve_result_path(
        job_id=job_id, explicit_path=screening_path, path_key="screening_path"
    )
    if err:
        return {"answer": f"Error: {err}", "metadata": {}}

    try:
        with open(screening_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return {"answer": f"Error: screening file not found at {screening_path}", "metadata": {}}

    question = list(data[0].keys())[0]
    rounds = data[0][question]

    rounds_info = [
        {"round": i, "count": len(papers), "titles": [p[0] for p in papers]}
        for i, papers in enumerate(rounds)
    ]
    final_titles = [p[0] for p in rounds[-1]] if rounds else []

    answer = (
        f"Screening went through {len(rounds)} rounds, narrowing from "
        f"{rounds_info[0]['count'] if rounds_info else 0} to {len(final_titles)} inspiration papers:\n"
        + "\n".join(f"- {t}" for t in final_titles)
    )

    return {
        "answer": answer,
        "metadata": {
            "screening_path": screening_path,
            "research_question": question,
            "rounds": rounds_info,
            "final_inspirations": final_titles,
        },
    }


if __name__ == "__main__":
    mcp.run(transport="http", host="0.0.0.0", port=7331, path="/mcp")
