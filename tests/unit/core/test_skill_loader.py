from xbot.skills.loader import SkillLoader


def test_skill_loader_accepts_top_level_manifest(tmp_path):
    skill_dir = tmp_path / "demo"
    skill_dir.mkdir()
    (skill_dir / "skill.toml").write_text(
        '''
name = "demo"
version = "0.1.0"
description = "Demo skill"
enabled = true

[tools]
required = ["skill.run"]
'''.strip(),
        encoding="utf-8",
    )

    manifest = SkillLoader().load_manifest(skill_dir)

    assert manifest.name == "demo"
    assert manifest.tools.required == ["skill.run"]


def test_skill_loader_accepts_wrapped_skill_manifest(tmp_path):
    skill_dir = tmp_path / "demo"
    skill_dir.mkdir()
    (skill_dir / "skill.toml").write_text(
        '''
[skill]
name = "demo"
version = "0.1.0"
description = "Demo skill"
entry = "demo.py"

[tools]
required = ["skill.run"]
'''.strip(),
        encoding="utf-8",
    )

    manifest = SkillLoader().load_manifest(skill_dir)

    assert manifest.name == "demo"
    assert manifest.version == "0.1.0"
    assert manifest.tools.required == ["skill.run"]
