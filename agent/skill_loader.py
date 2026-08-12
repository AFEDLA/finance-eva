import os
from pathlib import Path

class SkillLoader:
    def __init__(self, skills_dir: str):
        self.skills_dir = Path(skills_dir)

    def load_all(self) -> dict[str, str]:
        """Load semua SKILL.md dari folder skills."""
        skills = {}
        
        if not self.skills_dir.exists():
            print(f"[SkillLoader] Skills dir tidak ditemukan: {self.skills_dir}")
            return skills
        
        for skill_folder in self.skills_dir.iterdir():
            if not skill_folder.is_dir():
                continue
            
            skill_md = skill_folder / "SKILL.md"
            if not skill_md.exists():
                continue
            
            try:
                content = skill_md.read_text(encoding="utf-8")
                skill_name = skill_folder.name
                skills[skill_name] = content
                print(f"[SkillLoader] ✅ Loaded: {skill_name}")
            except Exception as e:
                print(f"[SkillLoader] ❌ Gagal load {skill_folder.name}: {e}")
        
        return skills

    def load_one(self, skill_name: str) -> str | None:
        """Load satu skill spesifik."""
        skill_md = self.skills_dir / skill_name / "SKILL.md"
        if skill_md.exists():
            return skill_md.read_text(encoding="utf-8")
        return None
