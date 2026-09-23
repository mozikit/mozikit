from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_windows_release_workflow_supports_reusable_prereleases_and_manifest():
    workflow = (ROOT / ".github" / "workflows" / "build_windows.yml").read_text(encoding="utf-8")

    assert "workflow_call:" in workflow
    assert "prerelease:" in workflow
    assert "target_commitish:" in workflow
    assert "scripts/generate_update_manifest.py" in workflow
    assert "--build-sequence" in workflow
    assert "update --status --json" in workflow
    assert "release/update-manifest.json" in workflow
    assert "submit_winget" not in workflow
    assert "WINGET_TOKEN" not in workflow


def test_nightly_workflow_is_dev_sha_gated_and_idempotent():
    workflow = (ROOT / ".github" / "workflows" / "nightly.yml").read_text(encoding="utf-8")

    assert 'ref: dev' in workflow
    assert "actions/workflows/test_windows.yml/runs?branch=dev&head_sha=" in workflow
    assert "git tag --list 'v*-nightly.*' --points-at" in workflow
    assert "v${base_version}-nightly.${date}.${short_sha}" in workflow
    assert "prerelease: true" in workflow


def test_windows_ci_runs_on_dev_for_nightly_gate():
    workflow = (ROOT / ".github" / "workflows" / "test_windows.yml").read_text(encoding="utf-8")

    assert "branches: [ dev ]" in workflow
    assert "python -m pytest -q" in workflow
