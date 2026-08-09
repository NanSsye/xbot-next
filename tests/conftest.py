from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import pytest

os.environ["XBOT_LOAD_DOTENV"] = "false"

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for path in (str(SRC), str(ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)


@pytest.fixture(autouse=True)
def sandbox_plugin_dirs(monkeypatch, tmp_path):
    """加载 fixture 插件/Skill，避免真实 plugins/ 目录里的生产插件
    （如会连接真实网关的通道类插件）干扰测试。"""
    from xbot.plugins.manager import PluginManager
    from xbot.skills.manager import SkillManager

    fixtures = Path(__file__).resolve().parent / "fixtures"
    plugins_target = tmp_path / "plugins"
    skills_target = tmp_path / "skills"
    if fixtures.joinpath("plugins").is_dir():
        shutil.copytree(fixtures / "plugins", plugins_target)
    if fixtures.joinpath("skills").is_dir():
        shutil.copytree(fixtures / "skills", skills_target)

    original_plugin_load_all = PluginManager.load_all

    async def sandboxed_plugin_load_all(self):
        original_dir = self.config.directory
        self.config.directory = str(plugins_target)
        try:
            await original_plugin_load_all(self)
        finally:
            self.config.directory = original_dir

    original_skill_load_all = SkillManager.load_all

    async def sandboxed_skill_load_all(self):
        original_dir = self.config.directory
        self.config.directory = str(skills_target)
        try:
            await original_skill_load_all(self)
        finally:
            self.config.directory = original_dir

    monkeypatch.setattr(PluginManager, "load_all", sandboxed_plugin_load_all)
    monkeypatch.setattr(SkillManager, "load_all", sandboxed_skill_load_all)
