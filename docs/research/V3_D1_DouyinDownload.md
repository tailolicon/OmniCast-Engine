# V3_D1 — Douyin/TikTok download layer: full mechanism + config extraction

Working root: `_refs/`. Report harvest only. No invention.

## 0. TL;DR — what to port, ranked

| Rank | Capability | Primary source | License | Port? |
|------|------------|----------------|---------|-------|
| 1 | `a_bogus` pure-Python signer + X-Bogus fallback | `douyin-downloader` (`utils/abogus.py`, `utils/xbogus.py`, `core/api_client.py`) | MIT | Yes — copy/adapt |
| 2 | No-watermark URL selection + original-quality probe | `douyin-downloader` (`core/downloader_base.py`) | MIT | Yes |
| 3 | Endpoint catalog + default query params | `douyin-downloader` + `f2` + `Douyin_TikTok_Download_API` | MIT / Apache-2.0 | Yes (retype) |
| 4 | msToken real-fetch + false fallback, ttwid register | `f2` / `douyin-downloader` MsTokenManager | Apache / MIT | Yes |
| 5 | verifyFp / s_v_web_id local generator | all four (same algorithm) | varies | Clean-room or MIT |
| 6 | Gallery / live-photo / quality tiers | `douyin-downloader` | MIT | Yes |
| 7 | Hybrid playwm→play rewrite (legacy) | `Douyin_TikTok_Download_API` hybrid_crawler | Apache-2.0 | Optional fallback |
| — | Full product CLI/monitor/DB of JoeanAmier stack | `TikTokDownloader` | **GPL-3.0** | **Describe-only. Do not copy source.** |

**Primary library to embed:** `douyin-downloader` (MIT, git tip `2026-08-07`, pure Python + `gmssl`, async aiohttp, library-shaped `DouyinAPIClient` / `BaseDownloader`).

**Fallback:** `f2` Apache-2.0 async library (`f2.apps.douyin.*`) for alternate signer (`ABogusManager`) and broader app surface; attribution + NOTICE required. Do **not** vendor `TikTokDownloader` source (GPL-3.0).

Maintenance recency (git last commit visible in checkout):
- `douyin-downloader`: `2026-08-07` — most recent
- `TikTokDownloader`: `2026-08-07` (GPL; v5.8 in pyproject)
- `f2`: `2025-10-12`; CHANGELOG version `0.0.1.7` dated `2024-12-31`
- `Douyin_TikTok_Download_API`: `2025-10-12`; root `config.yaml` claims `Version: V4.1.2` / `Update_Time: 2025/03/16`

Most current **signature implementation to copy under OmniCast license constraints:** `douyin-downloader` (MIT, abogus+xbogus, UA pool Chrome/139, empty-200 anti-bot retry). GPL repo is newer in some encrypt modules but not copyable.

---

## 1. Repo A — Douyin_TikTok_Download_API (Apache-2.0)

### 1.A Anti-bot signature

**Produced params (active path for post/detail/user_post):**
- Query: full `BaseRequestModel` fields + `a_bogus` (X-Bogus path **commented out as dead** 2024-06-12)
- Cookies (from config): include `ttwid`, `s_v_web_id`, etc. (not generated per-request in the fetch path)
- Utils also expose: `msToken` (real/fake), `ttwid`, `verify_fp` / `s_v_web_id`, `X-Bogus`, `a_bogus`

```python
            # 2024年6月12日22:41:44 由于XBogus加密已经失效，所以不再使用XBogus加密参数，转移至a_bogus加密参数。
            params_dict = params.dict()
            params_dict["msToken"] = ''
            a_bogus = BogusManager.ab_model_2_endpoint(params_dict, kwargs["headers"]["User-Agent"])
            endpoint = f"{DouyinAPIEndpoints.POST_DETAIL}?{urlencode(params_dict)}&a_bogus={a_bogus}"
```
-> `_refs/Douyin_TikTok_Download_API/crawlers/douyin/web/web_crawler.py:98-107`

**Generation sites:**

| Param | Where | Runtime |
|-------|-------|---------|
| `a_bogus` | `BogusManager.ab_model_2_endpoint` → `ABogus.get_value` | Pure Python + `gmssl` SM3 |
| `X-Bogus` | `BogusManager.xb_*` → `xbogus.XBogus` (still used for mix/live/comment/profile) | Pure Python |
| `msToken` | `TokenManager.gen_real_msToken` / `gen_false_msToken` | HTTP POST to mssdk; fallback random |
| `ttwid` | `TokenManager.gen_ttwid` | POST `ttwid.bytedance.com` |
| `verifyFp` / `s_v_web_id` | `VerifyFpManager.gen_verify_fp` | Pure Python local |

Core `a_bogus` wrapper:

```python
    @classmethod
    def ab_model_2_endpoint(cls, params: dict, user_agent: str) -> str:
        if not isinstance(params, dict):
            raise TypeError("参数必须是字典类型")

        try:
            ab_value = AB().get_value(params, )
        except Exception as e:
            raise RuntimeError("生成A-Bogus失败: {0})".format(e))

        return quote(ab_value, safe='')
```
-> `_refs/Douyin_TikTok_Download_API/crawlers/douyin/web/utils.py:293-304`

```python
class ABogus:
    __filter = compile(r'%([0-9A-F]{2})')
    __arguments = [0, 1, 14]
    __ua_key = "\u0000\u0001\u000e"
    __end_string = "cus"
    __version = [1, 0, 1, 5]
    __browser = "1536|742|1536|864|0|0|0|0|1536|864|1536|864|1536|742|24|24|MacIntel"
```
-> `_refs/Douyin_TikTok_Download_API/crawlers/douyin/web/abogus.py:30-36`

```python
    def get_value(self,
                  url_params: dict | str,
                  method="GET",
                  start_time=0,
                  end_time=0,
                  random_num_1=None,
                  random_num_2=None,
                  random_num_3=None,
                  ) -> str:
        string_1 = self.generate_string_1(
            random_num_1,
            random_num_2,
            random_num_3,
        )
        string_2 = self.generate_string_2(urlencode(url_params) if isinstance(
            url_params, dict) else url_params, method, start_time, end_time, )
        string = string_1 + string_2
        return self.generate_result(string, "s4")
```
-> `_refs/Douyin_TikTok_Download_API/crawlers/douyin/web/abogus.py:601-620`

**Loader note:** file header states algorithm origin is JoeanAmier / GPL code re-licensed into this Apache project; UA code **hardcoded** for Chrome/90 config UA (not dynamic from request UA).

```python
# import execjs
```
-> `_refs/Douyin_TikTok_Download_API/crawlers/douyin/web/utils.py:45`

Commented Node/execjs path for A-Bogus JS (not active):

```python
    #     a_bogus_js_path = os.path.join(js_path, 'a_bogus.js')
    #         node_runtime = execjs.get('Node')
    #         context = node_runtime.compile(js_code)
    #         arg = [0, 1, 0, endpoint_query_params, "", user_agent]
    #         a_bougus = quote(context.call('get_a_bogus', arg), safe='')
```
-> `_refs/Douyin_TikTok_Download_API/crawlers/douyin/web/utils.py:275-289`

**Embedded JS/WASM:** NOT FOUND active embedded JS/WASM for Douyin web sign in this repo. (Commented `a_bogus.js` only.)

**msToken:**

```python
    def gen_real_msToken(cls) -> str:
        payload = json.dumps(
            {
                "magic": cls.token_conf["magic"],
                "version": cls.token_conf["version"],
                "dataType": cls.token_conf["dataType"],
                "strData": cls.token_conf["strData"],
                "tspFromClient": get_timestamp(),
            }
        )
        ...
                response = client.post(
                    cls.token_conf["url"], content=payload, headers=headers
                )
                ...
                msToken = str(httpx.Cookies(response.cookies).get("msToken"))
                if len(msToken) not in [120, 128]:
                    raise APIResponseError(...)
                return msToken
            except Exception as e:
                ...
                return cls.gen_false_msToken()

    def gen_false_msToken(cls) -> str:
        return gen_random_str(126) + "=="
```
-> `_refs/Douyin_TikTok_Download_API/crawlers/douyin/web/utils.py:88-156`

Config endpoint + magic:

```yaml
    msToken:
      url: https://mssdk.bytedance.com/web/report
      magic: 538969122
      version: 1
      dataType: 8
```
-> `_refs/Douyin_TikTok_Download_API/crawlers/douyin/web/config.yaml:17-23`

**Length constants:** valid real token len `[120, 128]`; false = `126` random + `"=="`.

**ttwid / verifyFp:**

```python
    def gen_ttwid(cls) -> str:
        ...
                response = client.post(
                    cls.ttwid_conf["url"], content=cls.ttwid_conf["data"]
                )
                ...
                ttwid = str(httpx.Cookies(response.cookies).get("ttwid"))
```
-> `_refs/Douyin_TikTok_Download_API/crawlers/douyin/web/utils.py:158-174`

```yaml
    ttwid:
      url: https://ttwid.bytedance.com/ttwid/union/register/
      data: '{"region":"cn","aid":1768,"needFid":false,"service":"www.ixigua.com","migrate_info":{"ticket":"","source":"node"},"cbUrlProtocol":"https","union":true}'
```
-> `_refs/Douyin_TikTok_Download_API/crawlers/douyin/web/config.yaml:27-30`

```python
    def gen_verify_fp(cls) -> str:
        base_str = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
        ...
        return "verify_" + r + "_" + "".join(o)

    def gen_s_v_web_id(cls) -> str:
        return cls.gen_verify_fp()
```
-> `_refs/Douyin_TikTok_Download_API/crawlers/douyin/web/utils.py:200-233`

---

### 1.B Endpoints (this repo)

Class `DouyinAPIEndpoints` — all **web** unless noted:

| purpose | full URL path | method | repo | file:line |
|---------|---------------|--------|------|-----------|
| home feed | `https://www.douyin.com/aweme/v1/web/tab/feed/` | GET | DTDA | `endpoints.py:25` |
| user short info | `.../aweme/v1/web/im/user/info/` | GET | DTDA | `endpoints.py:28` |
| user profile | `.../aweme/v1/web/user/profile/other/` | GET | DTDA | `endpoints.py:31` |
| user post list | `.../aweme/v1/web/aweme/post/` | GET | DTDA | `endpoints.py:37` |
| locate post | `.../aweme/v1/web/locate/post/` | GET | DTDA | `endpoints.py:40` |
| general search | `.../aweme/v1/web/general/search/single/` | GET | DTDA | `endpoints.py:43` |
| video search | `.../aweme/v1/web/search/item/` | GET | DTDA | `endpoints.py:46` |
| user search | `.../aweme/v1/web/discover/search/` | GET | DTDA | `endpoints.py:49` |
| live search | `.../aweme/v1/web/live/search/` | GET | DTDA | `endpoints.py:52` |
| **aweme detail** | `.../aweme/v1/web/aweme/detail/` | GET | DTDA | `endpoints.py:55` |
| danmaku | `.../aweme/v1/web/danmaku/get_v2/` | GET | DTDA | `endpoints.py:58` |
| user favorite | `.../aweme/v1/web/aweme/favorite/` | GET | DTDA | `endpoints.py:61` |
| user like (ies) | `https://www.iesdouyin.com/web/api/v2/aweme/like/` | GET | DTDA | `endpoints.py:64` |
| following/follower | `.../user/following/list/`, `.../follower/list/` | GET | DTDA | `endpoints.py:67-70` |
| **mix/collection** | `.../aweme/v1/web/mix/aweme/` | GET | DTDA | `endpoints.py:73` |
| history | `.../history/read/` | GET | DTDA | `endpoints.py:76` |
| collection list | `.../aweme/listcollection/` | POST (crawler uses post) | DTDA | `endpoints.py:79` |
| collects list/video | `.../collects/list/`, `.../collects/video/list/` | GET | DTDA | `endpoints.py:82-85` |
| music collection | `.../music/listcollection/` | GET | DTDA | `endpoints.py:88` |
| friend/follow/related feed | familiar/follow/related | GET | DTDA | `endpoints.py:91-97` |
| live enter | `https://live.douyin.com/webcast/room/web/enter/` | GET | DTDA | `endpoints.py:103` |
| live reflow (mobile domain) | `https://webcast.amemv.com/webcast/room/reflow/info/` | GET | DTDA | `endpoints.py:106` |
| live gift rank | `.../webcast/ranklist/audience/` | GET | DTDA | `endpoints.py:109` |
| comments | `.../comment/list/`, reply, publish, delete, digg | GET/POST | DTDA | `endpoints.py:133-145` |
| hot search | `.../hot/search/list/` | GET | DTDA | `endpoints.py:148` |
| channel feed | `.../channel/feed/` | GET | DTDA | `endpoints.py:151` |
| short-link resolve | **not a Douyin API** — HTTP GET follow redirects on `v.douyin.com` via `AwemeIdFetcher` / `SecUserIdFetcher` | GET | DTDA | `utils.py:341-450` |

**Web vs app:** this Douyin package is **web API** (`device_platform=webapp`, `aid=6383`). Separate `crawlers/tiktok/app/` exists for TikTok app, not Douyin app.

Base query model defaults:

```python
class BaseRequestModel(BaseModel):
    device_platform: str = "webapp"
    aid: str = "6383"
    channel: str = "channel_pc_web"
    pc_client_type: int = 1
    version_code: str = "290100"
    version_name: str = "29.1.0"
    ...
    msToken: str = TokenManager.gen_real_msToken()
```
-> `_refs/Douyin_TikTok_Download_API/crawlers/douyin/web/models.py:8-42`

---

### 1.C Headers, cookies, UA

Default headers from crawler config:

```yaml
    headers:
      Accept-Language: zh-CN,zh;q=0.8,zh-TW;q=0.7,zh-HK;q=0.5,en-US;q=0.3,en;q=0.2
      User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/90.0.4430.212 Safari/537.36
      Referer: https://www.douyin.com/
      Cookie: __ac_nonce=... (long sample cookie string in file)
```
-> `_refs/Douyin_TikTok_Download_API/crawlers/douyin/web/config.yaml:3-11`

Loaded as:

```python
            "headers": {
                "Accept-Language": douyin_config["headers"]["Accept-Language"],
                "User-Agent": douyin_config["headers"]["User-Agent"],
                "Referer": douyin_config["headers"]["Referer"],
                "Cookie": douyin_config["headers"]["Cookie"],
            },
```
-> `_refs/Douyin_TikTok_Download_API/crawlers/douyin/web/web_crawler.py:75-81`

**Cookie required?** Config comment: “你唯一需要修改的地方就是这里的Cookie”. Collection endpoints require user-supplied Cookie (`fetch_user_collection_videos`). Public detail uses config Cookie + signatures; **sessionid not specially validated** in code — any working browser cookie bundle.

**Browser cookie import:** `chrome-cookie-sniffer/` Chrome extension — intercepts requests on `douyin.com`, stores cookies, optional webhook:

```json
{
  "service": "douyin",
  "cookie": "具体的Cookie字符串",
  "timestamp": "2025-08-29T12:34:56.789Z"
}
```
-> `_refs/Douyin_TikTok_Download_API/chrome-cookie-sniffer/README.md:75-80`

---

### 1.D No-watermark URL derivation

Hybrid parser (used by API/web UI after detail fetch):

```python
                uri = data['video']['play_addr']['uri']
                wm_video_url_HQ = data['video']['play_addr']['url_list'][0]
                wm_video_url = f"https://aweme.snssdk.com/aweme/v1/playwm/?video_id={uri}&radio=1080p&line=0"
                nwm_video_url_HQ = wm_video_url_HQ.replace('playwm', 'play')
                nwm_video_url = f"https://aweme.snssdk.com/aweme/v1/play/?video_id={uri}&ratio=1080p&line=0"
```
-> `_refs/Douyin_TikTok_Download_API/crawlers/hybrid/hybrid_crawler.py:177-181`

**Key paths tried (Douyin video):**
1. `video.play_addr.uri`
2. `video.play_addr.url_list[0]` (as HQ watermarked base)
3. Construct snssdk `playwm` / `play` with `video_id={uri}&ratio=1080p&line=0`
4. String replace `playwm` → `play` on url_list[0]

**Image post:**
```python
                for i in data['images']:
                    no_watermark_image_list.append(i['url_list'][0])
                    watermark_image_list.append(i['download_url_list'][0])
```
-> `hybrid_crawler.py:198-200`

**TikTok HQ:** `video.bit_rate[0].play_addr.url_list[0]` (index 0 only, no sort).

**Highest bitrate selection:** NOT FOUND for Douyin path (fixed 1080p construct / first url_list). TikTok uses `bit_rate[0]` only.

**Audio:** result embeds `music` object from aweme as-is; no separate extraction ranking.

---

### 1.E Download transport

Root API config (service download path prefix only — not full media client):

```yaml
  Download_Switch: true
  Download_Path: "./download"
  Download_File_Prefix: "douyin.wtf_"
```
-> `_refs/Douyin_TikTok_Download_API/config.yaml:38-42`

Fetcher timeouts: `timeout=10`, `retries=5` on httpx transports in `utils.py` (e.g. line 344, 429).

Chunked download / resume / semaphore: **NOT FOUND** as a reusable media downloader module in this repo (API returns URLs; optional download endpoint streams URLs).

Proxy shape:

```yaml
    proxies:
      http:
      https:
```
-> `crawlers/douyin/web/config.yaml:13-15`

---

### 1.F Config dumps

**Root `config.yaml` (full):**

```yaml
# Web
Web:
  # APP Switch
  PyWebIO_Enable: true    # Enable APP | 启用APP

  # APP Information
  Domain: https://douyin.wtf    # Web domain | Web域名

  # APP Configuration
  PyWebIO_Theme: minty    # PyWebIO theme | PyWebIO主题
  Max_Take_URLs: 30    # Maximum number of URLs that can be taken at a time | 一次最多可以取得的URL数量


  # Web Information
  Tab_Title: Douyin_TikTok_Download_API    # Web title | Web标题
  Description: Douyin_TikTok_Download_API is a free open-source API service for Douyin/TikTok. It provides a simple, fast, and stable API for developers to develop applications based on Douyin/TikTok.    # Web description | Web描述
  Favicon: https://raw.githubusercontent.com/Evil0ctal/Douyin_TikTok_Download_API/main/logo/logo192.png    # Web favicon | Web图标

  # Fun Configuration
  Easter_Egg: true    # Enable Easter Egg | 启用彩蛋
  Live2D_Enable: true
  Live2D_JS: https://fastly.jsdelivr.net/gh/TikHubIO/TikHub_live2d@latest/autoload.js

# API
API:
  # Network Configuration
  Host_IP: 0.0.0.0    # default IP | 默认IP
  Host_Port: 80    # default port is 80 | 默认端口为80
  Docs_URL: /docs    # API documentation URL | API文档URL
  Redoc_URL: /redoc    # API documentation URL | API文档URL

  # API Information
  Version: V4.1.2    # API version | API版本
  Update_Time: 2025/03/16    # API update time | API更新时间
  Environment: Demo    # API environment | API环境

  # Download Configuration
  Download_Switch: true    # Enable download function | 启用下载功能

  # File Configuration
  Download_Path: "./download"    # Default download directory | 默认下载目录
  Download_File_Prefix: "douyin.wtf_"    # Default download file prefix | 默认下载文件前缀


# iOS Shortcut
iOS_Shortcut:
  iOS_Shortcut_Version: 7.0
  iOS_Shortcut_Update_Time: 2024/07/05
  iOS_Shortcut_Link: https://www.icloud.com/shortcuts/06f891a026df40cfa967a907feaea632
  iOS_Shortcut_Link_EN: https://www.icloud.com/shortcuts/06f891a026df40cfa967a907feaea632
  iOS_Shortcut_Update_Note: 重构了快捷指令以兼容TikHub API。
  iOS_Shortcut_Update_Note_EN: Refactored the shortcut to be compatible with the TikHub API.
```
-> `_refs/Douyin_TikTok_Download_API/config.yaml:1-52`

**Field annotations:**
- `Web.*` — PyWebIO UI only (`app/web/`)
- `API.Host_*`, Docs/Redoc — FastAPI bind (`app/main.py`)
- `API.Version/Update_Time/Environment` — metadata in responses/UI
- `Download_Switch/Path/Prefix` — download endpoint file writing
- `iOS_Shortcut.*` — shortcut download page metadata

**Douyin token config:** full file at `_refs/Douyin_TikTok_Download_API/crawlers/douyin/web/config.yaml` (headers Cookie sample + msToken strData multi-KB + ttwid). Controls: headers/proxies for all crawler requests; msToken POST body; ttwid POST body. Read at `utils.py:74-86`, `web_crawler.py:66-67`.

---

### 1.G Errors

HTTP mapping in fetchers: 401 → `APIUnauthorizedError`, 404 → `APINotFoundError`, 503 → `APIUnavailableError`, 444 treated as success-ish for sec_uid (`utils.py:347-348`).

Douyin JSON `status_code` / captcha: **NOT FOUND** structured handling in web_crawler (returns raw JSON).

Retry-with-new-signature: **NOT FOUND** (single shot per call).

---

### 1.H Batch / monitoring

Service is per-request API. No SQLite watch-list schema in this repo for incremental user posts.

---

## 2. Repo B — f2 (Apache-2.0)

### 2.A Signature

**Params:** `a_bogus` (default encryption `ab` in conf) or `X-Bogus`; `msToken` (164/184 real); `ttwid`; `webid`; `verifyFp`/`s_v_web_id`; live uses **JS via execjs** `webcast_signature.js`.

```yaml
  douyin:
    encryption: ab
```
-> `_refs/f2/f2/conf/conf.yaml:22-23`

```python
class ABogusManager:
    ...
        final_endpoint = f"{base_endpoint}{separator}{param_str}&a_bogus={ab_value[1]}"
```
-> `_refs/f2/f2/apps/douyin/utils.py:591-637`

```python
class XBogusManager:
    ...
        final_endpoint = f"{base_endpoint}{separator}{param_str}&X-Bogus={xb_value[1]}"
```
-> `_refs/f2/f2/apps/douyin/utils.py:550-588`

**msToken:**

```python
            msToken = str(httpx.Cookies(response.cookies).get("msToken"))
            if len(msToken) not in [164, 184]:
                raise APIResponseError(_("{0} 内容不符合要求").format("msToken"))
```
-> `_refs/f2/f2/apps/douyin/utils.py:220-222`

```python
    def gen_false_msToken(cls) -> str:
        false_msToken = gen_random_str(182) + "=="
```
-> `_refs/f2/f2/apps/douyin/utils.py:296-300`

mssdk URL:

```yaml
    msToken:
      url: https://mssdk.bytedance.com/web/r/token?ms_appid=6383&msToken=...
      magic: 538969122
      version: 1
      dataType: 8
      ulr: 0
      strData: <multi-KB payload, full file ~15.8KB>
```
-> `_refs/f2/f2/conf/conf.yaml:62-68`

**ttwid:** same register URL as DTDA (`conf.yaml:70-72`).

**verifyFp:** identical algorithm to DTDA (`utils.py:514-547`).

**Live signature (JS):**

```python
class DouyinWebcastSignature:
    ...
    - 该类利用 `execjs` 执行 JavaScript 代码来计算签名，需要确保 `webcast_signature.js` 文件存在
```
-> `_refs/f2/f2/apps/douyin/algorithm/webcast_signature.py:9-39`

**Embedded files:**
- `_refs/f2/f2/apps/douyin/algorithm/webcast_signature.js`
- Pure Python: `f2/utils/abogus.py`, `f2/utils/xbogus.py`

**WASM / remote sign service:** NOT FOUND (except mssdk/ttwid/webid HTTP).

### 2.B Endpoints

`f2/apps/douyin/api.py` — largely same web paths as DTDA plus:

| purpose | path | file:line |
|---------|------|-----------|
| slides (ies) | `https://www.iesdouyin.com/web/api/v2/aweme/slidesinfo/` | `api.py:43` |
| post search | `.../general/search/single/` | `api.py:49` |
| home post search | `.../home/search/item/` | `api.py:52` |
| live im fetch | `https://live.douyin.com/webcast/im/fetch/` | `api.py:109` |
| user live status | `.../distribution/check_user_live_status/` | `api.py:112` |
| query user | `.../query/user/` | `api.py:133` |
| post stats | `.../aweme/v2/web/aweme/stats/` | `api.py:136` |
| live WSS | `wss://webcast5-ws-web-hl.douyin.com/webcast/im/push/v2/` | `api.py:22-25` |

### 2.C Headers / cookies

```yaml
    headers:
      User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36 Edg/130.0.0.0
      Referer: https://www.douyin.com/
```
-> `_refs/f2/f2/conf/conf.yaml:49-51`

App defaults:

```yaml
douyin:
  cookie:
  naming: '{create}_{desc}'
  path: Download
  timeout: 10
  max_retries: 5
  lyric: yes
  max_connections: 5
  max_counts: 0
  max_tasks: 10
  page_counts: 20
```
-> `_refs/f2/f2/conf/app.yaml:1-11`

Cookie required for CLI modes (user supplies via config/CLI). Downloader merges Cookie into headers (`base_downloader.py:79`).

### 2.D No-watermark / quality

Filter takes **first** bit_rate entry only (not sorted):

```python
    def video_play_addr(self):
        return self._get_attr_value(
            "$.aweme_detail.video.bit_rate[0].play_addr.url_list"
        )
```
-> `_refs/f2/f2/apps/douyin/filter.py:1408-1411`

List posts:

```python
    def video_play_addr(self):
        return self._get_list_attr_value(
            "$.aweme_list[*].video.bit_rate[0].play_addr.url_list"
        )
```
-> `filter.py:266-268`

Images: `$.aweme_detail.images[*].url_list[0]`; live photo: `images[*].video.play_addr.url_list[0]`.

Music: `$.aweme_detail.music.play_url.url_list[0]` (`filter.py:1312`).

**playwm rewrite:** NOT FOUND in f2 douyin filter (relies on bit_rate play_addr).

### 2.E Download transport

Dynamic chunk size:

```python
def get_chunk_size(file_size: int) -> int:
    if file_size < 10 * 1024:
        return file_size
    elif file_size < 1 * 1024 * 1024:
        return file_size // 10
    elif file_size < 10 * 1024 * 1024:
        return file_size // 20
    elif file_size < 100 * 1024 * 1024:
        return file_size // 50
    else:
        return 1 * 1024 * 1024  # 1MB
```
-> `_refs/f2/f2/utils/_dl.py:140-161`

Resume:

```python
                    start_byte = 0 if not tmp_path.exists() else tmp_path.stat().st_size
                    ...
                    range_headers = (
                        {"Range": f"bytes={start_byte}-"} if start_byte else {}
                    )
```
-> `_refs/f2/f2/dl/base_downloader.py:189-204`

- timeout: `10` (app.yaml); content-length HEAD uses `timeout=10.0`, transport `retries=5` (`_dl.py:38-40`)
- max_retries download loop: `3` (`base_downloader.py:211`)
- max_connections / max_tasks: `5` / `10` (app.yaml)
- proxies: `http://` / `https://` empty keys in conf.yaml
- progress: Rich `progress` console manager

### 2.F Config

Full `app.yaml` and `defaults.yaml` pasted in section reads above. Full `conf.yaml` is 15.8KB (includes huge `strData`); structure:

```
f2.version: "0.0.1.7"
f2.douyin.encryption: ab
f2.douyin.BaseRequestModel.version.code/name: "290100"/"29.1.0"
f2.douyin.headers.User-Agent: Chrome/130 Edge
f2.douyin.msToken: url, magic 538969122, version 1, dataType 8, ulr 0, strData
f2.douyin.ttwid: register URL + JSON data
f2.douyin.webid: mcs.zijieapi.com body
```
-> `_refs/f2/f2/conf/conf.yaml` entire file

Annotations: `ClientConfManager` (`apps/douyin/utils.py:39-121`) reads all of `f2.douyin.*`. CLI merges `app.yaml` defaults via `conf_manager`.

### 2.G Errors

API exception hierarchy: `APIConnectionError`, `APIResponseError`, `APIUnauthorizedError`, `APINotFoundError`, `APITimeoutError`. Token path raises on bad length/status.

Risk/captcha structured codes: **NOT FOUND** equivalent to douyin-downloader 2483.

### 2.H Batch / monitoring

SQLite user table for incremental last aweme:

```python
    TABLE_NAME = "user_info_web"
    ...
            "last_aweme_id TEXT",
```
-> `_refs/f2/f2/apps/douyin/db.py:7-45`

Date interval filter methods exist (`filter_by_date_interval` mentioned in CHANGELOG). Bark push for notifications.

---

## 3. Repo C — TikTokDownloader / DouK-Downloader (GPL-3.0) — **DESCRIBE-ONLY**

**Do not copy source into OmniCast.** Technique notes only.

### 3.A Signature (GPL)

Modules under `src/encrypt/`:

| Module | Role |
|--------|------|
| `aBogus.py` | Pure Python ABogus (gmssl SM3); browser string includes `Win32` |
| `xBogus.py` | X-Bogus |
| `xGnarly.py` | TikTok `X-Gnarly` (Release_Notes item 10) |
| `msToken.py` | Real POST `https://mssdk.bytedance.com/web/common`; fake size **156** |
| `ttWid.py` | Same union/register + TikTok check |
| `verifyFp.py` | Local `verify_{base36}_{uuidish}` |
| `webID.py` | webid |
| `device_id.py` | TikTok device id |

Also ships **JS** for reference/exec:

- `static/js/a_bogus.js` — `generate_a_bogus(url_search_params, user_agent)`
- `static/js/X-Bogus.js`
- dependency `never-jscore` in pyproject (JS runtime)

```python
    def get_fake_ms_token(key="msToken", size=156) -> dict:
        base_str = digits + ascii_uppercase + ascii_lowercase
        ...
        return {key: "".join(base_str[randint(0, length)] for _ in range(size))}
```
-> `_refs/TikTokDownloader/src/encrypt/msToken.py:81-87` **[GPL]**

```python
class TtWid:
    NAME = "ttwid"
    API = "https://ttwid.bytedance.com/ttwid/union/register/"
    DATA = (
        '{"region":"cn","aid":1768,"needFid":false,"service":"www.ixigua.com",...'
    )
```
-> `ttWid.py:17-23` **[GPL]**

Version: `5.8` / `__VERSION__` in `src/custom/internal.py:5-8`. Git tip `2026-08-07`.

### 3.B Endpoints (GPL describe)

`Detail` API:

```python
        self.api = f"{self.domain}aweme/v1/web/aweme/detail/"
...
            "aweme_id": self.detail_id,
            "version_code": "190500",
            "version_name": "19.5.0",
```
-> `src/interface/detail.py:21-30` **[GPL]**

Other interfaces in `src/interface/`: account, collection, collects, comment, hashtag, hot, info, live, mix, search, slides, user — web-style Douyin + TikTok twins (`*_tiktok.py`).

### 3.C Headers (GPL)

```python
USERAGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36"
...
DOWNLOAD_HEADERS = {
    "Accept": "*/*",
    "Range": "bytes=0-",
    "Referer": REFERER,
    "User-Agent": USERAGENT,
}
```
-> `src/custom/internal.py:48-78` **[GPL]**

Cookie: settings keys `cookie` / `cookie_tiktok` required for normal operation (docs). Browser cookie import **removed** (Release_Notes item 12).

### 3.D URL derivation (GPL technique)

Sort `video.bit_rate` by `(max(height,width), FPS, bit_rate, data_size)` ascending, take **last** (highest):

```python
            bit_rate.sort(
                key=lambda x: (
                    max(
                        x[3],
                        x[4],
                    ),
                    x[0],
                    x[1],
                    x[2],
                ),
            )
            return (
                (
                    bit_rate[-1][-3],
                    bit_rate[-1][-2],
                    bit_rate[-1][-1][VIDEO_INDEX],
                )
```
-> `src/extract/extractor.py:525-540` **[GPL — reimplement clean-room]**

Fields used: `FPS`, `bit_rate`, `play_addr.data_size/height/width/url_list`.

### 3.E Download transport (GPL numbers)

```python
        "chunk": 1024 * 1024 * 2,  # 2 MiB
        "timeout": 10,
        "max_retry": 5,
```
-> `src/config/settings.py:84-86` **[GPL]**

```python
MAX_WORKERS = 4
RETRY = 5
TIMEOUT = 10
```
-> `src/custom/static.py:2`, `internal.py:41-42` **[GPL]**

Downloader: httpx, Semaphore(MAX_WORKERS), Rich progress, Range-friendly download headers.

### 3.F Settings default structure (GPL)

`Settings.default` dict keys (see `settings.py:21-121`): accounts_urls, mix_urls, root, folder_name, name_format, cookie, proxy, chunk, timeout, max_retry, browser_info (UA Chrome/150, webid), etc. Written to `settings.json` on first run.

### 3.G Errors (GPL)

Account check: `status_code == 0` success path (`interface/account.py:262`). Docs mention ttwid failure / risk-control account change. Template logs response codes.

### 3.H Monitoring (GPL)

SQLite `DouK-Downloader.db`:

```sql
download_data (ID TEXT PRIMARY KEY);
mapping_data (ID, NAME, MARK);
config_data (NAME, VALUE 0|1);
option_data (NAME, VALUE);
```
-> `src/manager/database.py:31-49` **[GPL]**

`accounts_urls` earliest/latest date windows in settings for monitoring accounts. Metadata writers: csv/xlsx/sql modules under `src/storage/`.

---

## 4. Repo D — douyin-downloader (MIT) — **PRIMARY**

### 4.A Signature

**Produced:** prefers `a_bogus` via `ABogus.generate_abogus`; fallback `X-Bogus` via `XBogus.build`; always injects `msToken` in query; cookies carry `ttwid` etc.

```python
    def build_signed_path(...):
        query = urlencode(params)
        endpoint = f"{(base_url or self.BASE_URL).rstrip('/')}{path}"
        ab_signed = self._build_abogus_url(endpoint, query, request_data=request_data)
        if ab_signed:
            return ab_signed
        return self.sign_url(f"{endpoint}?{query}")
```
-> `_refs/douyin-downloader/core/api_client.py:350-363`

```python
            browser_fp = BrowserFingerprintGenerator.generate_fingerprint("Chrome")
            signer = ABogus(fp=browser_fp, user_agent=self.headers["User-Agent"])
            body = urlencode(request_data or {})
            params_with_ab, _ab, ua, _body = signer.generate_abogus(query, body)
            return f"{base_url}?{params_with_ab}", ua
```
-> `api_client.py:375-380`

**Runtime:** pure Python (`utils/abogus.py` f2-style class + `gmssl`); optional import failure → X-Bogus only.

**msToken:**

```python
    # 与 F2 保持一致，长度通常为 164 或 184
        return len(token.strip()) in (164, 184)

    def gen_false_ms_token(cls) -> str:
        token = (
            "".join(random.choice(string.ascii_letters + string.digits) for _ in range(182)) + "=="
        )
```
-> `_refs/douyin-downloader/auth/ms_token_manager.py:47-55`

Real: loads f2 conf from GitHub raw URL or cache, POST mssdk, parse Set-Cookie (`ms_token_manager.py:68-103`).

**ttwid:** expected in user cookies (`config.example.yml`); not auto-generated in MsTokenManager. Cookie fetcher tools list required keys:

```python
REQUIRED_KEYS = {"msToken", "ttwid", "odin_tt", "passport_csrf_token"}
```
-> `_refs/douyin-downloader/tools/cookie_fetcher.py:16`

**verifyFp:** via abogus BrowserFingerprintGenerator path inside ABogus (not separate verifyFp cookie generator in this package).

### 4.B Endpoints (used in api_client)

| purpose | path | method | file:line |
|---------|------|--------|-----------|
| video detail | `/aweme/v1/web/aweme/detail/` | GET | `api_client.py:641` |
| user post | `/aweme/v1/web/aweme/post/` | GET | `:683` |
| user like | `/aweme/v1/web/aweme/favorite/` | GET | `:690` |
| user mix list | `/aweme/v1/web/mix/list/` | GET | `:697` |
| user music list | `/aweme/v1/web/music/list/` | GET | `:704` |
| following | `/aweme/v1/web/user/following/list/` | GET | `:740` |
| collection | `/aweme/v1/web/aweme/listcollection/` | POST | `:785` |
| collects | `/aweme/v1/web/collects/list/` | GET | `:804` |
| collects video | `/aweme/v1/web/collects/video/list/` | GET | `:812` |
| mix listcollection | `/aweme/v1/web/mix/listcollection/` | GET | `:823` |
| user profile | `/aweme/v1/web/user/profile/other/` | GET | `:830` |
| profile self | `/aweme/v1/web/user/profile/self/` | GET | `:848` |
| mix detail | `/aweme/v1/web/mix/detail/` | GET | `:856` |
| mix aweme | `/aweme/v1/web/mix/aweme/` | GET | `:864` |
| music detail | `/aweme/v1/web/music/detail/` | GET | `:870` |
| music aweme | `/aweme/v1/web/music/aweme/` | GET | `:880` |
| live episode | `/aweme/v1/web/show/episode/enter/` | GET | `:1014` |
| live replay list | `/aweme/v1/web/show/episode/replay_list/` | GET | `:1036` |
| hot search | `/aweme/v1/web/hot/search/list/` | GET | `:1100` |
| search | `/aweme/v1/web/general/search/single/` | GET | `:1152` |
| comments | `/aweme/v1/web/comment/list/` | GET | `:1225` |
| comment replies | `/aweme/v1/web/comment/list/reply/` | GET | `:1263` |
| **play (CDN construct)** | `/aweme/v1/play/` | GET signed | `downloader_base.py:1038` |
| live web | `https://live.douyin.com` | — | `BASE` `api_client.py:234` |
| live reflow | `https://webcast.amemv.com` | — | `:235` |
| short URL | `resolve_short_url` follow redirects | GET | `api_client.py:1266` |

**aid dual try for detail:** `("6383", "1128")` — 6383 notes/gallery, 1128 videos (`api_client.py:624-626`).

Default query (excerpt):

```python
        return {
            "device_platform": "webapp",
            "aid": "6383",
            "channel": "channel_pc_web",
            "update_version_code": "170400",
            "pc_client_type": "1",
            ...
            "version_code": "290100",
            "version_name": "29.1.0",
            ...
            "browser_version": "139.0.0.0",
            ...
            "msToken": ms_token,
        }
```
-> `api_client.py:311-344`

### 4.C Headers / cookies

```python
_USER_AGENT_POOL = [
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36"
    ),
]
...
        self.headers = {
            "User-Agent": selected_ua,
            "Referer": "https://www.douyin.com/?recommend=1",
            "Accept": "*/*",
            "Accept-Encoding": "gzip, deflate",
            "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
        }
```
-> `api_client.py:220-264`

Download headers:

```python
        headers = {
            "Referer": f"{self.api_client.BASE_URL}/",
            "Origin": self.api_client.BASE_URL,
            "Accept": "*/*",
        }
        headers["User-Agent"] = user_agent or self.api_client.headers.get("User-Agent", "")
```
-> `downloader_base.py:196-204`

**Login cookies:** sessionid family in browser blocklist when merging browser cookies (`_BROWSER_COOKIE_BLOCKLIST` lines 236-249) for certain flows. Login required detected via:

```python
_LOGIN_REQUIRED_STATUS_CODES = {2483}
...
    return code in _LOGIN_REQUIRED_STATUS_CODES or "请先登录" in msg or "用户未登录" in msg
```
-> `api_client.py:30-145`

Public video download: cookies with ttwid/msToken/csrf typically needed; full login for private/liked/collection.

Cookie tools: `tools/cookie_fetcher.py`, `auth/cookie_manager.py`, Playwright login (`cli/login_flow.py`).

### 4.D No-watermark derivation (core)

Candidate build:

```python
        play_addr = self._pick_preferred_play_addr(video, quality) or {}
        url_candidates = [c for c in (play_addr.get("url_list") or []) if c]
        url_candidates.sort(key=lambda u: 0 if "watermark=0" in u else 1)
        ...
        # direct CDN first; douyin.com play endpoint signed second; watermark last
        constructed = self._build_signed_play_url(...)  # /aweme/v1/play/ watermark=0
```
-> `downloader_base.py:925-958`

Play construct params:

```python
        params = {
            "video_id": uri,
            "ratio": ratio,
            "line": "0",
            "is_play_url": "1",
            "watermark": "0",
            "source": "PackSourceEnum_PUBLISH",
        }
```
-> `downloader_base.py:1029-1037`

Original quality probe: `ratio: "default"` + Range bytes=0-0 (`:1093-1106`).

**JSON key order for play_addr pick:**
1. `video.bit_rate[*]` ranked by quality
2. else `video.play_addr`
3. else `_PLAY_ADDR_KEYS`: `play_addr_h264`, `play_addr_265`, `play_addr_256`, `play_addr`

```python
    _PLAY_ADDR_KEYS = (
        "play_addr_h264",
        "play_addr_265",
        "play_addr_256",
        "play_addr",
    )
```
-> `downloader_base.py:889-894`

**Quality ranking:**

```python
    _QUALITY_TARGET_WIDTH: Dict[str, int] = {
        "1440p": 2560,
        "1080p": 1920,
        "720p": 1280,
        "540p": 960,
        "480p": 854,
        "360p": 640,
    }
```
-> `downloader_base.py:1143-1150`

```python
        # Default / "highest": highest resolution, tie-break by bit rate.
        entries.sort(key=lambda t: (-t[2], -t[0], -t[1]))
```
-> `downloader_base.py:1238-1240`

Uses fields: `bit_rate`, `play_addr.width/height`, pixels; **not** gear_name/quality_type/FPS/is_h265 in sort (those may exist in JSON but unused in this picker).

**Watermark URL detection:**

```python
        watermark_hints = (
            "tplv-dy-water",
            "dy-water",
            "owner_watermark",
            "watermark_image",
            "watermark=1",
            "playwm",
        )
```
-> `downloader_base.py:1421-1428`

**Gallery / live photo:**

```python
    _GALLERY_AWEME_TYPES = {2, 68, 150}
```
-> `downloader_base.py:888`

Image sources ranked: `watermark_free_download_url_list`, `origin_image`, `display_image`, item, `download_url`, `download_addr`, `download_url_list`, `owner_watermark_image` (`:1286-1295`).

Live photo URLs from nested `item.video` preferred play_addr + h264/265/256/play/download keys (`:1306-1327`).

**Audio:** `aweme_data["music"]["play_url"]` first url (`:568-569`).

### 4.E Download transport

```python
    "thread": 5,
    "retry_times": 3,
    "rate_limit": 2,
    "proxy": "",
```
-> `config/default_config.py:50-53`

```python
class RateLimiter:
    def __init__(self, max_per_second: float = 2):
        ...
            await asyncio.sleep(random.uniform(0, 0.5))
```
-> `control/rate_limiter.py:6-28`

```python
class RetryHandler:
    def __init__(self, max_retries: int = 3):
        self.retry_delays = [1, 2, 5]
```
-> `control/retry_handler.py:11-16`

API session timeout: `aiohttp.ClientTimeout(total=30)` (`api_client.py:282`).

API retry delays: `[1, 2, 5]` (`api_client.py:401`).

Original probe timeout: `10` seconds (`downloader_base.py:1042`).

Live chunk: `65536` (`default_config.py:109`).

Resume/range for full video body download: **NOT FOUND** as general resume (Range only for original probe). Mirror list acts as multi-host retry.

Progress: `ProgressReporter` protocol — `update_step`, `set_item_total`, `advance_item` (`downloader_base.py:39-44`); CLI `cli/progress_display.py`.

### 4.F Config

**`config.example.yml` full** — already harvested (138 lines). Path: `_refs/douyin-downloader/config.example.yml`.

Key field → code:
| field | controls | reader |
|-------|----------|--------|
| `link` | job URLs | CLI/server |
| `path` | download root | FileManager |
| `video/music/cover/avatar/json` | asset toggles | BaseDownloader |
| `start_time/end_time` | date filter | user downloader |
| `filename_template/folder_template` | naming | utils/naming.py |
| `author_dir` | author folder style | file_manager |
| `mode/number/increase` | post/like/mix limits + incremental | strategies |
| `thread` | QueueManager workers | BaseDownloader.__init__ |
| `retry_times` | RetryHandler | config |
| `proxy` | aiohttp proxy | DouyinAPIClient |
| `video_quality` | bit_rate picker | downloader_base |
| `database/database_path` | sqlite history | storage/database.py |
| `cookies.*` | session | CookieManager / APIClient |
| `rate_limit` | RateLimiter max/s | default 2 |
| `live.*` | live recorder | live_downloader |
| `comments.*` | comment collector | comments_collector |
| `browser_fallback.*` | Playwright post list | api_client browser path |

### 4.G Errors

```python
_RISK_CONTROL_HTTP_STATUSES = frozenset({403, 429})
```
-> `api_client.py:46`

Empty HTTP 200 → anti-bot, ressign/retry (`api_client.py:437-458`).

`verify_ticket` → verify_page risk flag (`api_client.py:176`, `:592`).

`LoginRequiredError` status 2483 / 请先登录 / 用户未登录.

Homepage blocked markers in browser script: `验证码`, `安全验证`, `验证后继续`, `页面不存在`, `用户不存在`, `账号已注销` (`api_client.py:62-63`).

`filter_detail.filter_reason` e.g. `images_base` triggers aid retry (`api_client.py:652-661`).

### 4.H Batch / monitoring

SQLite schema:

```sql
CREATE TABLE IF NOT EXISTS aweme (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    aweme_id TEXT UNIQUE NOT NULL,
    aweme_type TEXT NOT NULL,
    title TEXT,
    author_id TEXT,
    author_name TEXT,
    create_time INTEGER,
    download_time INTEGER,
    file_path TEXT,
    metadata TEXT
);
CREATE TABLE IF NOT EXISTS download_history (...);
```
-> `storage/database.py:84-108`

Incremental: `increase.post` etc. + DB `is_downloaded` + local filesystem index (`_should_download`).

Metadata sidecar: `MetadataHandler.save_metadata` full JSON; `download_manifest.jsonl` append (`storage/metadata_handler.py:18-41`).

---

## 5. Consolidated endpoint table (all repos)

| purpose | full URL path | method | required query (min) | required headers | repos | file:line |
|---------|---------------|--------|----------------------|------------------|-------|-----------|
| aweme detail | `https://www.douyin.com/aweme/v1/web/aweme/detail/` | GET | `aweme_id`, base webapp params, `msToken`, `a_bogus`/`X-Bogus` | UA, Referer, Cookie | all | DD `api_client.py:641`; f2 `api.py:55`; DTDA `endpoints.py:55`; TTD `detail.py:21` **[GPL]** |
| user posts | `.../aweme/v1/web/aweme/post/` | GET | `sec_user_id`, `max_cursor`, `count` | same | all | DD `:683`; f2 `api.py:40`; DTDA `:37` |
| user profile | `.../user/profile/other/` | GET | `sec_user_id` | same | all | DD `:830`; f2 `:34`; DTDA `:31` |
| mix aweme | `.../mix/aweme/` | GET | `mix_id`, `cursor`, `count` | same | all | DD `:864`; f2 `:70`; DTDA `:73` |
| music detail/list | `.../music/detail/`, `.../music/aweme/` | GET | music id / cursor | same | DD, f2 | DD `:870-880` |
| comments | `.../comment/list/` | GET | `aweme_id`, `cursor`, `count` | same | all | DD `:1225`; DTDA `:133` |
| search | `.../general/search/single/` | GET | keyword + search_* | same | DD, f2, DTDA | DD `:1152` |
| live enter | `https://live.douyin.com/webcast/room/web/enter/` | GET | web_rid etc. | same | f2, DTDA, TTD | DTDA `:103` |
| live reflow | `https://webcast.amemv.com/webcast/room/reflow/info/` | GET | room_id | same | multi | DTDA `:106` |
| play no-WM | `https://www.douyin.com/aweme/v1/play/` | GET | `video_id`, `ratio`, `watermark=0`, signed | UA, Referer | DD | `downloader_base.py:1038` |
| legacy play | `https://aweme.snssdk.com/aweme/v1/play/?video_id=...` | GET | video_id, ratio | UA | DTDA hybrid | `hybrid_crawler.py:181` |
| short link | `https://v.douyin.com/...` | GET redirect | none | UA | all fetchers | DTDA `utils.py:429+`; DD `resolve_short_url` |
| ttwid register | `https://ttwid.bytedance.com/ttwid/union/register/` | POST | JSON region/aid | UA, Content-Type | f2, DTDA, TTD | conf / ttWid |
| msToken | `https://mssdk.bytedance.com/web/{report\|common\|r/token}` | POST | magic/strData JSON | UA, Content-Type | all | conf files |

**Web vs mobile:** Web path dominates (`aid=6383`, `device_platform=webapp`). DD also tries `aid=1128` (app-ish) for detail. Live reflow uses `webcast.amemv.com` (mobile webcast domain). No full Douyin **mobile app** protobuf API in these four for download.

---

## 6. PORT PLAN FOR OMNICAST

| capability | source repo | source file:line | license | difficulty | note |
|------------|-------------|------------------|---------|------------|------|
| ABogus + XBogus | douyin-downloader | `utils/abogus.py`, `utils/xbogus.py` | MIT | M | Prefer over GPL aBogus |
| API client sign+retry | douyin-downloader | `core/api_client.py` | MIT | M | Empty-200 / 403/429 / 2483 |
| Detail dual aid | douyin-downloader | `api_client.py:624-667` | MIT | S | |
| NWM URL + original probe | douyin-downloader | `downloader_base.py:925-1139` | MIT | M | Highest value |
| Quality picker | douyin-downloader | `downloader_base.py:1192-1240` | MIT | S | |
| Gallery/livephoto | douyin-downloader | `downloader_base.py:885-1327` | MIT | M | |
| msToken manager | douyin-downloader | `auth/ms_token_manager.py` | MIT | S | Vendor conf locally; don't fetch GitHub at runtime |
| Short URL resolve | douyin-downloader / f2 | url_parser + resolve | MIT/Apache | S | |
| SQLite aweme history | douyin-downloader | `storage/database.py` | MIT | S | Map into vault.db |
| Endpoint list cross-check | f2 + DTDA | api.py / endpoints.py | Apache | S | Attribution |
| Hybrid playwm rewrite | DTDA | hybrid_crawler.py:177-181 | Apache | S | Fallback only |
| bit_rate FPS sort idea | TikTokDownloader | extractor.py:514-540 | **GPL** | — | Clean-room reimplement only |
| X-Gnarly / TikTok | TikTokDownloader | encrypt/xGnarly.py | **GPL** | — | Out of OmniCast Douyin scope; describe-only |
| Live WSS JS sign | f2 | webcast_signature.js + execjs | Apache | H | Needs Node/execjs; optional |

### Wire-in sketch (primary: douyin-downloader as library)

```python
# Pseudocode for omnicast.media.providers.douyin
from core.api_client import DouyinAPIClient, LoginRequiredError
from core.url_parser import URLParser
from core.downloader_base import BaseDownloader  # or VideoDownloader
from core.video_downloader import VideoDownloader
from auth.cookie_manager import CookieManager
from auth.ms_token_manager import MsTokenManager

# 1) Parse share URL
parsed = URLParser.parse(url)  # -> {type, aweme_id, ...}

# 2) Session
async with DouyinAPIClient(cookies=cookie_dict, proxy=proxy) as client:
    # 3) Short link if needed
    # final = await client.resolve_short_url(url)

    # 4) Detail
    detail = await client.get_video_detail(parsed["aweme_id"])
    # detail: dict aweme_detail fields

    # 5) Download via VideoDownloader / BaseDownloader helpers
    # _build_video_url_candidates(detail)
    # _download_video_with_fallback(candidates, path, session)
```

Verbatim signatures:

```python
class DouyinAPIClient:
    BASE_URL = "https://www.douyin.com"
    def __init__(self, cookies: Dict[str, str], proxy: Optional[str] = None):
    async def get_video_detail(self, aweme_id: str, *, suppress_error: bool = False) -> Optional[Dict[str, Any]]:
    async def get_user_post(self, sec_uid: str, max_cursor: int = 0, count: int = 18) -> Dict[str, Any]:
    def build_signed_path(self, path: str, params: Dict[str, Any], *, base_url: Optional[str] = None, request_data: Optional[Dict[str, Any]] = None) -> Tuple[str, str]:
```
-> `_refs/douyin-downloader/core/api_client.py:232-363, 629, 669`

```python
class URLParser:
    @staticmethod
    def parse(url: str) -> Optional[Dict[str, Any]]:
```
-> `core/url_parser.py:11-13`

```python
    def _build_video_url_candidates(
        self, aweme_data: Dict[str, Any]
    ) -> List[Tuple[str, Dict[str, str]]]:
```
-> `core/downloader_base.py:925-927`

**Fallback f2:**

```python
from f2.apps.douyin.handler import DouyinHandler  # CLI-oriented
from f2.apps.douyin.utils import TokenManager, ABogusManager, AwemeIdFetcher
from f2.apps.douyin.filter import PostDetailFilter
```
`TokenManager.gen_real_msToken()`, `ABogusManager.model_2_endpoint(ua, base, params)`, `AwemeIdFetcher.get_aweme_id(url)`.

---

## 7. TRAPS / GOTCHAS

1. **X-Bogus alone is obsolete for many detail endpoints** (DTDA comment 2024-06-12); need `a_bogus`.
2. **msToken length diverges:** DTDA expects 120/128; f2/DD expect 164/184 — use matching generator.
3. **ABogus UA binding:** DTDA hardcodes UA SM3 bytes for Chrome/90; mismatch with runtime UA breaks sign.
4. **Empty HTTP 200** is anti-bot, not success (DD retries with new sign).
5. **403/429** edge WAF ≠ logout (DD comment); 2483 / 请先登录 is session death.
6. **bit_rate[0] ≠ best quality** (f2/DTDA TikTok path); DD/TTD sort properly — port DD sort.
7. **Original file** often missing from bit_rate list; only `ratio=default` play probe finds it.
8. **aid 6383 vs 1128** filters notes vs videos differently.
9. **PCDN hosts** after `/aweme/v1/play/` 302 may be dead; prefer direct `douyinvod` CDN URLs.
10. **playwm → play** string replace is legacy and may fail modern CDN URLs; keep as last resort.
11. **GPL contamination:** do not copy `TikTokDownloader/src/**` or its abogus into MIT/Apache tree without legal review; algorithms already dual-exist under MIT/Apache.
12. **Cookie freshness:** ttwid/msToken expire; rate_limit 2/s + jitter required.
13. **Captcha pages** (`verify_ticket`, 验证码 text) need human/browser_fallback — pure API cannot solve.
14. **Private/liked collections** need real `sessionid`; public detail may work with anonymous ttwid cookie set.
15. **f2 conf strData** bit-rots; pin a local copy of mssdk payload.

---

## 8. NOT FOUND

- NOT FOUND: WASM-based Douyin web sign in any of the four repos.
- NOT FOUND: active remote commercial sign API (TikHub is sponsor-only in READMEs, not wired as required).
- NOT FOUND: `mas` param usage for Douyin web in these four.
- NOT FOUND: `X-Gnarly` for Douyin (TikTok only, GPL repo).
- NOT FOUND: `_signature` actively set on Douyin web models (commented placeholders only).
- NOT FOUND: gear_name / quality_type ranking tables as explicit enums in DD (width/bit_rate used instead).
- NOT FOUND: full resume Range download in douyin-downloader media path (probe-only Range).
- NOT FOUND: structured region-block status code exclusive handler (generic HTTP/filter only).
- NOT FOUND: mobile Douyin app full API parity (no complete app endpoint suite for all four).

---

*End of V3_D1 harvest.*
