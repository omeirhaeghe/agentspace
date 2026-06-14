"""Scripted, illustrative playback of an AgentSpace conductor session (used to record
docs/demo.svg). Faithful to the real output format; the figures are representative.
Regenerate the SVG:
    uvx --from termtosvg termtosvg docs/demo.svg -g 92x32 -t window_frame \
        -c "python scripts/demo.py"
"""
import sys, time

G="\033[32m"; B="\033[1m"; D="\033[2m"; C="\033[36m"; Y="\033[33m"; W="\033[37m"; R="\033[0m"

def w(s): sys.stdout.write(s); sys.stdout.flush()
def line(s="", d=0.25): w(s+"\n"); time.sleep(d)
def typ(s, d=0.026):
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
w(f"{G}{B}agentspace ❯{R} ")
typ("design a local-first notes app — write the PRD, then scaffold it")
line("", 0.5)

# conductor orchestration (matches the real event feed)
line(f"{C}🧭 conductor: design a local-first notes app — write the PRD, then scaffold it{R}", 0.6)
line(f"{C}🧭 I'll have tech-writer draft the PRD, then coder scaffold it.{R}", 0.5)
line(f"{C}🧭 discovering agents…{R}", 0.7)

line(f"{Y}  → tech-writer  ←  PRD for a local-first notes app (offline, on-device model){R}", 0.6)
line(f"{D}      · [tech-writer] 🔧 load_skill(prd){R}", 0.7)
line(f"{D}      · [tech-writer] ✎ following house template — Golden Test Cases, Local Model Reqs{R}", 0.8)
line(f"{D}      · [tech-writer] 🔧 write_file(notes-app-prd.md){R}", 0.7)
line(f"{G}  ✓ tech-writer → Wrote output/notes-app-prd.md (14 sections){R}", 0.7)

line(f"{Y}  → coder        ←  scaffold the app from output/notes-app-prd.md{R}", 0.6)
line(f"{D}      · [coder] 🔧 read_file(output/notes-app-prd.md){R}", 0.6)
line(f"{D}      · [coder] 🔧 write_file(notes/app.py){R}", 0.6)
line(f"{D}      · [coder] 🔧 write_file(notes/test_app.py){R}", 0.6)
line(f"{D}      · [coder] 🔧 python(pytest -q)  →  3 passed{R}", 0.8)
line(f"{G}  ✓ coder → Scaffolded notes/ — app.py, storage.py, tests green.{R}", 0.8)
line()
line(f"{G}{B}conductor ❯{R} {W}Done. PRD at output/notes-app-prd.md (incl. Golden Test Cases &{R}", 0.25)
line(f"{W}Local Model Requirements), plus a working scaffold in notes/ with passing tests.{R}", 0.8)
line()
w(f"{G}{B}agentspace ❯{R} ")
time.sleep(1.6)
