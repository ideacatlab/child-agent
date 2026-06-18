from agent.memory.blocks import BlockStore
from agent.memory.store import MemoryStore


def test_memory_seed_and_search(settings):
    mem = MemoryStore(settings)
    assert settings.identity_file.exists()
    mem.remember("The deploy command is `agent serve`.")
    mem.journal("tested the worker")
    hits = mem.search("deploy command")
    assert any("deploy" in line.lower() for _, line in hits)


def test_blocks(tmp_path):
    bs = BlockStore(tmp_path / "blocks.json")
    bs.append("current_task", "step one")
    bs.append("current_task", "step two")
    block = bs.get("current_task")
    assert "step one" in block.value and "step two" in block.value
    bs.replace("current_task", "step one", "STEP ONE")
    assert "STEP ONE" in bs.get("current_task").value
    rendered = bs.render()
    assert "current_task" in rendered

    # persistence
    bs2 = BlockStore(tmp_path / "blocks.json")
    assert "STEP ONE" in bs2.get("current_task").value
