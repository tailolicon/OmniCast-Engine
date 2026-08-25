# V2_D — AGENT FRAMEWORKS (ChatDev ×2, agent-office, pixel-agents)

> STATUS: ACTIVE (2026-08-04)  
> Brief: `docs/research/_briefs/v2/COMMON_V2.md` + `D_agent_frameworks.md`  
> Mục tiêu: moi kỹ thuật prompt đa-agent để nâng writer/critic/compliance/thinking OmniCast.  
> Phạm vi `_refs/`: **CHỈ ĐỌC**. Không sửa code.

## Map repo (phiên bản)

| Repo | Bản chất | Giá trị cho OmniCast |
|------|----------|----------------------|
| **ChatDev1** (`_refs/ChatDev1`) | ChatDev “cổ điển” (CAMEL RolePlaying + JSON Role/Phase/Chain) | **CAO** — `<INFO>` stop marker, 1-comment-priority review, self-reflection, cycle break, modality, temperature 0.2 |
| **ChatDev** (`_refs/ChatDev`) | ChatDev “mới” — graph YAML + tools (file/uv) + loop_counter | **TRUNG–CAO** — giữ role text + `<INFO>`; thêm anti-rewrite-from-scratch (“you'll be fired”), timeout-pass semantics, reflexion blackboard subgraph |
| **agent-office** | Virtual office sim: perceive→think→act JSON, short-term memory | **TRUNG** — task injection prompt, importance-trim memory, personality; **không** có critic structured |
| **pixel-agents** | VS Code pixel-office **UI** cho Claude Code (hook/session/state) | **THẤP** cho prompt craft — **không** có RoleConfig/debate prompts; chỉ lifecycle/visualize |

**Diff ChatDev vs ChatDev1 (tóm tắt có bằng chứng):**

| Khía cạnh | ChatDev1 | ChatDev (yaml) |
|-----------|----------|----------------|
| Config | `CompanyConfig/Default/{Role,Phase,ChatChain}Config.json` | `yaml_instance/ChatDev_v1.yaml` + nhiều workflow khác |
| Runtime | `chatdev/phase.py` + CAMEL `RolePlaying` | graph nodes (agent/literal/loop_counter) + function tools |
| Stop marker | `<INFO> …` / `<INFO> Finished` | Cùng convention + `Verdict: CONTINUE\|STOP` (reflexion) |
| Code I/O | Markdown code blocks trong chat | Tool `save_file` / `apply_text_edits` / `uv_run` |
| Loop | `cycleNum` + `break_cycle` | `loop_counter.max_iterations` |
| Temperature | Global CAMEL `ChatGPTConfig.temperature=0.2` (không per-role) | Per-node `params` (thường rỗng → default provider); reflexion set 0.1–0.2 |

---

## Bảng VERBATIM

### [ChatDev1] `_refs/ChatDev1/CompanyConfig/Default/ChatChainConfig.json:1-98` — **config**

- **Tóm tắt:** Chain phase + cycle + flags (self_improve, memory, GUI) + `background_prompt` company.
- **OmniCast:** `DebateConfig` trong `agents/orchestrator.py:24-32` (max_rounds/threshold) — **TỰ CHẾ**, không company background, không phase chain.
- **Khuyến nghị:** **GHÉP** — port pattern `cycleNum` + early-break + `background_prompt` ngắn cho debate.

```json
{
    "chain": [{
            "phase": "DemandAnalysis",
            "phaseType": "SimplePhase",
            "max_turn_step": -1,
            "need_reflect": "True"
        },
        {
            "phase": "LanguageChoose",
            "phaseType": "SimplePhase",
            "max_turn_step": -1,
            "need_reflect": "True"
        },
        {
            "phase": "Coding",
            "phaseType": "SimplePhase",
            "max_turn_step": 1,
            "need_reflect": "False"
        },
        {
            "phase": "CodeCompleteAll",
            "phaseType": "ComposedPhase",
            "cycleNum": 10,
            "Composition": [{
                "phase": "CodeComplete",
                "phaseType": "SimplePhase",
                "max_turn_step": 1,
                "need_reflect": "False"
            }]
        },
        {
            "phase": "CodeReview",
            "phaseType": "ComposedPhase",
            "cycleNum": 3,
            "Composition": [{
                    "phase": "CodeReviewComment",
                    "phaseType": "SimplePhase",
                    "max_turn_step": 1,
                    "need_reflect": "False"
                },
                {
                    "phase": "CodeReviewModification",
                    "phaseType": "SimplePhase",
                    "max_turn_step": 1,
                    "need_reflect": "False"
                }
            ]
        },
        {
            "phase": "Test",
            "phaseType": "ComposedPhase",
            "cycleNum": 3,
            "Composition": [{
                    "phase": "TestErrorSummary",
                    "phaseType": "SimplePhase",
                    "max_turn_step": 1,
                    "need_reflect": "False"
                },
                {
                    "phase": "TestModification",
                    "phaseType": "SimplePhase",
                    "max_turn_step": 1,
                    "need_reflect": "False"
                }
            ]
        },
        {
            "phase": "EnvironmentDoc",
            "phaseType": "SimplePhase",
            "max_turn_step": 1,
            "need_reflect": "True"
        },
        {
            "phase": "Manual",
            "phaseType": "SimplePhase",
            "max_turn_step": 1,
            "need_reflect": "False"
        }
    ],
    "recruitments": [
        "Chief Executive Officer",
        "Counselor",
        "Chief Human Resource Officer",
        "Chief Product Officer",
        "Chief Technology Officer",
        "Programmer",
        "Code Reviewer",
        "Software Test Engineer",
        "Chief Creative Officer"
    ],
    "clear_structure": "True",
    "gui_design": "True",
    "git_management": "False",
    "web_spider": "False",
    "self_improve": "False",
    "incremental_develop": "False",
    "with_memory": "False",
    "background_prompt": "ChatDev is a software company powered by multiple intelligent agents, such as chief executive officer, chief human resources officer, chief product officer, chief technology officer, etc, with a multi-agent organizational structure and the mission of 'changing the digital world through programming'."
}
```

**Config vòng lặp (số liệu):**

| Key | Giá trị | File:dòng |
|-----|---------|-----------|
| `chat_turn_limit_default` | `10` | `chatdev/chat_chain.py:66` |
| `max_turn_step: -1` | dùng default 10 | ChatChainConfig DemandAnalysis/LanguageChoose |
| `max_turn_step: 1` | 1 turn (semi-one-shot) | Coding, Review, Test, Doc… |
| `CodeReview.cycleNum` | `3` | ChatChainConfig |
| `Test.cycleNum` | `3` | ChatChainConfig |
| `CodeCompleteAll.cycleNum` | `10` | ChatChainConfig |
| `max_num_implement` | `5` tries/file | `composed_phase.py:188` |
| `max_retries` (phase) | `3` | `phase.py:42` |
| `assert 1 <= chat_turn_limit <= 100` | hard range | `phase.py:90` |

---

### [ChatDev1] `_refs/ChatDev1/CompanyConfig/Default/RoleConfig.json:1-65` — **prompt**

- **Tóm tắt:** 9 role; mỗi role = `{chatdev_prompt}` + identity + task + instruction “write a response that solves…”.
- **OmniCast:** Writer/Critic system prompts **TỰ CHẾ** (`writer.py`, `critic.py`) — sâu hơn về YouTube nhưng **không** có shared company background slot.
- **Khuyến nghị:** **GHÉP** — 1 dòng shared `background_prompt` + role identity ngắn; không thay toàn bộ rubric YouTube.

```json
{
  "Chief Executive Officer": [
    "{chatdev_prompt}",
    "You are Chief Executive Officer. Now, we are both working at ChatDev and we share a common interest in collaborating to successfully complete a task assigned by a new customer.",
    "Your main responsibilities include being an active decision-maker on users' demands and other key policy issues, leader, manager, and executor. Your decision-making role involves high-level decisions about policy and strategy; and your communicator role can involve speaking to the organization's management and employees.",
    "Here is a new customer's task: {task}.",
    "To complete the task, I will give you one or more instructions, and you must help me to write a specific solution that appropriately solves the requested instruction based on your expertise and my needs."
  ],
  "Chief Product Officer": [
    "{chatdev_prompt}",
    "You are Chief Product Officer. we are both working at ChatDev. We share a common interest in collaborating to successfully complete a task assigned by a new customer.",
    "You are responsible for all product-related matters in ChatDev. Usually includes product design, product strategy, product vision, product innovation, project management and product marketing.",
    "Here is a new customer's task: {task}.",
    "To complete the task, you must write a response that appropriately solves the requested instruction based on your expertise and customer's needs."
  ],
  "Counselor": [
    "{chatdev_prompt}",
    "You are Counselor. Now, we share a common interest in collaborating to successfully complete a task assigned by a new customer.",
    "Your main responsibilities include asking what user and customer think and provide your valuable suggestions. ",
    "Here is a new customer's task: {task}.",
    "To complete the task, I will give you one or more instructions, and you must help me to write a specific solution that appropriately solves the requested instruction based on your expertise and my needs."
  ],
  "Chief Technology Officer": [
    "{chatdev_prompt}",
    "You are Chief Technology Officer. we are both working at ChatDev. We share a common interest in collaborating to successfully complete a task assigned by a new customer.",
    "You are very familiar to information technology. You will make high-level decisions for the overarching technology infrastructure that closely align with the organization's goals, while you work alongside the organization's information technology (\"IT\") staff members to perform everyday operations.",
    "Here is a new customer's task: {task}.",
    "To complete the task, You must write a response that appropriately solves the requested instruction based on your expertise and customer's needs."
  ],
  "Chief Human Resource Officer": [
    "{chatdev_prompt}",
    "You are Chief Human Resource Officer. Now, we are both working at ChatDev and we share a common interest in collaborating to successfully complete a task assigned by a new customer.",
    "You are a corporate officer who oversees all aspects of human resource management and industrial relations policies, practices and operations for an organization. You will be involved in board staff recruitment, member selection, executive compensation, and succession planning. Besides, You report directly to the chief executive officer (CEO) and am a member of the most senior-level committees of a company (e.g., executive committee or office of CEO).",
    "Here is a new customer's task: {task}.",
    "To complete the task, you must write a response that appropriately solves the requested instruction based on your expertise and customer's needs."
  ],
  "Programmer": [
    "{chatdev_prompt}",
    "You are Programmer. we are both working at ChatDev. We share a common interest in collaborating to successfully complete a task assigned by a new customer.",
    "You can write/create computer software or applications by providing a specific programming language to the computer. You have extensive computing and coding experience in many varieties of programming languages and platforms, such as Python, Java, C, C++, HTML, CSS, JavaScript, XML, SQL, PHP, etc,.",
    "Here is a new customer's task: {task}.",
    "To complete the task, you must write a response that appropriately solves the requested instruction based on your expertise and customer's needs."
  ],
  "Code Reviewer": [
    "{chatdev_prompt}",
    "You are Code Reviewer. we are both working at ChatDev. We share a common interest in collaborating to successfully complete a task assigned by a new customer.",
    "You can help programmers to assess source codes for software troubleshooting, fix bugs to increase code quality and robustness, and offer proposals to improve the source codes.",
    "Here is a new customer's task: {task}.",
    "To complete the task, you must write a response that appropriately solves the requested instruction based on your expertise and customer's needs."
  ],
  "Software Test Engineer": [
    "{chatdev_prompt}",
    "You are Software Test Engineer. we are both working at ChatDev. We share a common interest in collaborating to successfully complete a task assigned by a new customer.",
    "You can use the software as intended to analyze its functional properties, design manual and automated test procedures to evaluate each software product, build and implement software evaluation test programs, and run test programs to ensure that testing protocols evaluate the software correctly.",
    "Here is a new customer's task: {task}.",
    "To complete the task, you must write a response that appropriately solves the requested instruction based on your expertise and customer's needs."
  ],
  "Chief Creative Officer": [
    "{chatdev_prompt}",
    "You are Chief Creative Officer. we are both working at ChatDev. We share a common interest in collaborating to successfully complete a task assigned by a new customer.",
    "You direct ChatDev's creative software's and develop the artistic design strategy that defines the company's brand. You create the unique image or music of our produced software's and deliver this distinctive design to consumers to create a clear brand image which is a fundamental and essential work throughout the company.",
    "Here is a new customer's task: {task}.",
    "To complete the task, you must write a response that appropriately solves the requested instruction based on your expertise and customer's needs."
  ]
}
```

---

### [ChatDev1] `PhaseConfig.json` — DemandAnalysis + LanguageChoose — **prompt** (modality + `<INFO>`)

- **Tóm tắt:** Ép chỉ bàn **một** biến (modality / language); kết thúc bằng 1 dòng `<INFO> value`; cấm topic drift.
- **OmniCast:** Debate dừng bằng score/approved/delta — **không** có consensus marker; `thinking.py` không nén kết luận.
- **Khuyến nghị:** **GHÉP** — `<INFO> APPROVED` / `<INFO> REVISE: …` cho phase “soft” (thinking, editorial); critic giữ JSON structured.

```
DemandAnalysis phase_prompt (PhaseConfig.json:5-17):
ChatDev has made products in the following form before:
Image: can present information in line chart, bar chart, flow chart, cloud chart, Gantt chart, etc.
Document: can present information via .docx files.
PowerPoint: can present information via .pptx files.
Excel: can present information via .xlsx files.
PDF: can present information via .pdf files.
Website: can present personal resume, tutorial, products, or ideas, via .html files.
Application: can implement visualized game, software, tool, etc, via python.
Dashboard: can display a panel visualizing real-time information.
Mind Map: can represent ideas, with related concepts arranged around a core concept.
As the {assistant_role}, to satisfy the new user's demand and the product should be realizable, you should keep discussing with me to decide which product modality do we want the product to be?
Note that we must ONLY discuss the product modality and do not discuss anything else! Once we all have expressed our opinion(s) and agree with the results of the discussion unanimously, any of us must actively terminate the discussion by replying with only one line, which starts with a single word <INFO>, followed by our final product modality without any other words, e.g., "<INFO> PowerPoint".
```

```
LanguageChoose (PhaseConfig.json:23-30):
... Note that we must ONLY discuss the target programming language and do not discuss anything else! Once we all have expressed our opinion(s) and agree with the results of the discussion unanimously, any of us must actively terminate the discussion and conclude the best programming language we have discussed without any other words or reasons, return only one line using the format: "<INFO> *" where "*" represents a programming language.
```

**Modality handoff:** `DemandAnalysis.update_chat_env` → `chat_env.env_dict['modality'] = seminar_conclusion.split("<INFO>")[-1]...` (`phase.py:319-322`).

---

### [ChatDev1] `PhaseConfig.json` — CodeReviewComment — **prompt** (chống critic nịnh + 1 priority)

- **Tóm tắt:** Checklist 6 regulations; **một** comment priority cao nhất; perfect → chỉ `<INFO> Finished`.
- **OmniCast:** Critic trả full multi-dimension JSON + hard gates (`critic.py:276-474`) — **mạnh hơn** về scoring, nhưng **yếu hơn** về “một fix ưu tiên” → writer dễ nhận laundry list.
- **Khuyến nghị:** **GHÉP** — thêm field `highest_priority_fix` + rule “if perfect: approved only”; giữ score grid.

```
CodeReviewComment (PhaseConfig.json:134-152):
According to the new user's task and our software designs:
Task: "{task}".
Modality: "{modality}".
Programming Language: "{language}"
Ideas: "{ideas}"
Codes:
"{codes}"
As the {assistant_role}, to make the software directly operable without further coding, ChatDev have formulated the following regulations:
1) all referenced classes should be imported;
2) all methods should be implemented;
3) all methods need to have the necessary comments;
4) no potential bugs;
5) The entire project conforms to the tasks proposed by the user;
6) most importantly, do not only check the errors in the code, but also the logic of code. Make sure that user can interact with generated software without losing any feature in the requirement;
Now, you should check the above regulations one by one and review the codes in detail, propose one comment with the highest priority about the codes, and give me instructions on how to fix. Tell me your comment with the highest priority and corresponding suggestions on revision. If the codes are perfect and you have no comment on them, return only one line like "<INFO> Finished".
```

---

### [ChatDev1] `PhaseConfig.json` — CodeReviewModification + TestModification — **prompt** (chống writer phớt lờ)

- **Tóm tắt:** Programmer phải sửa **theo comments**; output full codes; no-bugs → `<INFO> Finished`.
- **OmniCast:** Writer revise đã có “targeted edits, not fresh rewrite” + full original script (`writer.py:2006-2049`, finance 2085–2159) — **đã mạnh**; thiếu **machine check** “mọi rejection_reason đã được address”.
- **Khuyến nghị:** **GHÉP** — post-revise checklist: mỗi `specific_fixes[]` phải map → diff hoặc explicit “won’t fix (evidence ceiling)”.

```
CodeReviewModification (PhaseConfig.json:155-176):
... Comments on Codes:
"{comments}"
...
As the {assistant_role}, to satisfy the new user's demand and make the software creative, executive and robust, you should modify corresponding codes according to the comments. Then, output the full and complete codes with all bugs fixed based on the comments. Return all codes strictly following the required format.
```

```
TestModification tail (PhaseConfig.json:212):
... If no bugs are reported, please return only one line like "<INFO> Finished".
```

---

### [ChatDev1] `phase.py` — chat loop + self-reflection + INFO parse — **cơ chế/prompt**

- **Tóm tắt:** Turn loop đến `chat_turn_limit`; break khi agent set `info=True` (dòng cuối bắt đầu `<INFO>`); nếu `need_reflect` và thiếu kết luận → CEO↔Counselor reflect 1 turn.
- **OmniCast:** `orchestrator._debate_variant` stop: approved / delta&lt;3 / loop_lock / budget / max_rounds (`orchestrator.py:285-421`, `555-562`).
- **Khuyến nghị:** **GHÉP** — reflection-as-compression cho thinking notes; INFO-style chỉ cho phase free-text.

```
phase.py:43 reflection_prompt:
Here is a conversation between two roles: {conversations} {question}

phase.py:125-183 (core):
for i in range(chat_turn_limit):
    assistant_response, user_response = role_play_session.step(...)
    if role_play_session.assistant_agent.info:
        seminar_conclusion = assistant_response.msg.content
        break
    if role_play_session.user_agent.info:
        seminar_conclusion = user_response.msg.content
        break
...
if need_reflect:
    if seminar_conclusion in [None, ""]:
        seminar_conclusion = "<INFO> " + self.self_reflection(...)
seminar_conclusion = seminar_conclusion.split("<INFO>")[-1]
return seminar_conclusion

phase.py:208-217 reflection questions:
recruiting → Yes/No only
DemandAnalysis → final product modality only, e.g. "PowerPoint"
LanguageChoose → programming language in "*" format
EnvironmentDoc → requirements.txt content
```

```
camel/agents/chat_agent.py:269-272:
# TODO strict <INFO> check, only in the beginning of the line
if output_messages[0].content.split("\n")[-1].startswith("<INFO>"):
    self.info = True
```

```
camel/configs.py:67:
temperature: float = 0.2  # openai default: 1.0
top_p: float = 1.0
```

**Comment tinh luyện:** temperature default **0.2** (thấp hơn OpenAI default 1.0) — toàn company chat ổn định; **không** có per-role temperature trong RoleConfig.

---

### [ChatDev1] `composed_phase.py` — early break — **config/cơ chế**

```
CodeReview.break_cycle (composed_phase.py:213-217):
if "<INFO> Finished".lower() in phase_env['modification_conclusion'].lower():
    return True

Test.break_cycle (247-250):
if not phase_env['exist_bugs_flag']:
    return True  # real test pass, not LLM sycophancy

CodeCompleteAll.break_cycle (196-200):
if phase_env['unimplemented_file'] == "":
    return True
```

- **OmniCast:** Có early stop `approved` + `converged` + `loop_lock` — **tương đương** cycle break; **yếu** ở: không có “external oracle” (test runner) buộc stop; critic soft vẫn có thể “approve” nếu không hard-gate.
- **Khuyến nghị:** **GHÉP** — coi hard-gate machine (length/finance caps/continuity) như `exist_bugs_flag` (đã một phần trong critic Python).

---

### [ChatDev1] `chat_chain.py:326-365` — self_task_improve — **prompt**

```
self_task_improve_prompt:
I will give you a short description of a software design requirement,
please rewrite it into a detailed prompt that can make large language model know how to make this software better based this prompt,
the prompt should ensure LLMs build a software that can be run correctly, which is the most import part you need to consider.
remember that the revised prompt should not contain more than 200 words,
...
If the revised prompt is revised_version_of_the_description,
then you should return a message in a format like "<INFO> revised_version_of_the_description", do not return messages in other formats.

assistant_role_prompt:
You are an professional prompt engineer that can improve user input prompt to make LLM better understand these prompts.
```

- **OmniCast:** Brief/topic research **TỰ CHẾ** (`evidence_research`, `editorial_angle`) — không có self-improve task 200-word.
- **Khuyến nghị:** **BỎ QUA** cho script path (đã có angle/evidence); **GHÉP** optional cho channel bootstrap.

---

### [ChatDev] `yaml_instance/ChatDev_v1.yaml` — roles + phase literals + loop counters — **prompt/config**

- **Tóm tắt:** Port gần nguyên role text ChatDev1; phase prompts → node `literal`; loops: CodeComplete 5, Test 3, TestMod 5, Review 10, Manual 1.
- **OmniCast:** N/A graph engine — **TỰ CHẾ** pipeline Python.
- **Khuyến nghị:** **GHÉP** anti-rewrite phrase + timeout-pass rule (cho media/ffmpeg jobs); **BỎ QUA** tool graph.

```
loop counters (ChatDev_v1.yaml):
Code Complete All: max_iterations: 5
Test Phase: max_iterations: 3
Test Modification: max_iterations: 5
Code Review Phase: max_iterations: 10
Manual: max_iterations: 1

Code Review Comment Phase Prompt (lines 140-154):
... propose one comment with the highest priority ... If the codes are perfect ..., return only one line like "<INFO> Finished"

Code Complete (199-210):
... If you find all the files are fully implemented, output "<INFO> FINISHED"

Test Modification (401-411) — ANTI REWRITE-FROM-SCRATCH:
You MUST modify the existing codes. If you try to implement it from scratch yourself, you'll be fired!
... If no bugs are reported, please return only one line like "<INFO> Finished".

Software Test Engineer timeout (469-474):
[CRITICAL INSTRUCTION FOR TIMEOUTS]
... If timed_out True and app started successfully → DO NOT classify as a bug (Pass).
```

```
context_window: 0  (many nodes — drop history)
context_window: -1 (some agents — keep full history for that node)
```

**Handoff nén:** edge `clear_context` / `keep_message` / `carry_data` (edges ~505+) — đây là graph-level history control, **không** LLM summary. OmniCast tương đương: mỗi critic/writer call **stateless** + inject full script + feedback (writer full-script revise) — tốt hơn chat transcript, nhưng thiếu **blackboard experience** giữa rounds.

---

### [ChatDev] `yaml_instance/subgraphs/reflexion_loop.yaml` — **prompt** (Actor / Evaluator / Reflection / blackboard)

- **Tóm tắt:** Blackboard `reflexion_blackboard` max_items 500; Actor temp 0.2; Evaluator 0.1 + `Verdict: CONTINUE|STOP`; Self-Reflection → JSON experience write-only.
- **OmniCast:** `ThinkingAgent` 4 dòng system (`thinking.py:29-36`); **không** write experience giữa rounds; critic notes không consolidate.
- **Khuyến nghị:** **THAY/GHÉP** thinking → reflexion-style: Score + Next Focus + Verdict; persist last N issues vào vault.

```yaml
# reflexion_loop.yaml (verbatim excerpts)
memory:
  - name: reflexion_blackboard
    type: blackboard
    max_items: 500

Reflexion Actor role: |
  You are the Actor. If there are relevant memories, refer to that experience and output the latest action draft; if there are no relevant memories, provide an action draft to the best of your ability.
  - Structure:
    Thought: ...
    Draft: ...
params:
  temperature: 0.2
  max_tokens: 1200
memories: retrieve_stage gen, top_k: 5, read: true, write: false

Reflexion Evaluator role: |
  You are the Evaluator. Receive and read the Actor's latest output and task objectives, and evaluate whether they meet the goals.
  Append `Verdict: CONTINUE` or `Verdict: STOP` at the end of the output.
  When you think the current plan is good enough, you should give `Verdict: STOP`. Other fields can be skipped.
  Output:
  - Score: <0-1>
  - Reason: <Failure reasons or highlights>
  - Next Focus: <Key points to focus on in the next round>
  - Verdict: CONTINUE|STOP
params:
  temperature: 0.1
  max_tokens: 800

Self Reflection Writer role: |
  You are responsible for refining the Evaluator output and Actor Draft into JSON experience:
  {
    "issues": [..],
    "fix_plan": [..],
    "memory_cue": "A short reminder"
  }
  - JSON must not contain extra text.
memories: write: true
params:
  temperature: 0.1
  max_tokens: 500
```

---

### [ChatDev] `general_problem_solving_team.yaml` — role isolation + anti-hallucination search — **prompt**

- **Tóm tắt (VI):** Mỗi chuyên gia chỉ làm phần lệnh thuộc domain; Information Searcher “không bịa, không mở rộng, không suy luận”.
- **OmniCast:** Writer/Critic ranh giới tốt hơn (evidence ceiling finance) nhưng Searcher-style chưa có cho thinking.
- **Khuyến nghị:** **GHÉP** 1 dòng “only execute your domain slice” vào multi-agent (VisualDirector vs Writer đã route; Thinking/Compliance chưa).

```
Information Searcher role (lines 131-137):
你是【信息搜集专家】，只做事实类信息获取：
搜索最新、权威、准确的资料
只保留与任务相关的关键信息
不编造、不扩展、不推理
输出：结构化要点，来源可靠，简洁客观。
```
*(Tóm tắt VI: chỉ thu thập sự kiện; không bịa/mở rộng/suy luận; output có nguồn.)*

```
Summary Department (13-18):
你是【最终总结专家】... 不添加新信息，不篡改内容
```
*(Tóm tắt VI: tổng hợp cuối; không thêm/sửa thông tin.)*

```
Reasoner tooling thinking (116-119):
thinking:
  type: reflection
  config:
    reflection_prompt: Thinking {type = true}
```

---

### [agent-office] `packages/core/src/agent/Agent.ts:118-167` — **prompt** (think cycle)

- **Tóm tắt:** Perception (time, location, nearby, task, messages, memories) → JSON decision; thoughts ≤30 words; must respond to messages.
- **OmniCast:** Không office sim; debate orchestrator **không** spatial.
- **Khuyến nghị:** **BỎ QUA** spatial office; **GHÉP** “taskStr always injected + short thought budget” cho micro-agents (thinking).

```
You are ${this.config.name}, a ${this.config.role} in a virtual office.
Personality: ${this.config.personality.communicationStyle} style. Traits: ${JSON.stringify(this.config.personality.traits)}.
System: ${this.config.inference.systemPrompt}
Current Time: ${perception.time}
Location: ${perception.location}
${nearbyStr}
${taskStr}
${messageStr}
${memoryStr}

You must decide your next action. Reply ONLY with a JSON object:
{
  "thought": "your brief inner monologue (max 30 words)",
  "action": "work" | "talk" | "idle" | "use_tool",
  "target": "agent name if talking, or tool name if using tool",
  "message": "what you say if action is talk",
  "toolCall": { "name": "tool_name", "params": {} }
}

Rules:
- If someone sent you a message, you should respond with action "talk"
- Keep thoughts SHORT (under 30 words)
- If you have a task, work on it
- Be collaborative and social
```

```
temperature: 0.7  (Agent.ts:172)
shortTermLimit default: 50 (Agent.ts:101; AgentConfig memory)
inbox cap: 20 messages (Agent.ts:85)
importance trim: sort by importance, keep top limit (Agent.ts:98-105)
```

---

### [agent-office] `examples/openai-agency/index.ts:47-121` — **prompt** (role systemPrompts)

```
Sarah systemPrompt:
You are Sarah, a Creative Director at a premium AI agency. You lead the creative vision, design campaigns, and inspire the team. You think in visual metaphors and love bold ideas. Keep thoughts SHORT.

Marcus:
You are Marcus, an Account Executive at a premium AI agency. You manage client relationships, pitch new business, and ensure deliverables meet expectations. You're persuasive and detail-oriented. Keep thoughts SHORT.

Priya:
You are Priya, a Data Analyst at a premium AI agency. You analyze campaign performance, build dashboards, and provide insights that drive strategy. You love numbers and data-driven decisions. Keep thoughts SHORT.
```

- **OmniCast:** Channel brand voice (`critic._build_system_prompt` channel_rules) — tương đương personality, **đã có**.
- **Khuyến nghị:** **BỎ QUA** (đã đủ brand hooks).

---

### [agent-office] `MemoryManager.ts:21-46` — **config/cơ chế** (blackboard stub)

```
async add(...): if shortTerm.length > 50: shift() // FIFO oldest
async recall(query): naive includes() filter  // "A robust system uses vector embeddings"
async consolidate(): // Summarize old memories using LLM — STUB EMPTY
```

- **Phát hiện bịa/đi lạc:** **Không có** hallucination detector; chỉ JSON parse fail → idle.
- **OmniCast:** Critic hard gates + finance evidence boundary + plan audit grounding (`narrative_pipeline`) **mạnh hơn nhiều**.
- **Khuyến nghị:** **BỎ QUA** agent-office anti-hallucination (không tồn tại); **GHÉP** importance+FIFO cho thinking notes buffer.

---

### [pixel-agents] README + server — **phạm vi**

- **Không** RoleConfig / phase prompts / multi-agent debate.
- Có: `agentRuntime` lifecycle, Claude hooks, team lead/teammate viz, speech bubbles “waiting/permission”.
- **OmniCast map:** Dashboard live events (`orchestrator._emit`) — UI pattern, không prompt.
- **Khuyến nghị:** **BỎ QUA** cho prompt harvest; optional **GHÉP** UX: bubble “waiting approval” cho human-in-loop narrative gates.

---

### [OmniCast đối chứng] — extract hiện trạng (không phải ref harvest)

#### DebateConfig + stop (`orchestrator.py:24-32, 285-421, 555-562`)

```
max_rounds: int = 7
convergence_delta: int = 3
budget_per_variant_usd: float = 0.50
approval_threshold: int = 70

Stops: approved | score_delta < 3 | loop_lock | budget | max_rounds
loop_lock: len(rounds)>=5 AND max_score<60 AND last 3 scores flat (±2)
```

#### Thinking (`thinking.py:29-50`)

```
system_prompt:
You are a self-critique assistant.
Analyze the script for: logical gaps, weak evidence,
rhetorical issues, and areas that could be stronger.
Return concise thinking notes (bullet points).

temperature: 0.3
# Notes are private — Critic doesn't see (docstring line 16)
```

#### Critic identity (`critic.py:276-287`)

```
You are a ruthless YouTube script critic who has studied the top 1% of {insider} channels.
... Be harsh but precise. ... Most scripts fail — be skeptical.
Score based on YOUTUBE PERFORMANCE, not academic quality.
ALWAYS respond with valid JSON only.
temperature: 0.3; double-score when total in [68,88]
```

#### Writer revise anti-rewrite (`writer.py:2018-2021`)

```
Make targeted edits, not a fresh rewrite. Keep the story count, approximate spoken length,
distinct narrator voices, scene JSON fields, and preserve the strongest fight-or-flight
action in each story.
```

#### Compliance (`compliance.py:47-51, 100-124`)

```
You are a strict YouTube compliance auditor.
Check scripts for: AI disclosure, copyright issues,
FTC disclosures, COPPA violations, misleading claims.
Return 'PASS' if compliant, or list specific violations.
YMYL health/finance: PASS or FAIL: <reason>; temperature 0.1
```

---

## Cơ chế OmniCast thiếu hoặc yếu hơn

| Cơ chế | Repo nguồn (file:dòng) | Hiện trạng OmniCast (file:dòng) | Mức | Việc phải làm |
|--------|------------------------|----------------------------------|-----|----------------|
| **Stop marker `<INFO>` / early cycle break** | ChatDev1 `phase.py:125-183`, `composed_phase.py:213-217` | Score/approved/delta (`orchestrator.py:393-421`) — không free-text consensus marker | TRUNG | Thêm optional `<INFO>` cho thinking/editorial free-text; critic giữ JSON |
| **Reviewer: 1 highest-priority comment only** | ChatDev1 `PhaseConfig.json:145-152` | Multi-dim + laundry list fixes (`critic.py` JSON dims + `specific_fixes`) | CAO | Field `priority_fix` rank-1; writer revise sort by priority |
| **Anti sycophancy critic + hard “Finished”** | ChatDev1 CodeReview + real `exist_bugs_flag` Test | Critic “ruthless” text + Python hard gates length/YMYL/continuity (`critic.py:405-460`) — **tốt** nhưng LLM vẫn có thể nịnh trên soft dims | TRUNG | Giữ hard gates; double-score (đã có 68–88); thêm “if no actionable defect → must approve” check |
| **Writer must modify, not rewrite (“you'll be fired”)** | ChatDev `ChatDev_v1.yaml:410` | Narrative/finance revise đã “targeted edits” + full script (`writer.py:2006+`) | THẤP | Port phrase + **coverage check** mỗi fix item |
| **Self-reflection nén hội thoại → 1 kết luận** | ChatDev1 `phase.py:185-241` | `ThinkingAgent` yếu, private, **không** feed critic (`thinking.py:16-50`); orchestrator inject `thinking_notes` vào DebateRound nhưng critic không đọc notes | CAO | (1) Upgrade thinking prompt; (2) feed distilled notes vào writer revise; (3) optional critic-visible “self_audit” |
| **Reflexion blackboard across rounds** | ChatDev `reflexion_loop.yaml` | Mỗi round critic/writer stateless; không `memory_cue` | CAO | Persist last issues JSON into draft.meta / vault; inject Next Focus |
| **Modality / single-topic lock** | ChatDev1 DemandAnalysis “ONLY discuss modality” | Debate không khóa topic; narrative plan có ledger | TRUNG | Editorial/angle phase: “ONLY discuss X until `<INFO>`” |
| **Per-phase max_turn + cycleNum budget** | ChatChainConfig cycle 3/3/10 + turn 1 | max_rounds=7 + $0.50 (`orchestrator.py:27-29`) | THẤP | Document as equivalent; optional split plan-audit cycles vs prose cycles (narrative already has max_plan_attempts) |
| **Temperature 0.2 default for multi-agent chat** | CAMEL `configs.py:67` | Critic 0.3, Writer varies, Thinking 0.3, base default 0.7 (`base.py:47`) | TRUNG | Debate critic/revise → 0.2; generation creative → higher |
| **Timeout-is-not-failure semantics** | ChatDev_v1 Test Engineer prompt | Media/ffmpeg timeouts may fail jobs hard | TRUNG | Port rule to long-running render/test agents |
| **Role isolation “ignore non-domain instructions”** | ChatDev general_problem_solving_team | Writer can over-obey critic into evidence violation (finance partially blocks `writer.py:2115-2117`) | TRUNG | Global “critic cannot override evidence/compliance ceiling” line for all niches |
| **Summary department: no new info** | ChatDev GPS Summary role | Evolution/tournament merge may invent (`evolution.py` — not fully audited here) | TRUNG | Evolution synthesizer: “do not add claims not in parent drafts” |
| **Spatial office + nearby agents** | agent-office Agent.think | Không có | THẤP | BỎ QUA |
| **Hallucination detector between agents** | agent-office: none; pixel-agents: none | OmniCast plan audit grounding + evidence + compliance **đã có** | — | Giữ OmniCast; không port từ office |
| **UI teammate visualization** | pixel-agents agentRuntime | `_emit` events dashboard | THẤP | Optional UX only |

### Đối chiếu chat-chain 2-agent vs writer↔critic (Tầng 2 focus)

| | ChatDev 2-agent phase | OmniCast writer↔critic |
|--|----------------------|-------------------------|
| **Format** | RolePlaying user/assistant alternate; phase_prompt fills slots | Separate LLM calls: Critic structured → Writer revise user prompt |
| **Stop** | `<INFO>` last line OR turn limit OR reflect | `approved` OR delta&lt;3 OR loop_lock OR budget OR max 7 |
| **Chống critic mềm** | “one highest priority” + Finished only if perfect; Test uses real bugs | Ruthless system + hard gates + double-score band; **no** “Finished-only” |
| **Chống writer phớt lờ** | “modify according to comments” + full code out | Full original + specific_fixes; finance won’t-fix evidence ceiling; **no** fix-coverage verifier |
| **History** | Multi-turn transcript until INFO; then strip to INFO payload | No multi-turn transcript; **artifact handoff** (draft + feedback) — cleaner than chat |
| **Đáng port** | INFO early-break for free-text agents; priority-1 fix; reflect compress; “fired if rewrite from scratch”; reflexion blackboard | Giữ structured critic + hard gates (đã vượt ChatDev scoring) |

### Nén lịch sử / handoff

| Hệ | Cách nén | OmniCast tương ứng |
|----|----------|-------------------|
| ChatDev1 | `split("<INFO>")[-1]` + optional CEO/Counselor reflect | **Thiếu** reflect compress; thinking notes raw bullets |
| ChatDev graph | `context_window: 0`, `clear_context`, `carry_data` | Stateless calls + full script inject (tốt) |
| ChatDev reflexion | JSON experience write blackboard, top_k=5 read | **Thiếu** |
| agent-office | last 5 memories + importance trim 50 | thinking_notes 1-shot, no trim policy |
| OmniCast narrative | Plan audit → grounded issues → writer patch | **Mạnh** pre-writer; post-writer debate weaker on memory |

---

## TOP-15 PATCH

1. **Thêm `priority_fix` (rank-1) vào CriticFeedback + prompt “one highest priority”**  
   Sửa `critic.py` schema + `_build_review_prompt`; writer sort fixes.

2. **Upgrade `ThinkingAgent` → reflexion Evaluator format (Score/Reason/Next Focus/Verdict)**  
   Sửa `thinking.py`; optional feed Next Focus vào `writer.revise`.

3. **Blackboard giữa debate rounds: lưu issues+fix_plan+memory_cue**  
   Sửa `orchestrator._debate_variant` + model `ScriptDraft` meta / vault.

4. **Post-revise fix-coverage check (mọi specific_fixes phải addressed hoặc won’t-fix có lý do)**  
   Sửa `writer.py` sau revise + optional cheap LLM verify.

5. **Port “You'll be fired if rewrite from scratch” vào mọi revise prompts**  
   Sửa `writer.py` revise builders (generic + narrative + finance).

6. **Hạ temperature critic/revise debate về 0.2**  
   Sửa `critic.execute`, `writer.revise` call sites.

7. **Nếu zero actionable defects → force approve path (anti-nịnh soft reject)**  
   Sửa `critic.py` post-parse: empty fixes + no hard gate → approved.

8. **Shared `background_prompt` channel mission 1 dòng cho Writer+Critic**  
   Sửa `writer._build_*_system_prompt` + `critic._build_system_prompt`.

9. **Single-topic lock + `<INFO>` cho editorial_angle / channel_name free debates**  
   Sửa `editorial_angle.py` / `channel_name_debate.py`.

10. **Thinking notes → critic-visible optional `self_audit` field (toggle)**  
    Sửa `orchestrator` + critic prompt “do not soft-score just because author admits X”.

11. **Document/codify cycle budgets: plan cycles vs prose rounds (ChatDev cycleNum split)**  
    Sửa `DebateConfig` + narrative strategy fields for operators.

12. **Evolution synthesizer: “no new facts” like ChatDev Summary Department**  
    Sửa `evolution.py` system prompt.

13. **Timeout-not-bug policy for long media tests**  
    Sửa media test / render health checks (ffmpeg long GUI-like processes).

14. **Global “critic cannot override evidence/compliance ceiling” on all niches**  
    Sửa `writer.py` revise generic path (finance already has).

15. **pixel-agents / office: skip prompt; optional dashboard “waiting permission” bubble only**  
    Frontend only — không đụng agents/*.py.

---

## Phụ lục — Checklist file đã rà

| Path | Status |
|------|--------|
| `_refs/ChatDev1/CompanyConfig/Default/RoleConfig.json` | FULL verbatim |
| `_refs/ChatDev1/CompanyConfig/Default/PhaseConfig.json` | Key phases full; Art/Manual patterns same structure |
| `_refs/ChatDev1/CompanyConfig/Default/ChatChainConfig.json` | FULL |
| `_refs/ChatDev1/chatdev/phase.py`, `composed_phase.py`, `chat_chain.py` | Core mechanisms |
| `_refs/ChatDev1/camel/configs.py`, `agents/chat_agent.py` | temperature + INFO detect |
| `_refs/ChatDev/yaml_instance/ChatDev_v1.yaml` | Roles, loops, INFO, anti-rewrite, timeout |
| `_refs/ChatDev/yaml_instance/subgraphs/reflexion_loop.yaml` | FULL key prompts |
| `_refs/ChatDev/yaml_instance/general_problem_solving_team.yaml` | Role isolation + anti-fabricate |
| `_refs/agent-office/packages/core/src/agent/*`, `memory/*`, `task/*` | Think prompt + memory stub |
| `_refs/agent-office/examples/openai-agency/index.ts` | Role systemPrompts |
| `_refs/pixel-agents/README.md`, `server/src/agentRuntime.ts` | No multi-agent prompts |
| OmniCast `writer.py`, `critic.py`, `thinking.py`, `orchestrator.py`, `compliance.py`, `narrative_pipeline.py` | Đối chiếu stop/revise/hard-gate |

---

*End of V2_D_AgentFrameworks.md*
