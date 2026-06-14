"""Scripted, illustrative playback of an AgentSpace conductor session (used to record
docs/demo.svg). Faithful to the real output format; the figures are representative.
Regenerate the SVG:
    uvx --from termtosvg termtosvg docs/demo.svg -g 92x30 -t window_frame \
        -c "python scripts/demo.py"
"""
import sys, time

G="\033[32m"; B="\033[1m"; D="\033[2m"; C="\033[36m"; Y="\033[33m"; W="\033[37m"; R="\033[0m"

def w(s): sys.stdout.write(s); sys.stdout.flush()
def line(s="", d=0.25): w(s+"\n"); time.sleep(d)
def typ(s, d=0.028):
    for ch in s: w(ch); time.sleep(d)
    time.sleep(0.3)

BANNER = f"""{G}
     ||      ||
   +------------+
   |  [o]  [o]  |     A G E N T S P A C E
   |    ----    |     local agent runtime
   +------------+
     ||      ||{R}"""

for l in BANNER.split("\n"): line(l, 0.04)
line()
line(f"{D}root: ~/AgentSpace{R}", 0.2)
line("type a goal in plain English (the conductor routes it). commands start with / — try /list or /help.", 0.5)
line()

# the goal
w(f"{G}{B}agentspace>{R} ")
typ("research france's odds of winning the world cup and make a slide deck")
line("", 0.5)

# conductor orchestration (matches the real event feed)
line(f"{C}🧭 conductor: research france's odds of winning the world cup and make a slide deck{R}", 0.6)
line(f"{C}🧭 I'll research the odds, then build a deck.{R}", 0.5)
line(f"{C}🧭 discovering agents…{R}", 0.7)
line(f"{Y}  → web         ←  find France's odds of winning the next World Cup, with sources{R}", 0.6)
line(f"{D}      · [web] 🔧 web_search(query='France World Cup winning odds 2026'){R}", 0.7)
line(f"{D}      · [web] 🔧 http_fetch(url='https://oddschecker.com/…'){R}", 0.8)
line(f"{G}  ✓ web → France ~+450 (~18% implied) at major books; among the favorites.{R}", 0.7)
line(f"{Y}  → doc-writer  ←  make a slide deck on: France ~18% implied odds, key drivers…{R}", 0.6)
line(f"{D}      · [doc-writer] 🔧 write_tool(name='create_deck'){R}", 0.6)
line(f"{D}      · [doc-writer] ✎ pi: writing tools/generated/create_deck.py{R}", 0.8)
line(f"{D}      · [doc-writer] ⚙ reloaded tools — create_deck now available{R}", 0.6)
line(f"{D}      · [doc-writer] 🔧 create_deck(title='France — World Cup Odds', slides=6){R}", 0.8)
line(f"{G}  ✓ doc-writer → Wrote output/france_wc_odds.pptx (6 slides){R}", 0.8)
line()
line(f"{G}{B}conductor>{R} {W}Done — France sit around +450 (~18% implied) to win the next World Cup,{R}", 0.25)
line(f"{W}among the favorites. I built a 6-slide deck at output/france_wc_odds.pptx —{R}", 0.25)
line(f"{W}odds, key players, and risks, with sources cited.{R}", 0.8)
line()
w(f"{G}{B}agentspace>{R} ")
time.sleep(1.6)
