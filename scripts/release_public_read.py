#!/usr/bin/env python3
"""Credential-free, bounded public reads for release admission.

This module is the only network owner used by release preparation and status
gates.  Consumers construct endpoint-specific queries; they cannot supply an
arbitrary URL, headers, credentials, retry policy, or redirect policy.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Final, cast

PUBLIC_REPOSITORY: Final = "rergards/mempalace-code"
PUBLIC_PACKAGE: Final = "mempalace-code"
REVIEWED_UPSTREAM_REPOSITORY: Final = "MemPalace/mempalace"
REVIEWED_UPSTREAM_BRANCH: Final = "develop"
GITHUB_API: Final = "https://api.github.com"
PYPI_API: Final = "https://pypi.org"
FILES_HOST: Final = "files.pythonhosted.org"
TIMEOUT_SECONDS: Final = 30
JSON_LIMIT: Final = 2_000_000
ARTIFACT_LIMIT: Final = 128 * 1024 * 1024
ERROR_LIMIT: Final = 320
USER_AGENT: Final = "mempalace-code-release-public-read/1"
MAX_TAG_PEELS: Final = 4

_SHA = re.compile(r"^[0-9a-fA-F]{40}$")
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_BRANCH = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")
_WORKFLOWS = frozenset({"Tests", "Publish to PyPI", "Dependency Audit"})
_WORKFLOW_FILES = {
    "Tests": "ci.yml",
    "Publish to PyPI": "publish.yml",
    "Dependency Audit": "dependency-audit.yml",
}


class PublicReadError(RuntimeError):
    """A public response was unavailable, ambiguous, malformed, or untrusted."""


@dataclass(frozen=True)
class _PublicQuery:
    """One closed-set public endpoint request."""

    endpoint: str
    values: tuple[object, ...]


@dataclass(frozen=True)
class PublicResult:
    """Bounded normalized result returned to pure admission predicates."""

    data: object | None = None
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error


def _fixed(value: str, expected: str, label: str) -> str:
    if value != expected:
        raise ValueError(f"unsupported {label}: {value!r}")
    return value


def _sha(value: str) -> str:
    if not _SHA.fullmatch(value):
        raise ValueError("SHA must be exactly 40 hexadecimal characters")
    return value.lower()


def _name(value: str, label: str) -> str:
    if not _NAME.fullmatch(value) or value in {".", ".."}:
        raise ValueError(f"invalid {label}: {value!r}")
    return value


def _branch(value: str) -> str:
    if (
        not _BRANCH.fullmatch(value)
        or value.startswith("/")
        or value.endswith("/")
        or "//" in value
        or any(part in {"", ".", ".."} for part in value.split("/"))
    ):
        raise ValueError(f"invalid branch: {value!r}")
    return value


def _positive(value: int, label: str, maximum: int = 1000) -> int:
    if type(value) is not int or value <= 0 or value > maximum:
        raise ValueError(f"invalid {label}: {value!r}")
    return value


def check_runs(repo: str, sha: str, check_name: str, limit: int) -> _PublicQuery:
    return _PublicQuery(
        "github_check_runs",
        (
            _fixed(repo, PUBLIC_REPOSITORY, "repository"),
            _sha(sha),
            _fixed(check_name, "release-required", "check"),
            _positive(limit, "limit", 100),
        ),
    )


def workflow_runs(
    repo: str, workflow: str, limit: int, *, branch: str | None = None
) -> _PublicQuery:
    _fixed(repo, PUBLIC_REPOSITORY, "repository")
    if workflow not in _WORKFLOWS:
        raise ValueError(f"unsupported workflow: {workflow!r}")
    return _PublicQuery(
        "github_workflow_runs",
        (
            repo,
            workflow,
            _positive(limit, "limit", 100),
            _fixed(_branch(branch), "main", "workflow branch") if branch else None,
        ),
    )


def workflow_jobs(repo: str, run_id: int) -> _PublicQuery:
    return _PublicQuery(
        "github_workflow_jobs",
        (_fixed(repo, PUBLIC_REPOSITORY, "repository"), _positive(run_id, "run id", 10**12)),
    )


def releases(repo: str, limit: int) -> _PublicQuery:
    return _PublicQuery(
        "github_releases",
        (_fixed(repo, PUBLIC_REPOSITORY, "repository"), _positive(limit, "limit", 200)),
    )


def branch_rules(repo: str, branch: str) -> _PublicQuery:
    return _PublicQuery(
        "github_branch_rules",
        (
            _fixed(repo, PUBLIC_REPOSITORY, "repository"),
            _fixed(_branch(branch), "main", "branch"),
        ),
    )


def rulesets(repo: str, limit: int) -> _PublicQuery:
    return _PublicQuery(
        "github_rulesets",
        (_fixed(repo, PUBLIC_REPOSITORY, "repository"), _positive(limit, "limit", 100)),
    )


def ruleset(repo: str, ruleset_id: int) -> _PublicQuery:
    return _PublicQuery(
        "github_ruleset",
        (
            _fixed(repo, PUBLIC_REPOSITORY, "repository"),
            _positive(ruleset_id, "ruleset id", 10**12),
        ),
    )


def matching_version_tags(repo: str, limit: int = 100) -> _PublicQuery:
    return _PublicQuery(
        "github_matching_tags",
        (_fixed(repo, PUBLIC_REPOSITORY, "repository"), _positive(limit, "limit", 100)),
    )


def public_main(repo: str, branch: str = "main") -> _PublicQuery:
    return _PublicQuery(
        "github_commit",
        (
            _fixed(repo, PUBLIC_REPOSITORY, "repository"),
            _fixed(_branch(branch), "main", "branch"),
        ),
    )


def reviewed_upstream_head(repo: str, branch: str) -> _PublicQuery:
    return _PublicQuery(
        "github_upstream_head",
        (
            _fixed(repo, REVIEWED_UPSTREAM_REPOSITORY, "upstream repository"),
            _fixed(_branch(branch), REVIEWED_UPSTREAM_BRANCH, "upstream branch"),
        ),
    )


def pypi_metadata(package: str) -> _PublicQuery:
    return _PublicQuery("pypi_metadata", (_fixed(package, PUBLIC_PACKAGE, "package"),))


def pypi_distribution(url: str) -> _PublicQuery:
    parsed = urllib.parse.urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != FILES_HOST
        or parsed.port not in (None, 443)
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or not parsed.path.startswith("/packages/")
        or any(part in {"", ".", ".."} for part in parsed.path.split("/")[2:])
        or urllib.parse.unquote(parsed.path) != parsed.path
    ):
        raise ValueError("unsupported PyPI distribution URL")
    return _PublicQuery("pypi_distribution", (url,))


def pypi_provenance(package: str, version: str, filename: str) -> _PublicQuery:
    _fixed(package, PUBLIC_PACKAGE, "package")
    _name(version, "version")
    _name(filename, "filename")
    return _PublicQuery("pypi_provenance", (package, version, filename))


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(  # noqa: ANN001
        self, _req, _fp, _code, _msg, _headers, _newurl
    ):
        return None


def build_opener() -> urllib.request.OpenerDirector:
    """Build an opener that ignores ambient proxies and follows no redirects."""
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        _NoRedirect(),
        urllib.request.HTTPSHandler(),
        urllib.request.HTTPErrorProcessor(),
    )


class PublicReader:
    """Execute the closed query set through one sterile stdlib transport."""

    def __init__(self, opener: urllib.request.OpenerDirector | None = None) -> None:
        self._opener = opener or build_opener()

    def __call__(self, query: _PublicQuery) -> PublicResult:
        try:
            return PublicResult(self._execute(query))
        except (PublicReadError, ValueError) as exc:
            return PublicResult(error=_diagnostic(exc))

    def _execute(self, query: _PublicQuery) -> object:
        url, limit, accept = self._request_spec(query)
        body = self._get(url, limit=limit, accept=accept)
        if query.endpoint == "pypi_distribution":
            return body
        try:
            data = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PublicReadError("response was not valid UTF-8 JSON") from exc
        normalized = self._normalize(query, data)
        if query.endpoint == "github_releases":
            repo, requested_limit = query.values
            normalized_releases = cast("list[dict[str, object]]", normalized)
            page_number = 2
            while len(normalized_releases) < cast("int", requested_limit):
                page_size = min(100, cast("int", requested_limit) - len(normalized_releases))
                if len(normalized_releases) < (page_number - 1) * 100:
                    break
                page_body = self._get(
                    f"{GITHUB_API}/repos/{repo}/releases?per_page={page_size}&page={page_number}",
                    limit=JSON_LIMIT,
                    accept="application/vnd.github+json",
                )
                try:
                    page = json.loads(page_body.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise PublicReadError("release page was not valid JSON") from exc
                if not isinstance(page, list):
                    raise PublicReadError("unexpected release page response shape")
                normalized_releases.extend(_release(item) for item in page)
                if len(page) < page_size:
                    break
                page_number += 1
            if len(normalized_releases) >= cast("int", requested_limit):
                raise PublicReadError("release response hit the bounded pagination limit")
            latest_body = self._get(
                f"{GITHUB_API}/repos/{repo}/releases/latest",
                limit=JSON_LIMIT,
                accept="application/vnd.github+json",
            )
            try:
                latest = json.loads(latest_body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise PublicReadError("latest-release response was not valid JSON") from exc
            if not isinstance(latest, dict) or not isinstance(latest.get("tag_name"), str):
                raise PublicReadError("unexpected latest-release response shape")
            latest_tag = latest["tag_name"]
            return [
                {**item, "isLatest": item.get("tagName") == latest_tag}
                for item in normalized_releases
            ]
        if query.endpoint == "github_matching_tags":
            normalized_tags = cast("list[dict[str, str]]", normalized)
            if len(normalized_tags) >= cast("int", query.values[1]):
                raise PublicReadError("matching-ref response hit the bounded pagination limit")
            repo = str(query.values[0])
            return [self._peel_matching_tag(repo, item) for item in normalized_tags]
        return normalized

    def _peel_matching_tag(self, repo: str, item: dict[str, str]) -> dict[str, str]:
        if item["type"] == "commit":
            return item
        sha = item["sha"]
        seen = {sha}
        for _ in range(MAX_TAG_PEELS):
            url = f"{GITHUB_API}/repos/{repo}/git/tags/{sha}"
            body = self._get(url, limit=JSON_LIMIT, accept="application/vnd.github+json")
            try:
                payload = json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise PublicReadError("annotated-tag response was not valid JSON") from exc
            target = payload.get("object") if isinstance(payload, dict) else None
            if not isinstance(target, dict):
                raise PublicReadError("annotated-tag response has no target object")
            target_sha = target.get("sha")
            target_type = target.get("type")
            if (
                not isinstance(target_sha, str)
                or not _SHA.fullmatch(target_sha)
                or target_type not in {"commit", "tag"}
                or target_sha in seen
            ):
                raise PublicReadError("annotated-tag peel is invalid or cyclic")
            sha = target_sha.lower()
            if target_type == "commit":
                return {"ref": item["ref"], "sha": sha, "type": "commit"}
            seen.add(sha)
        raise PublicReadError("annotated-tag peel exceeds the bounded depth")

    def _get(self, url: str, *, limit: int, accept: str) -> bytes:
        request = urllib.request.Request(
            url,
            method="GET",
            headers={"User-Agent": USER_AGENT, "Accept": accept},
        )
        if any(name.lower() in {"authorization", "cookie"} for name, _ in request.header_items()):
            raise PublicReadError("forbidden credential header")
        try:
            with self._opener.open(request, timeout=TIMEOUT_SECONDS) as response:
                final_url = response.geturl()
                if final_url != url:
                    raise PublicReadError("redirects are forbidden")
                raw_lengths = response.headers.get_all("Content-Length") or []
                if len(raw_lengths) > 1:
                    raise PublicReadError("conflicting Content-Length headers")
                declared: int | None = None
                if raw_lengths:
                    try:
                        declared = int(raw_lengths[0])
                    except ValueError as exc:
                        raise PublicReadError("malformed Content-Length") from exc
                    if declared < 0 or declared > limit:
                        raise PublicReadError("response exceeds the endpoint size limit")
                body = response.read(limit + 1)
        except urllib.error.HTTPError as exc:
            raise PublicReadError(f"HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise PublicReadError(f"public GET failed: {type(exc).__name__}") from exc
        if len(body) > limit:
            raise PublicReadError("response exceeds the endpoint size limit")
        if declared is not None and len(body) != declared:
            raise PublicReadError("response length does not match Content-Length")
        return body

    def _request_spec(self, query: _PublicQuery) -> tuple[str, int, str]:
        endpoint = query.endpoint
        values = query.values
        json_accept = "application/vnd.github+json"
        if endpoint == "github_check_runs":
            repo, sha, name, limit = values
            path = f"/repos/{repo}/commits/{sha}/check-runs?check_name={urllib.parse.quote(str(name), safe='')}&per_page={limit}"
        elif endpoint == "github_workflow_runs":
            repo, workflow, limit, branch = values
            query_args = {"per_page": str(limit)}
            if branch is not None:
                query_args["branch"] = str(branch)
            encoded_workflow = urllib.parse.quote(_WORKFLOW_FILES[str(workflow)], safe="")
            path = f"/repos/{repo}/actions/workflows/{encoded_workflow}/runs?{urllib.parse.urlencode(query_args)}"
        elif endpoint == "github_workflow_jobs":
            repo, run_id = values
            path = f"/repos/{repo}/actions/runs/{run_id}/jobs?per_page=100"
        elif endpoint == "github_releases":
            repo, limit = values
            path = f"/repos/{repo}/releases?per_page={min(cast('int', limit), 100)}&page=1"
        elif endpoint == "github_branch_rules":
            repo, branch = values
            path = f"/repos/{repo}/rules/branches/{urllib.parse.quote(str(branch), safe='')}"
        elif endpoint == "github_rulesets":
            repo, limit = values
            path = f"/repos/{repo}/rulesets?per_page={limit}"
        elif endpoint == "github_ruleset":
            repo, ruleset_id = values
            path = f"/repos/{repo}/rulesets/{ruleset_id}"
        elif endpoint == "github_matching_tags":
            repo, limit = values
            path = f"/repos/{repo}/git/matching-refs/tags/v?per_page={limit}"
        elif endpoint in {"github_commit", "github_upstream_head"}:
            repo, ref = values
            path = f"/repos/{repo}/commits/{urllib.parse.quote(str(ref), safe='')}"
        elif endpoint == "pypi_metadata":
            (package,) = values
            return f"{PYPI_API}/pypi/{package}/json", JSON_LIMIT, "application/json"
        elif endpoint == "pypi_distribution":
            (url,) = values
            return str(url), ARTIFACT_LIMIT, "application/octet-stream"
        elif endpoint == "pypi_provenance":
            package, version, filename = values
            path = "/integrity/{}/{}/{}/provenance".format(
                urllib.parse.quote(str(package), safe=""),
                urllib.parse.quote(str(version), safe=""),
                urllib.parse.quote(str(filename), safe=""),
            )
            return f"{PYPI_API}{path}", JSON_LIMIT, "application/vnd.pypi.integrity.v1+json"
        else:
            raise ValueError(f"unsupported public endpoint: {endpoint!r}")
        return f"{GITHUB_API}{path}", JSON_LIMIT, json_accept

    def _normalize(self, query: _PublicQuery, data: Any) -> object:
        endpoint = query.endpoint
        if endpoint == "github_check_runs":
            if not isinstance(data, dict) or not isinstance(data.get("check_runs"), list):
                raise PublicReadError("unexpected check-runs response shape")
            if type(data.get("total_count")) is not int:
                raise PublicReadError("check-runs response has no integer total_count")
            for item in data["check_runs"]:
                if (
                    not isinstance(item, dict)
                    or not isinstance(item.get("name"), str)
                    or not isinstance(item.get("head_sha"), str)
                    or not _SHA.fullmatch(item["head_sha"])
                    or not isinstance(item.get("status"), str)
                ):
                    raise PublicReadError("check-runs response contains a malformed item")
            if data["total_count"] != len(data["check_runs"]):
                raise PublicReadError("check-runs response does not prove complete pagination")
            return data
        if endpoint == "github_workflow_runs":
            if (
                not isinstance(data, dict)
                or not isinstance(data.get("workflow_runs"), list)
                or type(data.get("total_count")) is not int
            ):
                raise PublicReadError("unexpected workflow-runs response shape")
            if data["total_count"] != len(data["workflow_runs"]):
                raise PublicReadError("workflow-runs response does not prove complete pagination")
            workflow = str(query.values[1])
            return [_workflow_run(item, workflow) for item in data["workflow_runs"]]
        if endpoint == "github_workflow_jobs":
            if (
                not isinstance(data, dict)
                or not isinstance(data.get("jobs"), list)
                or type(data.get("total_count")) is not int
            ):
                raise PublicReadError("unexpected workflow-jobs response shape")
            if data["total_count"] != len(data["jobs"]):
                raise PublicReadError("workflow-jobs response does not prove complete pagination")
            return {"jobs": [_workflow_job(item) for item in data["jobs"]]}
        if endpoint == "github_releases":
            if not isinstance(data, list):
                raise PublicReadError("unexpected releases response shape")
            return [_release(item) for item in data]
        if endpoint == "github_branch_rules":
            if not isinstance(data, list):
                raise PublicReadError("unexpected list response shape")
            if any(
                not isinstance(item, dict) or not isinstance(item.get("type"), str) for item in data
            ):
                raise PublicReadError("branch-rules response contains a malformed item")
            return data
        if endpoint == "github_rulesets":
            if not isinstance(data, list):
                raise PublicReadError("unexpected list response shape")
            if any(not isinstance(item, dict) or type(item.get("id")) is not int for item in data):
                raise PublicReadError("ruleset list contains a malformed item")
            return data
        if endpoint == "github_ruleset":
            if (
                not isinstance(data, dict)
                or type(data.get("id")) is not int
                or not isinstance(data.get("name"), str)
                or not isinstance(data.get("target"), str)
                or not isinstance(data.get("enforcement"), str)
                or not isinstance(data.get("conditions"), dict)
                or not isinstance(data.get("rules"), list)
            ):
                raise PublicReadError("unexpected ruleset response shape")
            return data
        if endpoint == "github_matching_tags":
            return _matching_tags(data)
        if endpoint in {"github_commit", "github_upstream_head"}:
            if (
                not isinstance(data, dict)
                or not isinstance(data.get("sha"), str)
                or not _SHA.fullmatch(data["sha"])
            ):
                raise PublicReadError("commit response carried no 40-hex SHA")
            return data["sha"].lower()
        if endpoint == "pypi_metadata":
            if (
                not isinstance(data, dict)
                or not isinstance(data.get("info"), dict)
                or not isinstance(data.get("releases"), dict)
            ):
                raise PublicReadError("unexpected PyPI metadata response shape")
            return data
        if endpoint == "pypi_provenance":
            if not isinstance(data, dict):
                raise PublicReadError("unexpected provenance response shape")
            return json.dumps(data, separators=(",", ":")).encode()
        raise ValueError(f"unsupported public endpoint: {endpoint!r}")


def _workflow_run(item: object, workflow: str) -> dict[str, object]:
    if not isinstance(item, dict):
        raise PublicReadError("workflow-runs list contains a non-object")
    required_strings = ("status", "event")
    if workflow == "Dependency Audit":
        required_strings += ("updated_at",)
    else:
        required_strings += ("head_branch", "head_sha", "created_at")
        if type(item.get("id")) is not int or not _SHA.fullmatch(str(item.get("head_sha", ""))):
            raise PublicReadError("workflow-runs response contains an invalid run identity")
    if any(not isinstance(item.get(name), str) for name in required_strings):
        raise PublicReadError("workflow-runs response contains a malformed item")
    mapping = {
        "status": "status",
        "conclusion": "conclusion",
        "head_branch": "headBranch",
        "head_sha": "headSha",
        "display_title": "displayTitle",
        "html_url": "url",
        "created_at": "createdAt",
        "event": "event",
        "id": "databaseId",
        "updated_at": "updatedAt",
    }
    return {target: item.get(source) for source, target in mapping.items()}


def _workflow_job(item: object) -> dict[str, object]:
    if not isinstance(item, dict):
        raise PublicReadError("workflow-jobs list contains a non-object")
    if (
        not isinstance(item.get("name"), str)
        or not isinstance(item.get("status"), str)
        or type(item.get("id")) is not int
    ):
        raise PublicReadError("workflow-jobs response contains a malformed item")
    return {
        "name": item.get("name"),
        "status": item.get("status"),
        "conclusion": item.get("conclusion"),
        "databaseId": item.get("id"),
    }


def _release(item: object) -> dict[str, object]:
    if not isinstance(item, dict):
        raise PublicReadError("releases list contains a non-object")
    if (
        not isinstance(item.get("tag_name"), str)
        or type(item.get("draft")) is not bool
        or type(item.get("prerelease")) is not bool
    ):
        raise PublicReadError("releases list contains a malformed item")
    return {
        "tagName": item.get("tag_name"),
        "isDraft": item.get("draft"),
        "isPrerelease": item.get("prerelease"),
        "isLatest": False,
        "publishedAt": item.get("published_at"),
    }


def _matching_tags(data: object) -> list[dict[str, str]]:
    if not isinstance(data, list):
        raise PublicReadError("unexpected matching-refs response shape")
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in data:
        if not isinstance(item, dict) or not isinstance(item.get("ref"), str):
            raise PublicReadError("matching-refs list contains a malformed item")
        ref = item["ref"]
        obj = item.get("object")
        if not ref.startswith("refs/tags/v") or ref in seen or not isinstance(obj, dict):
            raise PublicReadError("matching-refs response is ambiguous")
        sha = obj.get("sha")
        obj_type = obj.get("type")
        if not isinstance(sha, str) or not _SHA.fullmatch(sha) or obj_type not in {"commit", "tag"}:
            raise PublicReadError("matching ref has an invalid target")
        seen.add(ref)
        result.append({"ref": ref, "sha": sha.lower(), "type": obj_type})
    return result


def _diagnostic(error: BaseException) -> str:
    text = " ".join(str(error).split()) or error.__class__.__name__
    return text[:ERROR_LIMIT]


DEFAULT_READER = PublicReader()


def main(argv: list[str] | None = None) -> int:
    """Expose the two fixed public facts needed by release operators and agents."""
    parser = argparse.ArgumentParser(description="Read fixed public release evidence safely.")
    operation = parser.add_mutually_exclusive_group(required=True)
    operation.add_argument("--version-tags", action="store_true")
    operation.add_argument("--public-main-sha", action="store_true")
    args = parser.parse_args(argv)

    query = (
        matching_version_tags(PUBLIC_REPOSITORY)
        if args.version_tags
        else public_main(PUBLIC_REPOSITORY)
    )
    result = DEFAULT_READER(query)
    if result.error:
        print(f"release-public-read: ERROR — {result.error}", file=sys.stderr)
        return 1
    if args.version_tags:
        if not isinstance(result.data, list):
            print("release-public-read: ERROR — invalid tag evidence", file=sys.stderr)
            return 1
        tags = sorted(
            item["ref"].removeprefix("refs/tags/")
            for item in result.data
            if isinstance(item, dict) and isinstance(item.get("ref"), str)
        )
        print("\n".join(tags))
    elif isinstance(result.data, str):
        print(result.data)
    else:
        print("release-public-read: ERROR — invalid main evidence", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
