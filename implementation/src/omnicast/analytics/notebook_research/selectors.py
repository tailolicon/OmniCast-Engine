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
        # Real UI 2026-07 (calibrated from live screenshot): the add-sources
        # dialog shows buttons "Upload files / Websites / Drive / Copied text".
        ("role:button", r"upload files?"),
        ("text", r"(Upload files|choose file|Tải.*lên|chọn tệp)"),
    ],
    "sources_dialog_marker": [
        ("text", r"(or drop your files|Upload files|thả tệp)"),
    ],
    "website_source_option": [
        # Dialog button "Websites" (carries the YouTube icon in the live UI).
        ("role:button", r"(websites?|youtube)"),
        ("text", r"(Websites|YouTube|Trang web)"),
    ],
    "url_input": [
        ("css", "input[type=url]"),
        ("role:textbox", r"(url|link|paste|dán)"),
        ("css", "input[placeholder*='http'], textarea[placeholder*='http']"),
        ("css", "textarea"),
    ],
    "url_submit": [
        ("role:button", r"(insert|add|submit|chèn|thêm)"),
        ("text", r"(Insert|Add|Chèn)"),
    ],
    "notebook_title_header": [
        ("text", r"(Untitled notebook|Sổ tay chưa có tiêu đề)"),
        ("css", "input[aria-label*='title'], input[aria-label*='Title']"),
    ],
    "chat_input": [
        # Calibrated across THREE live probes (2026-07-26). Two textareas
        # exist and BOTH contain "query"/"truy vấn" in their aria labels:
        #   chat      = aria "Query box"/"Hộp truy vấn",
        #               placeholder "Ask a question…"/"Đặt câu hỏi…"
        #   discovery = aria "Discover sources based on the inputted query"/
        #               "Khám phá nguồn…", formcontrolname=discoverSourcesQuery
        # A substring/first-match on "query" grabs the (often disabled)
        # discovery box → run 5 typed into it, run 7 click-timed-out on it.
        # Placeholder is the reliable discriminator; every fallback EXCLUDES
        # the discovery control explicitly.
        ("css", "textarea[placeholder*='Ask a question'], "
                "textarea[placeholder*='Đặt câu hỏi']"),
        ("role:textbox", r"^(query box|hộp truy vấn)$"),
        ("css", "textarea:not([formcontrolname='discoverSourcesQuery'])"
                ":not([aria-label*='Discover']):not([aria-label*='Khám phá'])"),
        ("css", "[contenteditable=true]"),
    ],
    "send_button": [
        ("role:button", r"(send|submit|gửi)"),
        ("css", "button[aria-label*='end'], button[aria-label*='ửi']"),
    ],
    "source_list_item": [
        ("css", "[role=listitem]"),
        ("css", "[data-testid*=source]"),
    ],
    "processing_indicator": [
        ("text", r"(processing|importing|đang xử lý|đang nhập|đang tải)"),
        ("css", "[role=progressbar]"),
    ],
    "citation_chip": [
        ("css", "button[aria-label*='itation']"),
        ("role:button", r"^\d{1,3}$"),          # numbered chips
        ("css", "[class*='citation']"),          # last resort only
    ],
    "response_container": [
        # DOM probe 2026-07-28: a .chat-message-pair holds TWO chat-message
        # nodes — .from-user-container (our question) and .to-user-container
        # (the answer). The old table named the PAIR "the current answer", so
        # every saved response artifact began with our own prompt, and the
        # source verifier read the question's own NO_TRANSCRIPT token as the
        # model's verdict ten times in a row.
        # `...inner-content` also excludes the card's action row
        # ("Save to note / copy_all / thumb_up"), which is chrome, not answer.
        ("css", ".to-user-message-inner-content"),
        ("css", ".to-user-container"),
        # Fallbacks, in known-bad order: these DO include the question, which
        # is why _strip_prompt_echo still runs on whatever comes back.
        ("css", ".chat-message-pair"),
        ("css", ".chat-panel-content"),
        ("css", "chat-panel"),
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
