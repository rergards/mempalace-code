from __future__ import annotations

import importlib.util
import json
import sys
import urllib.error
from email.message import Message
from pathlib import Path

import pytest


def _load():
    name = "release_public_read_test"
    path = Path(__file__).parents[1] / "scripts" / "release_public_read.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


public = _load()


class Response:
    def __init__(
        self,
        body: bytes,
        url: str,
        *,
        length: str | None = None,
    ) -> None:
        self._body = body
        self._url = url
        self.headers = Message()
        if length is not None:
            self.headers["Content-Length"] = length

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def geturl(self) -> str:
        return self._url

    def read(self, limit: int) -> bytes:
        return self._body[:limit]


class Opener:
    def __init__(self, responses: list[bytes | Response | BaseException]) -> None:
        self.responses = list(responses)
        self.requests = []
        self.timeouts = []

    def open(self, request, timeout):
        self.requests.append(request)
        self.timeouts.append(timeout)
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        if isinstance(response, Response):
            return response
        return Response(response, request.full_url, length=str(len(response)))


def _json(value: object) -> bytes:
    return json.dumps(value).encode()


CHECK_RUN_ID = 99_722_321_144
EXPECTED_SHA = "a" * 40


def _check_run(**updates):
    value = {
        "id": CHECK_RUN_ID,
        "name": public.MINILM_CHECK_NAME,
        "status": "completed",
        "conclusion": "failure",
        "head_sha": EXPECTED_SHA,
        "html_url": "https://github.com/ignored",
    }
    value.update(updates)
    return value


def _annotation(**updates):
    value = {
        "annotation_level": "failure",
        "title": public.MINILM_ANNOTATION_TITLE,
        "message": "ERROR: MiniLM runtime cache is unavailable",
        "path": "ignored/path",
        "raw_details": "ignored details",
    }
    value.update(updates)
    return value


def test_check_runs_uses_one_bounded_credential_free_get():
    opener = Opener([_json({"total_count": 0, "check_runs": []})])
    reader = public.PublicReader(opener)
    result = reader(public.check_runs(public.PUBLIC_REPOSITORY, "a" * 40, "release-required", 100))

    assert result.data == {"total_count": 0, "check_runs": []}
    assert result.error == ""
    assert opener.timeouts == [public.TIMEOUT_SECONDS]
    request = opener.requests[0]
    assert request.get_method() == "GET"
    assert request.get_header("User-agent") == public.USER_AGENT
    assert request.get_header("Authorization") is None
    assert request.get_header("Cookie") is None


def test_check_run_annotations_binds_two_exact_sterile_gets():
    opener = Opener([_json(_check_run()), _json([_annotation()])])
    result = public.PublicReader(opener)(
        public.check_run_annotations(public.PUBLIC_REPOSITORY, CHECK_RUN_ID, EXPECTED_SHA)
    )

    assert result.error == ""
    assert result.data == {
        "expectedSha": EXPECTED_SHA,
        "checkRunId": CHECK_RUN_ID,
        "checkName": public.MINILM_CHECK_NAME,
        "annotationLevel": "failure",
        "title": public.MINILM_ANNOTATION_TITLE,
        "message": "ERROR: MiniLM runtime cache is unavailable",
    }
    assert opener.timeouts == [public.TIMEOUT_SECONDS, public.TIMEOUT_SECONDS]
    assert [request.full_url for request in opener.requests] == [
        f"{public.GITHUB_API}/repos/{public.PUBLIC_REPOSITORY}/check-runs/{CHECK_RUN_ID}",
        f"{public.GITHUB_API}/repos/{public.PUBLIC_REPOSITORY}/check-runs/{CHECK_RUN_ID}"
        "/annotations?per_page=100&page=1",
    ]
    for request in opener.requests:
        assert request.get_method() == "GET"
        assert request.get_header("Authorization") is None
        assert request.get_header("Cookie") is None


@pytest.mark.parametrize(
    "message",
    [
        "ERROR: MiniLM compatibility current_vector_norm failed",
        "ERROR: active mempalace-code distribution is not installed",
        "ERROR: installed MiniLM runtime is unavailable",
    ],
)
def test_check_run_annotation_accepts_every_compatibility_message_prefix(message):
    evidence = public._check_run_annotation_evidence(
        [_annotation(message=message)],
        check_run_id=CHECK_RUN_ID,
        expected_sha=EXPECTED_SHA,
    )

    assert evidence["message"] == message


@pytest.mark.parametrize("check_run_id", [0, -1, 10**12 + 1, True])
def test_check_run_annotation_invalid_id_is_rejected_before_requests(check_run_id):
    opener = Opener([])
    with pytest.raises(ValueError, match="invalid check run id"):
        public.check_run_annotations(public.PUBLIC_REPOSITORY, check_run_id, EXPECTED_SHA)
    assert opener.requests == []


@pytest.mark.parametrize("expected_sha", ["a" * 39, "g" * 40, "../" + "a" * 37])
def test_check_run_annotation_invalid_sha_is_rejected_before_requests(expected_sha):
    with pytest.raises(ValueError, match="SHA"):
        public.check_run_annotations(public.PUBLIC_REPOSITORY, CHECK_RUN_ID, expected_sha)


@pytest.mark.parametrize(
    "updates",
    [
        {"head_sha": "b" * 40},
        {"name": "installed-application (ubuntu-latest, 3.11, arm64)"},
        {"status": "in_progress"},
        {"conclusion": "success"},
    ],
)
def test_check_run_annotation_rejects_stale_name_or_state_before_second_get(updates):
    opener = Opener([_json(_check_run(**updates))])
    result = public.PublicReader(opener)(
        public.check_run_annotations(public.PUBLIC_REPOSITORY, CHECK_RUN_ID, EXPECTED_SHA)
    )

    assert result.data is None
    assert "does not match" in result.error
    assert len(opener.requests) == 1


@pytest.mark.parametrize(
    "annotations",
    [
        [],
        [_annotation(annotation_level="warning")],
        [_annotation(title="Other failure")],
        [_annotation(message="WARNING: another benchmark")],
        [_annotation(message="ERROR: ")],
        [_annotation(message="MiniLM compatibility failed")],
        [_annotation(), _annotation(message="ERROR: MiniLM second failure")],
        [_annotation(message="ERROR: MiniLM" + "x" * 628)],
    ],
)
def test_check_run_annotation_requires_one_bounded_exact_match(annotations):
    opener = Opener([_json(_check_run()), _json(annotations)])
    result = public.PublicReader(opener)(
        public.check_run_annotations(public.PUBLIC_REPOSITORY, CHECK_RUN_ID, EXPECTED_SHA)
    )

    assert result.data is None
    assert "exactly one" in result.error


def test_check_run_annotation_rejects_full_page_as_incomplete():
    opener = Opener([_json(_check_run()), _json([_annotation()] * 100)])
    result = public.PublicReader(opener)(
        public.check_run_annotations(public.PUBLIC_REPOSITORY, CHECK_RUN_ID, EXPECTED_SHA)
    )

    assert result.data is None
    assert "bounded pagination limit" in result.error


@pytest.mark.parametrize(
    ("first", "second", "error"),
    [
        ({"name": public.MINILM_CHECK_NAME}, [_annotation()], "malformed evidence"),
        (_check_run(head_sha=1), [_annotation()], "malformed evidence"),
        (_check_run(), {}, "unexpected annotation response shape"),
        (_check_run(), [{"title": public.MINILM_ANNOTATION_TITLE}], "malformed evidence"),
        (_check_run(), [_annotation(message=None)], "malformed evidence"),
    ],
)
def test_check_run_annotation_rejects_malformed_declared_fields(first, second, error):
    result = public.PublicReader(Opener([_json(first), _json(second)]))(
        public.check_run_annotations(public.PUBLIC_REPOSITORY, CHECK_RUN_ID, EXPECTED_SHA)
    )
    assert result.data is None
    assert error in result.error


@pytest.mark.parametrize("response_index", [0, 1])
def test_check_run_annotation_rejects_redirects_and_oversized_bodies(response_index):
    metadata_url = f"{public.GITHUB_API}/repos/{public.PUBLIC_REPOSITORY}/check-runs/{CHECK_RUN_ID}"
    annotation_url = metadata_url + "/annotations?per_page=100&page=1"
    good: list[bytes | Response | BaseException] = [
        _json(_check_run()),
        _json([_annotation()]),
    ]
    redirected = list(good)
    redirected[response_index] = Response(b"{}", "https://example.com/elsewhere", length="2")
    oversized = list(good)
    oversized[response_index] = Response(
        b"x" * (public.JSON_LIMIT + 1),
        metadata_url if response_index == 0 else annotation_url,
    )

    redirect_result = public.PublicReader(Opener(redirected))(
        public.check_run_annotations(public.PUBLIC_REPOSITORY, CHECK_RUN_ID, EXPECTED_SHA)
    )
    oversized_result = public.PublicReader(Opener(oversized))(
        public.check_run_annotations(public.PUBLIC_REPOSITORY, CHECK_RUN_ID, EXPECTED_SHA)
    )

    assert redirect_result.error == "redirects are forbidden"
    assert oversized_result.error == "response exceeds the endpoint size limit"


@pytest.mark.parametrize(
    ("factory", "args"),
    [
        (public.check_runs, ("other/repo", "a" * 40, "release-required", 100)),
        (public.check_run_annotations, ("other/repo", CHECK_RUN_ID, EXPECTED_SHA)),
        (public.check_runs, (public.PUBLIC_REPOSITORY, "../main", "release-required", 100)),
        (public.check_runs, (public.PUBLIC_REPOSITORY, "a" * 40, "other-check", 100)),
        (public.workflow_runs, (public.PUBLIC_REPOSITORY, "Unknown", 10)),
        (
            lambda repo, workflow, limit, branch: public.workflow_runs(
                repo, workflow, limit, branch=branch
            ),
            (public.PUBLIC_REPOSITORY, "Tests", 10, "feature"),
        ),
        (public.branch_rules, (public.PUBLIC_REPOSITORY, "../main")),
        (public.branch_rules, (public.PUBLIC_REPOSITORY, "feature")),
        (public.pypi_metadata, ("other-package",)),
        (public.reviewed_upstream_head, ("other/repo", "main")),
    ],
)
def test_unsupported_targets_are_rejected_before_a_request(factory, args):
    opener = Opener([])
    with pytest.raises(ValueError, match="unsupported|invalid|SHA"):
        factory(*args)
    assert opener.requests == []


@pytest.mark.parametrize(
    "url",
    [
        "http://files.pythonhosted.org/packages/a.whl",
        "https://user@files.pythonhosted.org/packages/a.whl",
        "https://files.pythonhosted.org:444/packages/a.whl",
        "https://example.com/packages/a.whl",
        "https://files.pythonhosted.org/packages/../a.whl",
        "https://files.pythonhosted.org/packages/%2e%2e/a.whl",
        "https://files.pythonhosted.org/packages/a.whl?token=x",
    ],
)
def test_distribution_url_rejects_alternate_or_ambiguous_targets(url):
    with pytest.raises(ValueError, match="unsupported PyPI distribution URL"):
        public.pypi_distribution(url)


def test_redirect_and_oversized_body_fail_closed_with_bounded_diagnostics():
    query = public.pypi_metadata(public.PUBLIC_PACKAGE)
    expected_url = f"{public.PYPI_API}/pypi/{public.PUBLIC_PACKAGE}/json"
    redirect = public.PublicReader(
        Opener([Response(b"{}", "https://example.com/elsewhere", length="2")])
    )(query)
    oversized = public.PublicReader(
        Opener([Response(b"x" * (public.JSON_LIMIT + 1), expected_url)])
    )(query)

    assert redirect.data is None
    assert redirect.error == "redirects are forbidden"
    assert oversized.data is None
    assert oversized.error == "response exceeds the endpoint size limit"
    assert len(oversized.error) <= public.ERROR_LIMIT


def test_declared_length_and_malformed_json_fail_closed():
    query = public.pypi_metadata(public.PUBLIC_PACKAGE)
    url = f"{public.PYPI_API}/pypi/{public.PUBLIC_PACKAGE}/json"
    incomplete = public.PublicReader(Opener([Response(b"{}", url, length="3")]))(query)
    malformed = public.PublicReader(Opener([Response(b"{", url, length="1")]))(query)

    assert incomplete.error == "response length does not match Content-Length"
    assert malformed.error == "response was not valid UTF-8 JSON"


def test_workflow_and_release_adapters_preserve_predicate_schema():
    workflow = {
        "total_count": 1,
        "workflow_runs": [
            {
                "status": "completed",
                "conclusion": "success",
                "head_branch": "main",
                "head_sha": "a" * 40,
                "display_title": "test",
                "html_url": "https://github.com/run",
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-01T00:01:00Z",
                "event": "push",
                "id": 42,
            }
        ],
    }
    releases = [{"tag_name": "v1.0.0", "draft": False, "prerelease": False}]
    latest = {"tag_name": "v1.0.0"}
    reader = public.PublicReader(Opener([_json(workflow), _json(releases), _json(latest)]))

    runs = reader(public.workflow_runs(public.PUBLIC_REPOSITORY, "Tests", 30)).data
    normalized_releases = reader(public.releases(public.PUBLIC_REPOSITORY, 20)).data

    assert runs == [
        {
            "status": "completed",
            "conclusion": "success",
            "headBranch": "main",
            "headSha": "a" * 40,
            "displayTitle": "test",
            "url": "https://github.com/run",
            "createdAt": "2026-01-01T00:00:00Z",
            "event": "push",
            "databaseId": 42,
            "updatedAt": "2026-01-01T00:01:00Z",
        }
    ]
    assert normalized_releases == [
        {
            "tagName": "v1.0.0",
            "isDraft": False,
            "isPrerelease": False,
            "isLatest": True,
            "publishedAt": None,
        }
    ]


def test_annotated_tag_is_peeled_to_a_commit_with_a_fixed_depth():
    tag_object = "a" * 40
    commit = "b" * 40
    refs = [{"ref": "refs/tags/v1.0.0", "object": {"sha": tag_object, "type": "tag"}}]
    peel = {"object": {"sha": commit, "type": "commit"}}
    reader = public.PublicReader(Opener([_json(refs), _json(peel)]))

    result = reader(public.matching_version_tags(public.PUBLIC_REPOSITORY))

    assert result.data == [{"ref": "refs/tags/v1.0.0", "sha": commit, "type": "commit"}]
    assert result.error == ""


def test_build_opener_contains_proxy_bypass_and_redirect_refusal():
    opener = public.build_opener()
    proxy_handlers = [
        handler
        for handler in opener.handlers
        if isinstance(handler, public.urllib.request.ProxyHandler)
    ]
    redirect_handlers = [
        handler for handler in opener.handlers if isinstance(handler, public._NoRedirect)
    ]

    assert proxy_handlers == []
    assert len(redirect_handlers) == 1
    handler_names = {type(handler).__name__ for handler in opener.handlers}
    assert not handler_names & {
        "HTTPBasicAuthHandler",
        "HTTPDigestAuthHandler",
        "ProxyBasicAuthHandler",
        "ProxyDigestAuthHandler",
        "HTTPCookieProcessor",
    }


def test_ambient_credential_and_proxy_traps_do_not_change_the_opener(monkeypatch):
    for name in (
        "GH_TOKEN",
        "GITHUB_TOKEN",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "NETRC",
        "GH_CONFIG_DIR",
        "SSH_AUTH_SOCK",
    ):
        monkeypatch.setenv(name, "must-not-be-observed")
    opener = public.build_opener()
    assert not [
        handler
        for handler in opener.handlers
        if isinstance(handler, public.urllib.request.ProxyHandler)
    ]


@pytest.mark.parametrize(
    ("query", "payload"),
    [
        (
            public.check_runs(public.PUBLIC_REPOSITORY, "a" * 40, "release-required", 100),
            {
                "total_count": 0,
                "check_runs": [
                    {
                        "name": "release-required",
                        "head_sha": "a" * 40,
                        "status": "completed",
                    }
                ],
            },
        ),
        (
            public.workflow_runs(public.PUBLIC_REPOSITORY, "Tests", 100),
            {
                "total_count": 0,
                "workflow_runs": [
                    {
                        "status": "completed",
                        "event": "push",
                        "head_branch": "main",
                        "head_sha": "a" * 40,
                        "created_at": "2026-01-01T00:00:00Z",
                        "id": 1,
                    }
                ],
            },
        ),
        (
            public.workflow_jobs(public.PUBLIC_REPOSITORY, 1),
            {
                "total_count": 0,
                "jobs": [{"name": "build", "status": "completed", "id": 1}],
            },
        ),
    ],
)
def test_counted_github_collections_require_exact_pagination_proof(query, payload):
    result = public.PublicReader(Opener([_json(payload)]))(query)
    assert result.data is None
    assert "complete pagination" in result.error


def test_matching_tag_rejects_non_commit_and_non_tag_objects():
    refs = [{"ref": "refs/tags/v1.0.0", "object": {"sha": "a" * 40, "type": "tree"}}]
    result = public.PublicReader(Opener([_json(refs)]))(
        public.matching_version_tags(public.PUBLIC_REPOSITORY)
    )
    assert result.data is None
    assert "invalid target" in result.error


def test_release_reader_fetches_overflow_entry_and_fails_closed():
    release = {"tag_name": "v1.0.0", "draft": False, "prerelease": False}
    opener = Opener([_json([release] * 100), _json([release] * 100)])
    result = public.PublicReader(opener)(public.releases(public.PUBLIC_REPOSITORY, 200))
    assert result.data is None
    assert "bounded pagination limit" in result.error
    assert len(opener.requests) == 2


@pytest.mark.parametrize(
    "failure",
    [
        urllib.error.HTTPError("https://redacted.invalid", 403, "forbidden", Message(), None),
        urllib.error.HTTPError("https://redacted.invalid", 429, "limited", Message(), None),
        TimeoutError("sensitive local detail"),
    ],
)
def test_transport_failures_are_sanitized_and_bounded(failure):
    result = public.PublicReader(Opener([failure]))(public.pypi_metadata(public.PUBLIC_PACKAGE))
    assert result.data is None
    assert len(result.error) <= public.ERROR_LIMIT
    assert "sensitive local detail" not in result.error


def test_cli_prints_fixed_version_tags(monkeypatch, capsys):
    monkeypatch.setattr(
        public,
        "DEFAULT_READER",
        lambda _query: public.PublicResult(
            data=[{"ref": "refs/tags/v1.2.3", "sha": "a" * 40, "type": "commit"}]
        ),
    )
    assert public.main(["--version-tags"]) == 0
    assert capsys.readouterr().out == "v1.2.3\n"


def test_cli_prints_deterministic_check_run_annotation_evidence(monkeypatch, capsys):
    opener = Opener([_json(_check_run()), _json([_annotation()])])
    monkeypatch.setattr(public, "DEFAULT_READER", public.PublicReader(opener))

    assert (
        public.main(
            [
                "--check-run-annotations",
                str(CHECK_RUN_ID),
                "--expect-sha",
                EXPECTED_SHA.upper(),
            ]
        )
        == 0
    )
    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out == (
        '{"annotationLevel":"failure","checkName":"installed-application '
        '(ubuntu-latest, 3.11, x64)","checkRunId":99722321144,'
        '"expectedSha":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",'
        '"message":"ERROR: MiniLM runtime cache is unavailable",'
        '"title":"MiniLM runtime compatibility"}\n'
    )


@pytest.mark.parametrize(
    "argv",
    [
        ["--check-run-annotations", "0", "--expect-sha", EXPECTED_SHA],
        ["--check-run-annotations", str(CHECK_RUN_ID), "--expect-sha", "bad"],
        ["--check-run-annotations", str(CHECK_RUN_ID)],
        ["--public-main-sha", "--expect-sha", EXPECTED_SHA],
    ],
)
def test_cli_rejects_invalid_annotation_arguments_without_request(monkeypatch, capsys, argv):
    opener = Opener([])
    monkeypatch.setattr(public, "DEFAULT_READER", public.PublicReader(opener))

    assert public.main(argv) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("release-public-read: ERROR — ")
    assert opener.requests == []


def test_public_query_exposes_no_superseded_command_compatibility():
    forbidden = {
        "fixture_arguments",
        "_map_gh",
        "_map_git",
        "gh",
        "git",
        "http",
        "__getitem__",
        "__iter__",
        "__contains__",
        "__len__",
    }
    assert forbidden.isdisjoint(public._PublicQuery.__dict__)
