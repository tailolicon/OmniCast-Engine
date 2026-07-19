import asyncio
import json
import os
import sys

sys.path.insert(0, r"E:\Project\OmniCast Engine\implementation\src")

from omnicast.agents.channel_name_debate import ChannelNameDebateAgent, NameCandidate, _strip_json_fences
from omnicast.llm.client import LLMClient

async def main():
    flash = LLMClient(provider="deepseek", model="deepseek-v4-flash")
    chat = LLMClient(provider="deepseek", model="deepseek-v4-flash")
    
    agent = ChannelNameDebateAgent(flash_llm=flash, chat_llm=chat, yt_api_key=None)
    
    niche = {
        "niche_name": "Aged Pension Downsizing",
        "audience_description": "Australian retirees looking to downsize their homes",
        "pain_points": ["Fear of losing pension", "Stress of moving", "Tax implications"]
    }
    
    candidates = [
        NameCandidate(name="Downsize Authority", channel_id="downsize_authority", angle="authority", rationale="", audience_trust=0.0, memorability=0.0, searchability=0.0, differentiation=0.0, handle_available=None),
        NameCandidate(name="No Pension Surprises", channel_id="no_pension_surprises", angle="outcome", rationale="", audience_trust=0.0, memorability=0.0, searchability=0.0, differentiation=0.0, handle_available=None),
        NameCandidate(name="Aussie Downsizers", channel_id="aussie_downsizers", angle="community", rationale="", audience_trust=0.0, memorability=0.0, searchability=0.0, differentiation=0.0, handle_available=None),
        NameCandidate(name="Downsize Simply", channel_id="downsize_simply", angle="minimalism", rationale="", audience_trust=0.0, memorability=0.0, searchability=0.0, differentiation=0.0, handle_available=None),
        NameCandidate(name="Pension Puzzle Solved", channel_id="pension_puzzle_solved", angle="educational", rationale="", audience_trust=0.0, memorability=0.0, searchability=0.0, differentiation=0.0, handle_available=None),
        NameCandidate(name="Aussie Pension Navigator", channel_id="aussie_pension_navigator", angle="guide", rationale="", audience_trust=0.0, memorability=0.0, searchability=0.0, differentiation=0.0, handle_available=None)
    ]
    
    # Let's call flash directly with the same prompt to see RAW output
    import textwrap
    names_json = json.dumps([{"name": c.name, "angle": c.angle} for c in candidates], indent=2)
    prompt = textwrap.dedent(f"""
        You are a YouTube audience research expert scoring channel name candidates.

        TARGET AUDIENCE: {niche['audience_description']}
        CORE PAIN POINTS: {', '.join(niche['pain_points'])}
        NICHE: {niche['niche_name']}

        Score each name candidate on 4 dimensions (0-10 scale) for THIS SPECIFIC audience:

        - audience_trust: Does this name trigger trust from someone with THIS pain profile?
        - memorability: Easy to remember, say aloud, find by search 3 months later?
        - searchability: Contains keywords a person with these pain points would type?
        - differentiation: Clearly distinct from generic/existing channels in this space?

        CANDIDATES:
        {names_json}

        Return JSON array with same order, adding scores:
        [
          {{
            "name": "...",
            "audience_trust": 8.5,
            "memorability": 7.0,
            "searchability": 8.0,
            "differentiation": 7.5
          }}
        ]
    """).strip()

    print("Requesting LLM...")
    resp = await flash.complete(
        messages=[{"role": "user", "content": prompt}],
        system="You are a scoring expert. Respond in valid JSON only.",
        max_tokens=4000,
        temperature=0.2,
    )
    
    with open("test_output.txt", "w", encoding="utf-8") as f:
        f.write(resp.content)
    print("Wrote response to test_output.txt")
    
    print("Extracted JSON:")
    print(_strip_json_fences(resp.content))

if __name__ == "__main__":
    asyncio.run(main())
