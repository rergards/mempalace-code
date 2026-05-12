"""Unit tests for detect_language() in miner.py."""

import shutil
import tempfile
from pathlib import Path

import pytest

from mempalace_code.miner import detect_language

# =============================================================================
# Extension-based detection
# =============================================================================


@pytest.mark.parametrize(
    "ext,expected",
    [
        (".py", "python"),
        (".js", "javascript"),
        (".jsx", "jsx"),
        (".ts", "typescript"),
        (".tsx", "tsx"),
        (".go", "go"),
        (".rs", "rust"),
        (".rb", "ruby"),
        (".java", "java"),
        (".sh", "shell"),
        (".sql", "sql"),
        (".md", "markdown"),
        (".txt", "text"),
        (".json", "json"),
        (".yaml", "yaml"),
        (".yml", "yaml"),
        (".toml", "toml"),
        (".html", "html"),
        (".css", "css"),
        (".csv", "csv"),
        (".c", "c"),
        (".h", "c"),
        (".cpp", "cpp"),
        (".hpp", "cpp"),
        (".cs", "csharp"),
        (".fs", "fsharp"),
        (".fsi", "fsharp"),
        (".vb", "vbnet"),
        (".php", "php"),
        (".csproj", "xml"),
        (".fsproj", "xml"),
        (".vbproj", "xml"),
        (".sln", "dotnet-solution"),
        (".xaml", "xaml"),
        (".scala", "scala"),
        (".sc", "scala"),
        (".dart", "dart"),
        (".lua", "lua"),
    ],
)
def test_extension_detection(ext, expected):
    filepath = Path(f"some/file{ext}")
    assert detect_language(filepath) == expected


def test_unknown_extension_returns_unknown():
    filepath = Path("some/file.xyz")
    assert detect_language(filepath) == "unknown"


def test_extensionless_no_shebang_returns_unknown():
    filepath = Path("some_extensionless_file")
    assert detect_language(filepath, "") == "unknown"


# =============================================================================
# Shebang fallback
# =============================================================================


@pytest.mark.parametrize(
    "shebang,expected",
    [
        ("#!/usr/bin/python", "python"),
        ("#!/usr/bin/python3", "python"),
        ("#!/usr/bin/python3.9", "python"),
        ("#!/usr/bin/env python3", "python"),
        ("#!/usr/bin/env python", "python"),
        ("#!/usr/bin/node", "javascript"),
        ("#!/usr/bin/env node", "javascript"),
        ("#!/usr/bin/nodejs", "javascript"),
        ("#!/usr/bin/env nodejs", "javascript"),
        ("#!/usr/bin/ruby", "ruby"),
        ("#!/usr/bin/env ruby", "ruby"),
        ("#!/bin/bash", "shell"),
        ("#!/bin/sh", "shell"),
        ("#!/bin/zsh", "shell"),
        ("#!/usr/bin/env bash", "shell"),
        ("#!/usr/bin/perl", "perl"),
        ("#!/usr/bin/env perl", "perl"),
    ],
)
def test_shebang_detection(shebang, expected):
    filepath = Path("script")  # no extension
    content = f"{shebang}\nsome content here\n"
    assert detect_language(filepath, content) == expected


def test_shebang_with_env_wrapper_python3():
    """#!/usr/bin/env python3 should be detected as python."""
    filepath = Path("run")
    content = "#!/usr/bin/env python3\nprint('hello')\n"
    assert detect_language(filepath, content) == "python"


def test_shebang_with_interpreter_flags():
    """Shebangs with flags after interpreter name should still detect correctly.

    Bug fixed in harden round-1: the previous parser used parts[-1] which
    resolved to the flag ('-u', '-O', etc.) rather than the interpreter.
    """
    cases = [
        ("#!/usr/bin/python3 -u", "python"),
        ("#!/usr/bin/python -O", "python"),
        ("#!/usr/bin/env python3 -O", "python"),
        ("#!/bin/bash -e", "shell"),
        ("#!/bin/sh -x", "shell"),
    ]
    for shebang, expected in cases:
        filepath = Path("script")
        content = f"{shebang}\nsome content\n"
        assert detect_language(filepath, content) == expected, f"Failed for: {shebang!r}"


def test_shebang_unknown_interpreter_returns_unknown():
    filepath = Path("run")
    content = "#!/usr/bin/awk -f\nsome content\n"
    assert detect_language(filepath, content) == "unknown"


def test_empty_content_no_extension_returns_unknown():
    filepath = Path("noext")
    assert detect_language(filepath, "") == "unknown"


# =============================================================================
# Extension takes precedence over shebang
# =============================================================================


def test_extension_wins_over_shebang():
    """When a file has a recognized extension, shebang is irrelevant."""
    filepath = Path("script.py")
    content = "#!/usr/bin/env node\nprint('python file with node shebang')\n"
    assert detect_language(filepath, content) == "python"


# =============================================================================
# DevOps / infrastructure — extension-based
# =============================================================================


@pytest.mark.parametrize(
    "filename,expected",
    [
        ("main.tf", "terraform"),
        ("terraform.tfvars", "terraform"),
        ("config.hcl", "hcl"),
        ("deployment.tpl", "gotemplate"),
        ("template.j2", "jinja2"),
        ("template.jinja2", "jinja2"),
        ("nginx.conf", "conf"),
        ("setup.cfg", "conf"),
        ("settings.ini", "ini"),
        ("rules.mk", "make"),
    ],
)
def test_devops_extension_detection(filename, expected):
    filepath = Path(filename)
    assert detect_language(filepath) == expected


# =============================================================================
# DevOps / infrastructure — filename-based (extensionless)
# =============================================================================


@pytest.mark.parametrize(
    "filename,expected",
    [
        ("Dockerfile", "dockerfile"),
        ("Containerfile", "dockerfile"),
        ("Makefile", "make"),
        ("GNUmakefile", "make"),
        ("Vagrantfile", "ruby"),
    ],
)
def test_devops_filename_detection(filename, expected):
    filepath = Path(filename)
    assert detect_language(filepath) == expected


def test_filename_detection_takes_precedence_over_shebang():
    """FILENAME_LANG_MAP must be checked before shebang for extensionless files."""
    filepath = Path("Dockerfile")
    content = "#!/bin/sh\nFROM ubuntu:22.04\n"
    assert detect_language(filepath, content) == "dockerfile"


# =============================================================================
# Kubernetes — content-based detection
# =============================================================================

_K8S_DEPLOYMENT = (
    "apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: nginx\nspec:\n  replicas: 1\n"
)

_PLAIN_YAML = "name: my-app\nreplicaCount: 1\nimage:\n  repository: nginx\n  tag: latest\n"


def test_k8s_yaml_content_returns_kubernetes():
    """A .yaml file with apiVersion+kind is detected as 'kubernetes'."""
    assert detect_language(Path("deploy.yaml"), _K8S_DEPLOYMENT) == "kubernetes"


def test_k8s_yml_extension_also_detected():
    """A .yml file with apiVersion+kind is also detected as 'kubernetes'."""
    assert detect_language(Path("deploy.yml"), _K8S_DEPLOYMENT) == "kubernetes"


def test_plain_yaml_without_k8s_fields_stays_yaml():
    """A .yaml file without apiVersion+kind stays 'yaml' (Helm values, etc.)."""
    assert detect_language(Path("values.yaml"), _PLAIN_YAML) == "yaml"


def test_k8s_detection_requires_both_fields():
    """Only apiVersion without kind (or vice versa) does not trigger K8s detection."""
    only_api = "apiVersion: v1\ndata:\n  key: value\n"
    only_kind = "kind: Deployment\nspec: {}\n"
    assert detect_language(Path("partial.yaml"), only_api) == "yaml"
    assert detect_language(Path("partial.yaml"), only_kind) == "yaml"


def test_k8s_detection_non_yaml_extension_unaffected():
    """A .json file is never detected as kubernetes regardless of content."""
    assert detect_language(Path("manifest.json"), _K8S_DEPLOYMENT) == "json"


# =============================================================================
# Helm — path-context detection (AC-1, AC-4)
# =============================================================================


def test_chart_yaml_detects_helm():
    """Chart.yaml is always detected as helm regardless of content or location."""
    tmpdir = tempfile.mkdtemp()
    try:
        chart_file = Path(tmpdir) / "Chart.yaml"
        chart_file.write_text("apiVersion: v2\nname: my-chart\nversion: 0.1.0\n", encoding="utf-8")
        assert detect_language(chart_file) == "helm"
    finally:
        shutil.rmtree(tmpdir)


def test_values_yaml_with_chart_root_detects_helm():
    """values.yaml next to Chart.yaml is detected as helm."""
    tmpdir = tempfile.mkdtemp()
    try:
        chart_root = Path(tmpdir)
        (chart_root / "Chart.yaml").write_text("apiVersion: v2\nname: my-chart\n", encoding="utf-8")
        values_file = chart_root / "values.yaml"
        values_file.write_text("replicaCount: 1\nimage:\n  repository: nginx\n", encoding="utf-8")
        assert detect_language(values_file) == "helm"
    finally:
        shutil.rmtree(tmpdir)


def test_template_yaml_with_chart_root_detects_helm():
    """A YAML file under templates/ with a sibling Chart.yaml is detected as helm."""
    tmpdir = tempfile.mkdtemp()
    try:
        chart_root = Path(tmpdir)
        (chart_root / "Chart.yaml").write_text("apiVersion: v2\nname: my-chart\n", encoding="utf-8")
        templates_dir = chart_root / "templates"
        templates_dir.mkdir()
        tpl_file = templates_dir / "deployment.yaml"
        tpl_file.write_text(
            "apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: {{ .Release.Name }}\n",
            encoding="utf-8",
        )
        assert detect_language(tpl_file) == "helm"
    finally:
        shutil.rmtree(tmpdir)


def test_tpl_file_in_templates_with_chart_root_detects_helm():
    """A .tpl file under templates/ with a sibling Chart.yaml is detected as helm."""
    tmpdir = tempfile.mkdtemp()
    try:
        chart_root = Path(tmpdir)
        (chart_root / "Chart.yaml").write_text("apiVersion: v2\nname: my-chart\n", encoding="utf-8")
        templates_dir = chart_root / "templates"
        templates_dir.mkdir()
        tpl_file = templates_dir / "_helpers.tpl"
        tpl_file.write_text(
            '{{- define "mychart.labels" -}}\napp: {{ .Chart.Name }}\n{{- end }}\n',
            encoding="utf-8",
        )
        assert detect_language(tpl_file) == "helm"
    finally:
        shutil.rmtree(tmpdir)


def test_non_chart_values_yaml_remains_yaml():
    """A values.yaml not next to a Chart.yaml stays language='yaml' (AC-4 guard)."""
    tmpdir = tempfile.mkdtemp()
    try:
        values_file = Path(tmpdir) / "values.yaml"
        values_file.write_text("replicaCount: 1\nimage:\n  repository: nginx\n", encoding="utf-8")
        # No Chart.yaml in the same directory
        assert detect_language(values_file) == "yaml"
    finally:
        shutil.rmtree(tmpdir)


def test_non_chart_kubernetes_yaml_still_detects_kubernetes():
    """A Kubernetes manifest not inside a Helm chart is still detected as kubernetes (AC-4 guard)."""
    tmpdir = tempfile.mkdtemp()
    try:
        deploy_file = Path(tmpdir) / "deploy.yaml"
        deploy_file.write_text(_K8S_DEPLOYMENT, encoding="utf-8")
        # No Chart.yaml → deploy.yaml is NOT a helm file, K8s detection applies
        assert detect_language(deploy_file, _K8S_DEPLOYMENT) == "kubernetes"
    finally:
        shutil.rmtree(tmpdir)


# =============================================================================
# Ansible — detection (AC-4 guards + positive cases)
# =============================================================================

_ANSIBLE_PLAYBOOK_CONTENT = """\
---
- name: Deploy web application
  hosts: webservers
  vars_files:
    - common_vars.yml
  roles:
    - web
  tasks:
    - name: Install nginx
      apt:
        name: nginx
        state: present
"""

_ANSIBLE_ROLE_TASKS_CONTENT = """\
---
- name: Install dependencies
  apt:
    name: "{{ item }}"
    state: present
  loop:
    - nginx
    - curl
"""

_ANSIBLE_INVENTORY_INI = """\
[webservers]
web1.example.com
web2.example.com

[dbservers]
db1.example.com
"""

_ANSIBLE_INVENTORY_YML = """\
all:
  hosts:
    web1.example.com:
    web2.example.com:
  children:
    webservers:
      hosts:
        web1.example.com:
"""


def test_ansible_playbook_yaml_detects_ansible():
    """A .yml file with Ansible playbook structure (list + hosts:) detects as 'ansible'."""
    filepath = Path("site.yml")
    assert detect_language(filepath, _ANSIBLE_PLAYBOOK_CONTENT) == "ansible"


def test_ansible_playbook_yaml_ext_also_detects():
    """A .yaml file with Ansible playbook structure detects as 'ansible'."""
    filepath = Path("site.yaml")
    assert detect_language(filepath, _ANSIBLE_PLAYBOOK_CONTENT) == "ansible"


def test_ansible_role_tasks_file_detects_ansible():
    """A YAML file under roles/<name>/tasks/ detects as 'ansible' from path context."""
    tmpdir = tempfile.mkdtemp()
    try:
        tasks_file = Path(tmpdir) / "roles" / "web" / "tasks" / "main.yml"
        tasks_file.parent.mkdir(parents=True)
        tasks_file.write_text(_ANSIBLE_ROLE_TASKS_CONTENT, encoding="utf-8")
        assert detect_language(tasks_file, _ANSIBLE_ROLE_TASKS_CONTENT) == "ansible"
    finally:
        shutil.rmtree(tmpdir)


def test_ansible_role_handlers_file_detects_ansible():
    """A YAML file under roles/<name>/handlers/ detects as 'ansible' from path context."""
    tmpdir = tempfile.mkdtemp()
    try:
        handlers_file = Path(tmpdir) / "roles" / "web" / "handlers" / "main.yml"
        handlers_file.parent.mkdir(parents=True)
        handlers_file.write_text(
            "---\n- name: Restart nginx\n  service:\n    name: nginx\n    state: restarted\n",
            encoding="utf-8",
        )
        assert detect_language(handlers_file) == "ansible"
    finally:
        shutil.rmtree(tmpdir)


def test_ansible_role_vars_file_detects_ansible():
    """A YAML file under roles/<name>/vars/ detects as 'ansible' from path context."""
    tmpdir = tempfile.mkdtemp()
    try:
        vars_file = Path(tmpdir) / "roles" / "web" / "vars" / "main.yml"
        vars_file.parent.mkdir(parents=True)
        vars_file.write_text("nginx_port: 80\nnginx_user: www-data\n", encoding="utf-8")
        assert detect_language(vars_file) == "ansible"
    finally:
        shutil.rmtree(tmpdir)


def test_ansible_role_defaults_file_detects_ansible():
    """A YAML file under roles/<name>/defaults/ detects as 'ansible' from path context."""
    tmpdir = tempfile.mkdtemp()
    try:
        defaults_file = Path(tmpdir) / "roles" / "web" / "defaults" / "main.yml"
        defaults_file.parent.mkdir(parents=True)
        defaults_file.write_text("nginx_port: 80\n", encoding="utf-8")
        assert detect_language(defaults_file) == "ansible"
    finally:
        shutil.rmtree(tmpdir)


def test_ansible_inventory_ini_detects_ansible():
    """inventory.ini detects as 'ansible' via conservative inventory filename match."""
    filepath = Path("inventory.ini")
    assert detect_language(filepath, _ANSIBLE_INVENTORY_INI) == "ansible"


def test_ansible_inventory_yml_detects_ansible():
    """inventory.yml detects as 'ansible' via conservative inventory filename match."""
    filepath = Path("inventory.yml")
    assert detect_language(filepath, _ANSIBLE_INVENTORY_YML) == "ansible"


def test_ansible_inventory_yaml_detects_ansible():
    """inventory.yaml detects as 'ansible' via conservative inventory filename match."""
    filepath = Path("inventory.yaml")
    assert detect_language(filepath, _ANSIBLE_INVENTORY_YML) == "ansible"


def test_plain_yaml_without_ansible_stays_yaml():
    """A .yaml file with a mapping at the top level (no list, no hosts:) stays 'yaml' (AC-4 guard)."""
    filepath = Path("config.yaml")
    content = "name: my-app\nreplicaCount: 1\nimage:\n  repository: nginx\n  tag: latest\n"
    assert detect_language(filepath, content) == "yaml"


def test_yaml_list_without_hosts_stays_yaml():
    """A YAML list without hosts: key does NOT detect as ansible (RISK-1 guard)."""
    filepath = Path("items.yaml")
    content = "- name: item1\n  value: a\n- name: item2\n  value: b\n"
    assert detect_language(filepath, content) == "yaml"


def test_non_ansible_kubernetes_yaml_still_detects_kubernetes():
    """A Kubernetes manifest does not misdetect as ansible (AC-4 guard, no hosts: in play sense)."""
    filepath = Path("deploy.yaml")
    assert detect_language(filepath, _K8S_DEPLOYMENT) == "kubernetes"


def test_helm_chart_detection_still_precedes_ansible():
    """Helm chart-context files detect as 'helm' even when content has playbook-like structure (AC-4 guard)."""
    tmpdir = tempfile.mkdtemp()
    try:
        chart_root = Path(tmpdir)
        (chart_root / "Chart.yaml").write_text(
            "apiVersion: v2\nname: my-chart\nversion: 0.1.0\n", encoding="utf-8"
        )
        # values.yaml next to Chart.yaml → helm, not ansible
        values_file = chart_root / "values.yaml"
        values_file.write_text(_ANSIBLE_PLAYBOOK_CONTENT, encoding="utf-8")
        assert detect_language(values_file, _ANSIBLE_PLAYBOOK_CONTENT) == "helm"
    finally:
        shutil.rmtree(tmpdir)


def test_non_inventory_ini_stays_ini():
    """A .ini file NOT named inventory.* stays 'ini' (no over-detection)."""
    filepath = Path("settings.ini")
    assert detect_language(filepath, "[section]\nkey=value\n") == "ini"


def test_non_inventory_yaml_with_host_key_stays_yaml():
    """A .yaml file with a 'hosts:' key but no top-level list structure stays 'yaml'."""
    filepath = Path("config.yaml")
    content = "hosts:\n  - web1\n  - web2\n"
    assert detect_language(filepath, content) == "yaml"
