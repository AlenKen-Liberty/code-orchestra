"""E2E integration tests for Gemini CLI.

These tests call the real Gemini CLI and verify it can actually create files.
Skip if GEMINI_E2E=0 or if gemini CLI is not available.
"""
import os
import shutil
import subprocess
import sys

import pytest

SKIP_MSG = "Set GEMINI_E2E=1 to run Gemini CLI integration tests"
GEMINI_BIN = shutil.which("gemini")
# Default to a model with better capacity availability
GEMINI_MODEL = os.environ.get("GEMINI_E2E_MODEL", "gemini-2.5-pro")


def should_skip() -> bool:
    if os.environ.get("GEMINI_E2E", "0") != "1":
        return True
    if not GEMINI_BIN:
        return True
    return False


@pytest.mark.skipif(should_skip(), reason=SKIP_MSG)
class TestGeminiCLIE2E:
    """End-to-end tests that invoke the real Gemini CLI."""

    def test_gemini_ping(self):
        """Layer 3: Gemini CLI can respond to a simple prompt."""
        result = subprocess.run(
            ["gemini", "-m", GEMINI_MODEL, "-p", "Reply with exactly: GEMINI_OK"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, f"Gemini CLI failed: {result.stderr}"
        assert "GEMINI_OK" in result.stdout

    def test_gemini_creates_file(self, tmp_path):
        """Layer 4: Gemini CLI with -y can create a file in a git repo."""
        # Init a git repo (Gemini CLI expects one)
        subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True)
        subprocess.run(
            ["git", "commit", "--allow-empty", "-m", "init"],
            cwd=str(tmp_path),
            capture_output=True,
        )

        result = subprocess.run(
            [
                "gemini",
                "-m", GEMINI_MODEL,
                "-y",  # CRITICAL: yolo mode for auto-approving file writes
                "-p",
                "Create a file called hello.py containing exactly:\n"
                "def greet():\n"
                "    return 'Hello from Gemini'\n",
            ],
            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(tmp_path),
        )
        assert result.returncode == 0, f"Gemini CLI failed: {result.stderr[:500]}"

        hello_py = tmp_path / "hello.py"
        assert hello_py.exists(), (
            f"Gemini CLI did not create hello.py. stdout={result.stdout[:300]}"
        )
        content = hello_py.read_text()
        assert "greet" in content, f"hello.py content unexpected: {content}"

    def test_gemini_without_yolo_cannot_write(self, tmp_path):
        """Verify that WITHOUT -y, Gemini CLI cannot write files.

        Without -y, Gemini loops trying unavailable tools and eventually
        times out.  We give it a short timeout and check no file was created.
        """
        subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True)
        subprocess.run(
            ["git", "commit", "--allow-empty", "-m", "init"],
            cwd=str(tmp_path),
            capture_output=True,
        )

        try:
            subprocess.run(
                [
                    "gemini",
                    "-m", GEMINI_MODEL,
                    # NO -y flag — intentionally omitted
                    "-p",
                    "Create a file called should_not_exist.py with print('hi')",
                ],
                capture_output=True,
                text=True,
                timeout=30,  # short timeout; it will loop and fail
                cwd=str(tmp_path),
            )
        except subprocess.TimeoutExpired:
            pass  # expected: without -y it loops trying unavailable write tools

        # Without -y, the file should NOT be created
        assert not (tmp_path / "should_not_exist.py").exists(), (
            "File was created without -y flag! Gemini CLI may have changed behavior."
        )
