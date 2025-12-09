from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from dotenv import load_dotenv
from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, FieldValidationInfo, field_validator
from pydantic_settings import BaseSettings

load_dotenv()

logger = logging.getLogger("mcp-tester")
logging.basicConfig(level=logging.INFO)


class Settings(BaseSettings):
    host: str = Field("0.0.0.0", alias="MCP_TESTER_HOST")
    port: int = Field(8330, alias="MCP_TESTER_PORT")
    allow_origins: Optional[str] = Field(None, alias="MCP_TESTER_ALLOW_ORIGINS")
    targets_blob: Optional[str] = Field(None, alias="MCP_TESTER_TARGETS")
    suite_file: Optional[str] = Field(None, alias="MCP_TESTER_SUITE_FILE")
    suite_files: Optional[str] = Field(None, alias="MCP_TESTER_SUITE_FILES")
    default_timeout_ms: int = Field(5000, alias="MCP_TESTER_DEFAULT_TIMEOUT_MS")
    verify_tls: bool = Field(True, alias="MCP_TESTER_VERIFY_TLS")
    history_file: Optional[str] = Field(None, alias="MCP_TESTER_HISTORY_FILE")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"

    def cors_origins(self) -> List[str]:
        if not self.allow_origins:
            return ["*"]
        return [origin.strip() for origin in self.allow_origins.split(",") if origin.strip()]


settings = Settings()


class TestDefinition(BaseModel):
    name: str = Field(..., description="Unique name for display + filtering")
    url: str = Field(..., description="Target HTTP URL (supports env placeholders like {{MCP0_URL}})")
    method: str = Field("GET", description="HTTP method to use when calling the target")
    description: Optional[str] = None
    expect_status: int = Field(200, description="Expected HTTP status code")
    timeout_ms: Optional[int] = Field(None, description="Per-attempt timeout override in milliseconds")
    retries: int = Field(0, description="Number of retry attempts after the first try")
    retry_delay_ms: int = Field(750, description="Delay between retries in milliseconds")
    allow_redirects: bool = Field(True, description="Forward redirects when hitting the endpoint")
    verify_tls: Optional[bool] = Field(None, description="Override TLS verification per test")
    headers: Dict[str, str] = Field(default_factory=dict, description="Additional request headers")
    body: Optional[Any] = Field(None, description="Optional request payload for non-GET calls")
    requires_env: List[str] = Field(default_factory=list, description="Env variables that must be defined or this test is skipped")
    summary_path: Optional[str] = Field(None, description="Dot-path inside JSON response for success confirmation (e.g., 'status')")
    expect_json_contains: Optional[Dict[str, Any]] = Field(
        None, description="JSON key/value pairs that must match for the test to pass"
    )

    @field_validator("method", mode="before")
    @classmethod
    def normalize_method(cls, value: str) -> str:
        method = (value or "GET").strip().upper()
        if method not in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}:
            raise ValueError(f"Unsupported HTTP method '{value}'")
        return method

    @field_validator("retries", "retry_delay_ms", mode="before")
    @classmethod
    def non_negative(cls, value: Optional[int], info: FieldValidationInfo) -> Optional[int]:
        if value is None:
            return value
        if value < 0:
            field_name = info.field_name or "value"
            raise ValueError(f"{field_name} cannot be negative")
        return value


class TestResult(BaseModel):
    name: str
    status: str
    description: Optional[str]
    target_url: str
    method: str
    expect_status: int
    actual_status: Optional[int]
    latency_ms: Optional[int]
    attempts: int
    error: Optional[str]
    body_excerpt: Optional[str]
    skipped: bool = False


class TestRunSummary(BaseModel):
    run_id: str
    started_at: datetime
    completed_at: datetime
    duration_ms: int
    total: int
    passed: int
    failed: int
    results: List[TestResult]


class RunRequest(BaseModel):
    tests: Optional[List[str]] = Field(None, description="Subset of test names to execute")
    fail_fast: bool = Field(False, description="Abort the run after the first failure")
    timeout_ms: Optional[int] = Field(None, ge=100, description="Override timeout for every test (ms)")
    retries: Optional[int] = Field(None, ge=0, description="Override retries for every test")
    retry_delay_ms: Optional[int] = Field(None, ge=0, description="Override retry delay (ms)")


def _expand_env_placeholders(value: str) -> str:
    pattern = re.compile(r"\{\{([A-Z0-9_]+)\}\}")

    def replacer(match: re.Match[str]) -> str:
        key = match.group(1)
        return os.getenv(key, match.group(0))

    return pattern.sub(replacer, value)


def _expand_structure(payload: Any) -> Any:
    if isinstance(payload, str):
        return _expand_env_placeholders(payload)
    if isinstance(payload, list):
        return [_expand_structure(item) for item in payload]
    if isinstance(payload, dict):
        return {key: _expand_structure(value) for key, value in payload.items()}
    return payload


def _load_json_entries(label: str, content: str) -> List[Dict[str, Any]]:
    try:
        data = json.loads(content)
        if not isinstance(data, list):
            raise ValueError("JSON payload must be an array")
        return [item for item in data if isinstance(item, dict)]
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to parse %s suite: %s", label, exc)
        return []


def load_test_definitions() -> List[TestDefinition]:
    raw_entries: Dict[str, Dict[str, Any]] = {}
    sources: List[tuple[str, str]] = []

    default_file = Path(__file__).with_name("tests.example.json")
    if default_file.exists():
        sources.append(("tests.example.json", default_file.read_text()))

    suite_candidates: List[str] = []
    if settings.suite_file:
        suite_candidates.append(settings.suite_file)
    if settings.suite_files:
        suite_candidates.extend(
            entry.strip() for entry in settings.suite_files.split(",") if entry.strip()
        )

    for candidate in suite_candidates:
        path = Path(candidate)
        if path.exists():
            sources.append((str(path), path.read_text()))
        else:
            logger.warning("Suite file %s not found (from MCP_TESTER suite settings)", candidate)

    if settings.targets_blob:
        sources.append(("MCP_TESTER_TARGETS", settings.targets_blob))

    for label, content in sources:
        for entry in _load_json_entries(label, content):
            expanded = _expand_structure(entry)
            name = (expanded.get("name") or "").strip()
            if not name:
                logger.warning("Skipping entry without name in %s", label)
                continue
            raw_entries[name] = expanded

    tests = [TestDefinition(**entry) for entry in raw_entries.values()]
    tests.sort(key=lambda item: item.name.lower())

    if not tests:
        raise RuntimeError("No MCP tester targets were loaded; provide MCP_TESTER_TARGETS or a suite file.")

    logger.info("Loaded %d MCP tester targets", len(tests))
    return tests


class SuiteManager:
    def __init__(self) -> None:
        self._tests: List[TestDefinition] = []
        self._test_lookup: Dict[str, TestDefinition] = {}
        self._latest_run: Optional[TestRunSummary] = None
        self._lock = asyncio.Lock()
        self.reload()

    def reload(self) -> List[TestDefinition]:
        tests = load_test_definitions()
        self._tests = tests
        self._test_lookup = {test.name: test for test in tests}
        return tests

    def list_tests(self) -> List[TestDefinition]:
        return self._tests

    def select(self, names: Optional[List[str]]) -> List[TestDefinition]:
        if not names:
            return self._tests
        missing = [name for name in names if name not in self._test_lookup]
        if missing:
            raise HTTPException(status_code=404, detail=f"Unknown test(s): {', '.join(missing)}")
        return [self._test_lookup[name] for name in names]

    @property
    def latest_run(self) -> Optional[TestRunSummary]:
        return self._latest_run

    async def record_run(self, summary: TestRunSummary) -> None:
        async with self._lock:
            self._latest_run = summary


suite_manager = SuiteManager()

app = FastAPI(title="mcp-tester", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins(),
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)


def _excerpt(text: Optional[str], limit: int = 480) -> Optional[str]:
    if not text:
        return None
    snippet = text.strip().replace("\r\n", "\n")
    if len(snippet) <= limit:
        return snippet
    return snippet[: limit - 3] + "..."


async def _execute_test(test: TestDefinition, overrides: RunRequest) -> TestResult:
    missing_env = [name for name in test.requires_env if not os.getenv(name)]
    if missing_env:
        return TestResult(
            name=test.name,
            status="skipped",
            description=test.description,
            target_url=test.url,
            method=test.method,
            expect_status=test.expect_status,
            actual_status=None,
            latency_ms=None,
            attempts=0,
            error=f"Missing env vars: {', '.join(missing_env)}",
            body_excerpt=None,
            skipped=True,
        )

    effective_timeout_ms = overrides.timeout_ms or test.timeout_ms or settings.default_timeout_ms
    effective_retries = overrides.retries if overrides.retries is not None else test.retries
    effective_delay_ms = overrides.retry_delay_ms if overrides.retry_delay_ms is not None else test.retry_delay_ms
    verify = test.verify_tls if test.verify_tls is not None else settings.verify_tls
    attempts = 0
    last_error: Optional[str] = None
    start_ts = datetime.now(timezone.utc)

    for attempt in range(effective_retries + 1):
        attempts = attempt + 1
        try:
            request_kwargs: Dict[str, Any] = {
                "method": test.method,
                "url": test.url,
                "headers": test.headers or None,
                "timeout": httpx.Timeout(effective_timeout_ms / 1000),
                "follow_redirects": test.allow_redirects,
            }
            if test.body is not None:
                if isinstance(test.body, (dict, list)):
                    request_kwargs["json"] = test.body
                    headers = request_kwargs["headers"] or {}
                    if not any(k.lower() == "content-type" for k in headers.keys()):
                        headers = dict(headers)
                        headers["Content-Type"] = "application/json"
                        request_kwargs["headers"] = headers
                else:
                    request_kwargs["content"] = str(test.body)

            async with httpx.AsyncClient(verify=verify) as client:
                response = await client.request(**request_kwargs)
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)
            if attempt < effective_retries:
                await asyncio.sleep(effective_delay_ms / 1000)
            continue

        latency_ms = int((datetime.now(timezone.utc) - start_ts).total_seconds() * 1000)
        if response.status_code == test.expect_status:
            return TestResult(
                name=test.name,
                status="passed",
                description=test.description,
                target_url=test.url,
                method=test.method,
                expect_status=test.expect_status,
                actual_status=response.status_code,
                latency_ms=latency_ms,
                attempts=attempts,
                error=None,
                body_excerpt=None,
            )

        body_preview = _excerpt(response.text)
        last_error = f"Expected {test.expect_status}, received {response.status_code}"

        if attempt < effective_retries:
            await asyncio.sleep(effective_delay_ms / 1000)
        else:
            return TestResult(
                name=test.name,
                status="failed",
                description=test.description,
                target_url=test.url,
                method=test.method,
                expect_status=test.expect_status,
                actual_status=response.status_code,
                latency_ms=latency_ms,
                attempts=attempts,
                error=last_error,
                body_excerpt=body_preview,
            )

    return TestResult(
        name=test.name,
        status="failed",
        description=test.description,
        target_url=test.url,
        method=test.method,
        expect_status=test.expect_status,
        actual_status=None,
        latency_ms=None,
        attempts=attempts,
        error=last_error or "Unknown error",
        body_excerpt=None,
    )


async def run_suite(run_request: RunRequest) -> TestRunSummary:
    tests = suite_manager.select(run_request.tests)
    if not tests:
        raise HTTPException(status_code=400, detail="No tests available to run")

    started_at = datetime.now(timezone.utc)
    results: List[TestResult] = []

    for test in tests:
        result = await _execute_test(test, run_request)
        results.append(result)
        if run_request.fail_fast and result.status != "passed":
            break

    completed_at = datetime.now(timezone.utc)
    passed = sum(1 for item in results if item.status == "passed")
    failed = sum(1 for item in results if item.status != "passed")
    summary = TestRunSummary(
        run_id=str(uuid.uuid4()),
        started_at=started_at,
        completed_at=completed_at,
        duration_ms=int((completed_at - started_at).total_seconds() * 1000),
        total=len(results),
        passed=passed,
        failed=failed,
        results=results,
    )
    await suite_manager.record_run(summary)
    _persist_history(summary)
    return summary


@app.get("/health")
async def service_health() -> Dict[str, Any]:
    tests = suite_manager.list_tests()
    latest = suite_manager.latest_run
    status = "ok" if tests else "error"
    if latest and latest.failed:
        status = "degraded"
    return {
        "service": "mcp-tester",
        "status": status,
        "testsLoaded": len(tests),
        "latestRun": latest.dict() if latest else None,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/tests")
async def list_tests(refresh: bool = Query(False, description="Reload suite definitions before listing")) -> Dict[str, Any]:
    if refresh:
        suite_manager.reload()
    tests = [test.dict() for test in suite_manager.list_tests()]
    return {"tests": tests, "count": len(tests)}


@app.get("/tests/latest")
async def latest_run() -> TestRunSummary:
    latest = suite_manager.latest_run
    if not latest:
        raise HTTPException(status_code=404, detail="No test runs recorded yet")
    return latest


@app.post("/tests/run", response_model=TestRunSummary)
async def trigger_run(payload: RunRequest = Body(default_factory=RunRequest)) -> TestRunSummary:
    return await run_suite(payload)


def tool_definitions() -> List[Dict[str, Any]]:
    return [
        {
            "name": "list_tests",
            "description": "List all MCP tester checks and metadata.",
            "input_schema": {"type": "object"},
        },
        {
            "name": "run_tests",
            "description": "Execute the MCP tester suite or a subset of checks.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "tests": {"type": "array", "items": {"type": "string"}},
                    "fail_fast": {"type": "boolean"},
                    "timeout_ms": {"type": "integer"},
                    "retries": {"type": "integer"},
                    "retry_delay_ms": {"type": "integer"},
                },
            },
        },
    ]


@app.get("/tools")
async def list_tools() -> Dict[str, Any]:
    return {"tools": tool_definitions()}


@app.get("/.well-known/mcp.json")
async def well_known_manifest() -> Dict[str, Any]:
    return {
        "name": "mcp-tester",
        "version": "0.1.0",
        "description": "Chaba stack tester MCP provider",
        "capabilities": {"tools": tool_definitions()},
    }


@app.post("/invoke")
async def invoke_tool(payload: Dict[str, Any]) -> JSONResponse:
    tool = payload.get("tool")
    arguments = payload.get("arguments") or {}
    if tool == "list_tests":
        result = {"tests": [test.dict() for test in suite_manager.list_tests()]}
        return JSONResponse({"tool": tool, "result": result})
    if tool == "run_tests":
        run_request = RunRequest(**arguments)
        summary = await run_suite(run_request)
        return JSONResponse({"tool": tool, "result": summary.dict()})
    raise HTTPException(status_code=404, detail=f"Unknown tool '{tool}'")


@app.get("/")
async def root() -> Dict[str, Any]:
    return {"service": "mcp-tester", "version": "0.1.0", "status": "ok"}
