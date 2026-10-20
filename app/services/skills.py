"""冻结原生研究技能，以只读内存后端隔离项目文件与用户密钥。"""

import hashlib
import json
from copy import deepcopy
from pathlib import Path

from deepagents.backends import StateBackend
from deepagents.backends.utils import create_file_data


def freeze_skills():
    """任务创建时保存 Markdown 原文；恢复时不重新读取磁盘内容。"""
    root = Path(__file__).resolve().parents[1] / "skills"
    files = {"/skills/" + path.relative_to(root).as_posix(): path.read_text(encoding="utf-8")
             for path in sorted(root.rglob("*.md"))}
    payload = json.dumps(files, ensure_ascii=False, sort_keys=True)
    return {"hash": hashlib.sha256(payload.encode()).hexdigest(), "files": files}


class FrozenSkillBackend(StateBackend):
    """复用官方文件格式与目录发现，但只提供本次运行冻结的技能。"""

    def __init__(self, files):
        """创建独立内存副本，不访问工作目录和其他运行状态。"""
        self.files = {path: create_file_data(content) for path, content in files.items()}

    def _read_files(self):
        """原生 SkillsMiddleware 和 read_file 均从同一冻结副本读取。"""
        return deepcopy(self.files)

    def _send_files_update(self, update):
        """即使绕过工具过滤，后端仍禁止写入与删除。"""
        raise PermissionError("研究技能只读，请修改源文件后创建新任务")
