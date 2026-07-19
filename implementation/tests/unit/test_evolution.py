from omnicast.agents.evolution import EvolutionAgent
from omnicast.config.niches import get_niche_config


def test_narrative_evolution_prompt_preserves_story_format_without_ctas():
    agent = EvolutionAgent.__new__(EvolutionAgent)

    prompt = agent._build_system_prompt(get_niche_config("psychology", "horror"))

    assert "first-person" in prompt.lower()
    assert "preserve the number of stories" in prompt.lower()
    assert "like cta" not in prompt.lower()
    assert "subscribe" not in prompt.lower()
    assert "data points" not in prompt.lower()
