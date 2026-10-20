"""从当前解释器导出本项目依赖闭包，排除 py12 中无关项目包。"""

import argparse
import importlib.metadata as metadata
import json
import subprocess
import sys
import tomllib
from pathlib import Path

from packaging.markers import default_environment
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name


def main():
    """验证每条适用版本约束；存在冲突时不生成看似可复现的锁文件。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="docs/acceptance/dependency-results.json")
    args = parser.parse_args()
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))["project"]
    root = (project["dependencies"] + project["optional-dependencies"]["dev"] +
            project["optional-dependencies"]["demo"])
    queue = [Requirement(value) for value in root]
    activated, versions, errors = {}, {}, []
    while queue:
        requirement = queue.pop()
        name = canonicalize_name(requirement.name)
        try:
            package = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            errors.append(f"{name}: not installed")
            continue
        if requirement.specifier and package.version not in requirement.specifier:
            errors.append(f"{name}=={package.version} violates {requirement.specifier}")
        contexts = {""} | set(requirement.extras)
        new_contexts = contexts - activated.get(name, set())
        if not new_contexts:
            continue
        activated.setdefault(name, set()).update(contexts)
        versions[name] = package.version
        for raw in package.requires or []:
            child = Requirement(raw)
            if child.marker is None or any(
                child.marker.evaluate({**default_environment(), "extra": extra})
                for extra in new_contexts
            ):
                queue.append(child)
    if errors:
        raise SystemExit("\n".join(sorted(set(errors))))
    text = "# Windows Python 3.12 project closure including dev and demo extras\n"
    text += "\n".join(f"{name}=={versions[name]}" for name in sorted(versions)) + "\n"
    Path("requirements.project.lock").write_text(text, encoding="utf-8")
    shared = subprocess.run([sys.executable, "-m", "pip", "check"], capture_output=True, text=True)
    Path(args.output).write_text(json.dumps({
        "scope": "本项目依赖闭包，包含 dev/demo extras，按当前 Windows Python 环境标记解析",
        "packages": len(versions), "constraints_passed": True,
        "shared_environment_pip_check": shared.stdout.splitlines() if shared.returncode else [],
        "action": "只检查本项目闭包约束，未修改共享环境中其他项目的包版本",
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"locked_packages": len(versions), "constraints_passed": True}))


if __name__ == "__main__":
    main()
