"""Semantic locators for the NotebookLM UI — meaning first, CSS last.

Order of resolution (GPT proposal §2, matches how the Flow provider survived
UI drift): accessibility role+name → multilingual text → aria-label/placeholder
→ CSS fallback. Obfuscated classes (.sc-xxxx, .mat-mdc-…) are never primary.
The browser is launched with locale en-US, but Vietnamese aliases stay for
recovery when Google ignores the locale hint.

Each entry is a list of (strategy, value) tried in order by
`browser_provider.find()`. Strategies: role:<role> (value = name regex),
text (value = text regex), css (value = css selector).
"""

from __future__ import annotations

SELECTORS: dict[str, list[tuple[str, str]]] = {
    "create_notebook": [
        ("role:button", r"(create|new notebook|tạo)"),
        ("text", r"(Create new|New notebook|Tạo sổ tay|Tạo notebook)"),
        ("css", "button[aria-label*='reate']"),
    ],
    "notebook_title_input": [
        ("role:textbox", r"(title|tiêu đề)"),
        ("css", "input[aria-label*='itle']"),
    ],
    "add_source": [
        ("role:button", r"(add source|thêm nguồn)"),
        ("text", r"(Add source|Thêm nguồn)"),
        ("css", "button[aria-label*='ource']"),
    ],
    "file_input": [
        ("css", "input[type=file]"),
    ],
    "upload_file_option": [
        ("text", r"(Upload|choose file|Tải.*lên|chọn tệp)"),
        ("role:button", r"(upload|tải lên)"),
    ],
    "chat_input": [
        ("role:textbox", r"(ask|question|nhập|hỏi)"),
        ("css", "textarea"),
        ("css", "[contenteditable=true]"),
    ],
    "send_button": [
        ("role:button", r"(send|submit|gửi)"),
        ("css", "button[aria-label*='end']"),
    ],
    "source_list_item": [
        ("css", "[role=listitem]"),
        ("css", "[data-testid*=source]"),
    ],
    "processing_indicator": [
        ("text", r"(processing|importing|đang xử lý|đang nhập)"),
        ("css", "[role=progressbar]"),
    ],
    "citation_chip": [
        ("css", "button[aria-label*='itation']"),
        ("role:button", r"^\d{1,3}$"),          # numbered chips
        ("css", "[class*='citation']"),          # last resort only
    ],
    "response_container": [
        ("css", "[data-testid*=response]"),
        ("css", "[role=article]"),
        ("css", "message-content, .message-content"),
    ],
    "signed_out_marker": [
        ("text", r"(Sign in|Đăng nhập|Use another account)"),
        ("css", "input[type=email]"),
    ],
}

# Actions the supervisor (Claude) may choose during self-heal. ANYTHING else —
# delete notebook/source, share, account/subscription changes, accepting new
# terms — is not merely discouraged: it has no implementation in the provider,
# so the allowlist is enforced by absence of code.
SUPERVISOR_ALLOWLIST = (
    "open_notebook", "create_notebook", "upload_sources", "open_source",
    "fill_prompt", "send_prompt", "read_response", "read_citations",
    "screenshot", "snapshot",
)
