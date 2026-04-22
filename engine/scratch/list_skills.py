import os
from pathlib import Path
from dotenv import load_dotenv
from engine.skill_factory import SkillFactory

load_dotenv()

def list_skills():
    working_dir = Path(os.getcwd())
    skill_paths = [working_dir / "skills"]
    env_paths = os.getenv("SKILL_SCAN_PATHS", "")
    if env_paths:
        for p in env_paths.split(";"):
            path = Path(p.strip())
            if path.exists():
                skill_paths.append(path)
            else:
                print(f"⚠️ Path does not exist: {path}")
    
    print(f"Scanning paths: {skill_paths}")
    factory = SkillFactory(skill_paths)
    skills = factory.list_skills()
    
    print(f"\nTotal skills discovered: {len(skills)}")
    for skill in skills:
        print(f"- {skill['name']} ({skill['chars']} chars): {skill['description']}")

if __name__ == "__main__":
    list_skills()
