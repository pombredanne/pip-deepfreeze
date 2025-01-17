import subprocess
import sys
import textwrap

import pytest
from typer.testing import CliRunner

from pip_deepfreeze.__main__ import app
from pip_deepfreeze.pip import pip_freeze, pip_list
from pip_deepfreeze.sync import sync


def test_sync(virtualenv_python, testpkgs, tmp_path):
    (tmp_path / "requirements.txt.in").write_text(
        textwrap.dedent(
            f"""\
            --pre
            --no-index
            --find-links {testpkgs}
            pkga<1
            """
        )
    )
    (tmp_path / "setup.py").write_text(
        textwrap.dedent(
            """\
            from setuptools import setup

            setup(name="theproject", install_requires=["pkgb"])
            """
        )
    )
    (tmp_path / "setup.cfg").write_text("[metadata]\nname = theproject\n")  # for perf
    subprocess.check_call(
        [sys.executable, "-m", "pip_deepfreeze", "--python", virtualenv_python, "sync"],
        cwd=tmp_path,
    )
    assert (tmp_path / "requirements.txt").read_text() == textwrap.dedent(
        f"""\
        # frozen requirements generated by pip-deepfreeze
        --pre
        --no-index
        --find-links {testpkgs}
        pkga==0.0.0
        pkgb==0.0.0
        """
    )


def test_sync_no_in_req(virtualenv_python, tmp_path):
    (tmp_path / "setup.py").write_text(
        textwrap.dedent(
            """\
            from setuptools import setup

            setup(name="theproject")
            """
        )
    )
    (tmp_path / "setup.cfg").write_text("[metadata]\nname = theproject\n")  # for perf
    subprocess.check_call(
        [sys.executable, "-m", "pip_deepfreeze", "--python", virtualenv_python, "sync"],
        cwd=tmp_path,
    )
    assert (tmp_path / "requirements.txt").read_text() == textwrap.dedent(
        """\
        # frozen requirements generated by pip-deepfreeze
        """
    )


def test_python_not_found(tmp_path):
    runner = CliRunner()
    result = runner.invoke(app, ["--python", "this-is-not-a-python", "sync"])
    assert result.exit_code != 0
    assert "Python interpreter 'this-is-not-a-python' not found" in result.output


@pytest.fixture
def editable_foobar_path(tmp_path):
    setup_py = tmp_path / "setup.py"
    setup_py.write_text(
        textwrap.dedent(
            """
            from setuptools import setup

            setup(name="foobar", version="0.0.1")
            """
        )
    )
    (tmp_path / "setup.cfg").write_text("[metadata]\nname = foobar\n")  # for perf
    return tmp_path


def test_editable_default_install(virtualenv_python, editable_foobar_path):
    subprocess.check_call(
        [sys.executable, "-m", "pip_deepfreeze", "--python", virtualenv_python, "sync"],
        cwd=editable_foobar_path,
    )
    # installed editable by default
    assert "-e " in "\n".join(pip_freeze(virtualenv_python))


def test_sync_project_root(virtualenv_python, editable_foobar_path):
    sync(
        virtualenv_python,
        upgrade_all=False,
        to_upgrade=[],
        extras=[],
        uninstall_unneeded=False,
        project_root=editable_foobar_path,
    )
    assert (editable_foobar_path / "requirements.txt").exists()


def test_sync_uninstall(virtualenv_python, tmp_path, testpkgs):
    setup_py = tmp_path / "setup.py"
    setup_py.write_text(
        textwrap.dedent(
            """
            from setuptools import setup

            setup(name="foobar", version="0.0.1", install_requires=["pkga"])
            """
        )
    )
    (tmp_path / "setup.cfg").write_text("[metadata]\nname = foobar\n")  # for perf
    in_reqs = tmp_path / "requirements.txt.in"
    in_reqs.write_text(f"--no-index\n-f {testpkgs}")
    sync(
        virtualenv_python,
        upgrade_all=False,
        to_upgrade=[],
        extras=[],
        uninstall_unneeded=False,
        project_root=tmp_path,
    )
    assert "pkga==" in "\n".join(pip_freeze(virtualenv_python))
    # remove dependency on pkga
    setup_py.write_text(
        textwrap.dedent(
            """
            from setuptools import setup

            setup(name="foobar", version="0.0.1", install_requires=[])
            """
        )
    )
    # sync with uninstall=False, pkga remains
    sync(
        virtualenv_python,
        upgrade_all=False,
        to_upgrade=[],
        extras=[],
        uninstall_unneeded=False,
        project_root=tmp_path,
    )
    assert "pkga==" in "\n".join(pip_freeze(virtualenv_python))
    # sync with uninstall=True, pkga removed
    sync(
        virtualenv_python,
        upgrade_all=False,
        to_upgrade=[],
        extras=[],
        uninstall_unneeded=True,
        project_root=tmp_path,
    )
    assert "pkga==" not in "\n".join(pip_freeze(virtualenv_python))


@pytest.mark.xfail(reason="https://github.com/sbidoul/pip-deepfreeze/issues/24")
def test_sync_update_new_dep(virtualenv_python, testpkgs, tmp_path):
    """Test that a preinstalled dependency is updated when project is not installed
    before sync.

    This case may also happen when adding intermediate dependencies
    """
    subprocess.check_call(
        [
            virtualenv_python,
            "-m",
            "pip",
            "install",
            "--no-index",
            "-f",
            testpkgs,
            "pkgc==0.0.1",
        ]
    )
    assert "pkgc==0.0.1" in "\n".join(pip_freeze(virtualenv_python))
    (tmp_path / "setup.py").write_text(
        textwrap.dedent(
            """\
            from setuptools import setup
            setup(name="theproject", install_requires=["pkgc"])
            """
        )
    )
    (tmp_path / "setup.cfg").write_text("[metadata]\nname = theproject\n")  # for perf
    (tmp_path / "requirements.txt.in").write_text(
        textwrap.dedent(
            f"""\
            --no-index
            -f {testpkgs}
            """
        )
    )
    sync(
        virtualenv_python,
        upgrade_all=False,
        to_upgrade=["pkgc"],
        extras=[],
        uninstall_unneeded=False,
        project_root=tmp_path,
    )
    assert "pkgc==0.0.3" in "\n".join(pip_freeze(virtualenv_python))


@pytest.mark.xfail(reason="https://github.com/sbidoul/pip-deepfreeze/issues/24")
def test_sync_update_all_new_dep(virtualenv_python, testpkgs, tmp_path):
    """Test that a preinstalled dependency is updated when project is not installed
    before sync.

    This case may also happen when adding intermediate dependencies
    """
    subprocess.check_call(
        [
            virtualenv_python,
            "-m",
            "pip",
            "install",
            "--no-index",
            "-f",
            testpkgs,
            "pkgc==0.0.1",
        ]
    )
    assert "pkgc==0.0.1" in "\n".join(pip_freeze(virtualenv_python))
    (tmp_path / "setup.py").write_text(
        textwrap.dedent(
            """\
            from setuptools import setup
            setup(name="theproject", install_requires=["pkgc"])
            """
        )
    )
    (tmp_path / "setup.cfg").write_text("[metadata]\nname = theproject\n")  # for perf
    (tmp_path / "requirements.txt.in").write_text(
        textwrap.dedent(
            f"""\
            --no-index
            -f {testpkgs}
            """
        )
    )
    sync(
        virtualenv_python,
        upgrade_all=True,
        to_upgrade=[],
        extras=[],
        uninstall_unneeded=False,
        project_root=tmp_path,
    )
    assert "pkgc==0.0.3" in "\n".join(pip_freeze(virtualenv_python))


def test_sync_extras(virtualenv_python, testpkgs, tmp_path):
    (tmp_path / "setup.py").write_text(
        textwrap.dedent(
            """\
            from setuptools import setup
            setup(
                name="theproject",
                install_requires=["pkgb"],
                extras_require={
                    "c": ["pkgc"],
                },
            )
            """
        )
    )
    (tmp_path / "setup.cfg").write_text("[metadata]\nname = theproject\n")  # for perf
    (tmp_path / "requirements.txt.in").write_text(
        textwrap.dedent(
            f"""\
            --no-index
            -f {testpkgs}
            """
        )
    )
    sync(
        virtualenv_python,
        upgrade_all=False,
        to_upgrade=[],
        extras=["c"],
        uninstall_unneeded=False,
        project_root=tmp_path,
    )
    assert {"pkga", "pkgb", "pkgc"}.issubset(pip_list(virtualenv_python))
    requirements_txt = (tmp_path / "requirements.txt").read_text()
    assert "pkga==0.0.0\npkgb==0.0.0\n" in requirements_txt
    assert "pkgc" not in requirements_txt
    requirements_c_txt = (tmp_path / "requirements-c.txt").read_text()
    assert "pkga" not in requirements_c_txt
    assert "pkgb" not in requirements_c_txt
    assert "pkgc==0.0.3\n" in requirements_c_txt
    # now sync again with a different frozen extra dependency
    (tmp_path / "requirements-c.txt").write_text("pkgc==0.0.2")
    sync(
        virtualenv_python,
        upgrade_all=False,
        to_upgrade=[],
        extras=["c"],
        uninstall_unneeded=False,
        project_root=tmp_path,
    )
    assert {"pkga", "pkgb", "pkgc"}.issubset(pip_list(virtualenv_python))
    requirements_txt = (tmp_path / "requirements.txt").read_text()
    assert "pkga==0.0.0\npkgb==0.0.0\n" in requirements_txt
    assert "pkgc" not in requirements_txt
    requirements_c_txt = (tmp_path / "requirements-c.txt").read_text()
    assert "pkga" not in requirements_c_txt
    assert "pkgb" not in requirements_c_txt
    assert "pkgc==0.0.2\n" in requirements_c_txt
