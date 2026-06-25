#!/usr/bin/env python3
"""freee 会計 API 本地客户端 — 自用单公司记账。

设计思路同 /Users/patrick/code/xy（自己不碰复杂协议），但 freee 有官方 API，
所以连浏览器都省了：纯 REST + OAuth2。token 6 小时过期，自动用 refresh_token 续
（freee 的 refresh_token 一次性，刷新后必须存回新的那个）。

零第三方依赖（只用 stdlib urllib）。所有写操作默认 dry-run，需 --commit 才真提交。

配置/凭据都在 ~/.config/freee/（不在任何 git 仓库里）：
    config.json   {client_id, client_secret, redirect_uri, company_id}
    token.json    {access_token, refresh_token, expires_at}
    cache/*.json   主数据缓存（account_items / partners / taxes / walletables）

用法见 README.md。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "freee"
CONFIG_PATH = CONFIG_DIR / "config.json"
TOKEN_PATH = CONFIG_DIR / "token.json"
CACHE_DIR = CONFIG_DIR / "cache"

AUTHZ_URL = "https://accounts.secure.freee.co.jp/public_api/authorize"
TOKEN_URL = "https://accounts.secure.freee.co.jp/public_api/token"
API_BASE = "https://api.freee.co.jp"
# freee デフォルトの OOB リダイレクト：認可後にコードを画面表示する。
DEFAULT_REDIRECT = "urn:ietf:wg:oauth:2.0:oob"
REFRESH_SKEW_S = 120  # 过期前 2 分钟就提前刷新


# --------------------------------------------------------------------------- #
# 低层：配置 / token / HTTP
# --------------------------------------------------------------------------- #
def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        sys.exit(
            f"缺少 {CONFIG_PATH}。先建 freee app 拿 client_id/secret，"
            f"再写入该文件（见 README.md「一次性设置」）。"
        )
    cfg = _read_json(CONFIG_PATH)
    cfg.setdefault("redirect_uri", DEFAULT_REDIRECT)
    return cfg


def _http(method: str, url: str, *, headers: dict, body: bytes | None = None) -> dict:
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")
        raise SystemExit(f"freee API {e.code} {url}\n{detail}") from e
    return json.loads(raw) if raw else {}


# --------------------------------------------------------------------------- #
# OAuth：登录 / 刷新 / 取有效 token
# --------------------------------------------------------------------------- #
def cmd_authurl(_args) -> None:
    cfg = load_config()
    q = urllib.parse.urlencode(
        {
            "response_type": "code",
            "client_id": cfg["client_id"],
            "redirect_uri": cfg["redirect_uri"],
        }
    )
    print("① 浏览器打开下面这个地址，登录并选择你的公司授权：\n")
    print(f"{AUTHZ_URL}?{q}\n")
    print("② 授权后页面会显示一串 authorization code，复制它，然后跑：")
    print("   python3 freee.py login --code <粘贴那串code>")


def _token_request(cfg: dict, form: dict) -> dict:
    body = urllib.parse.urlencode(form).encode("utf-8")
    tok = _http(
        "POST",
        TOKEN_URL,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        body=body,
    )
    # access 6h；用 expires_in 算绝对过期时刻。refresh_token 每次都换新，必须存回。
    tok["expires_at"] = int(time.time()) + int(tok.get("expires_in", 21600))
    _write_json(TOKEN_PATH, tok)
    return tok


def cmd_login(args) -> None:
    cfg = load_config()
    tok = _token_request(
        cfg,
        {
            "grant_type": "authorization_code",
            "client_id": cfg["client_id"],
            "client_secret": cfg["client_secret"],
            "code": args.code,
            "redirect_uri": cfg["redirect_uri"],
        },
    )
    print(f"✅ 已登录，token 存到 {TOKEN_PATH}（{tok.get('expires_in', '?')}s 后过期，会自动续）")


def refresh_token() -> dict:
    cfg = load_config()
    if not TOKEN_PATH.exists():
        sys.exit("还没登录。先 `python3 freee.py authurl` 走一次授权。")
    old = _read_json(TOKEN_PATH)
    return _token_request(
        cfg,
        {
            "grant_type": "refresh_token",
            "client_id": cfg["client_id"],
            "client_secret": cfg["client_secret"],
            "refresh_token": old["refresh_token"],
        },
    )


def cmd_refresh(_args) -> None:
    tok = refresh_token()
    print(f"🔄 已刷新，新 token 有效到 {time.ctime(tok['expires_at'])}")


def ensure_token() -> str:
    """返回一个有效 access_token，过期了自动刷新。"""
    if not TOKEN_PATH.exists():
        sys.exit("还没登录。先 `python3 freee.py authurl` 走一次授权。")
    tok = _read_json(TOKEN_PATH)
    if time.time() >= tok.get("expires_at", 0) - REFRESH_SKEW_S:
        tok = refresh_token()
    return tok["access_token"]


def _api_get(path: str, params: dict | None = None) -> dict:
    token = ensure_token()
    url = f"{API_BASE}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    return _http("GET", url, headers={"Authorization": f"Bearer {token}"})


def _api_post(path: str, payload: dict) -> dict:
    token = ensure_token()
    return _http(
        "POST",
        f"{API_BASE}{path}",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        body=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
    )


# --------------------------------------------------------------------------- #
# 主数据：拉公司 / 勘定科目 / 取引先 / 税区分 / 口座 并缓存
# --------------------------------------------------------------------------- #
def cmd_companies(_args) -> None:
    data = _api_get("/api/1/companies")
    for c in data.get("companies", []):
        print(f"  company_id={c['id']}  {c.get('display_name') or c.get('name')}")
    print("\n把你公司的 company_id 写进 ~/.config/freee/config.json 的 company_id 字段。")


def _company_id(cfg: dict) -> int:
    cid = cfg.get("company_id")
    if not cid:
        sys.exit("config.json 里还没 company_id。先 `python3 freee.py companies` 查到再填。")
    return int(cid)


def cmd_sync(_args) -> None:
    """拉主数据缓存到本地，供 skill 把名称映射成 id。"""
    cfg = load_config()
    cid = _company_id(cfg)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    # 注：这些 path 已按 freee 会計 API 命名；首次 sync 若某条 404/400，
    # 对着 https://developer.freee.co.jp/reference/accounting/reference 校正即可。
    targets = {
        "account_items": ("/api/1/account_items", {"company_id": cid}),
        "partners": ("/api/1/partners", {"company_id": cid, "limit": 3000}),
        "taxes": ("/api/1/taxes/codes", None),
        "walletables": ("/api/1/walletables", {"company_id": cid}),
        "items": ("/api/1/items", {"company_id": cid}),
        "sections": ("/api/1/sections", {"company_id": cid}),
    }
    for name, (path, params) in targets.items():
        try:
            data = _api_get(path, params)
        except SystemExit as e:
            print(f"  ⚠️  {name} 拉取失败：{e}")
            continue
        _write_json(CACHE_DIR / f"{name}.json", data)
        n = len(next((v for v in data.values() if isinstance(v, list)), []))
        print(f"  ✓ {name}: {n} 条 → cache/{name}.json")


# --------------------------------------------------------------------------- #
# 写入：创建取引（默认 dry-run）
# --------------------------------------------------------------------------- #
def cmd_deal(args) -> None:
    """从 JSON（--file 或 stdin）建一笔取引。

    输入 JSON 直接就是 freee deals 的 body（缺 company_id 时自动补）。
    示例见 README.md。默认只预览，加 --commit 才真写。
    """
    cfg = load_config()
    raw = Path(args.file).read_text(encoding="utf-8") if args.file else sys.stdin.read()
    body = json.loads(raw)

    # —— 必填字段体检（放在 company_id 解析前，没配 company_id 也能先验 JSON 结构）——
    missing = [k for k in ("issue_date", "type", "details") if k not in body]
    if missing:
        sys.exit(f"取引缺字段：{missing}（必填 issue_date / type(income|expense) / details[]）")
    if not body.get("details"):
        sys.exit("取引 details 不能为空。")

    body.setdefault("company_id", _company_id(cfg))

    print("—— 将要写入 freee 的取引 ——")
    print(json.dumps(body, ensure_ascii=False, indent=2))
    if not args.commit:
        print("\n[dry-run] 没有提交。确认无误后加 --commit 再跑一次。")
        return
    result = _api_post("/api/1/deals", body)
    deal = result.get("deal", result)
    print(f"\n✅ 已写入。deal_id={deal.get('id')}  金额={deal.get('amount')}")


def cmd_journal(args) -> None:
    """从 JSON（--file 或 stdin）建一张振替伝票（manual_journal）。

    用于借贷自定义的分录，如「借)通信費 / 貸)役員借入金」这种取引(deal)表达不了的。
    每条 details 需 entry_side(debit|credit) / account_item_id / tax_code / amount。
    借方合计必须等于贷方合计。默认只预览，加 --commit 才真写。
    """
    cfg = load_config()
    raw = Path(args.file).read_text(encoding="utf-8") if args.file else sys.stdin.read()
    body = json.loads(raw)

    missing = [k for k in ("issue_date", "details") if k not in body]
    if missing:
        sys.exit(f"振替伝票缺字段：{missing}（必填 issue_date / details[]）")
    if not body.get("details"):
        sys.exit("振替伝票 details 不能为空。")

    # —— 每条 detail 体检 + 借贷平衡 ——
    debit = credit = 0
    for i, d in enumerate(body["details"]):
        side = d.get("entry_side")
        if side not in ("debit", "credit"):
            sys.exit(f"details[{i}] 的 entry_side 必须是 debit 或 credit，当前={side!r}")
        for k in ("account_item_id", "tax_code", "amount"):
            if k not in d:
                sys.exit(f"details[{i}] 缺字段 {k}")
        debit += d["amount"] if side == "debit" else 0
        credit += d["amount"] if side == "credit" else 0
    if debit != credit:
        sys.exit(f"借贷不平：借方合计 {debit} ≠ 贷方合计 {credit}。请检查 details。")

    # company_id 放在校验之后解析：没配 company_id 时也能先验 JSON 结构与借贷平衡
    body.setdefault("company_id", _company_id(cfg))

    print("—— 将要写入 freee 的振替伝票 ——")
    print(json.dumps(body, ensure_ascii=False, indent=2))
    print(f"\n借方合计={debit}  贷方合计={credit}（已平衡）")
    if not args.commit:
        print("\n[dry-run] 没有提交。确认无误后加 --commit 再跑一次。")
        return
    result = _api_post("/api/1/manual_journals", body)
    mj = result.get("manual_journal", result)
    print(f"\n✅ 已写入。manual_journal_id={mj.get('id')}")


# --------------------------------------------------------------------------- #
# 証憑 / ファイルボックス：上传 PDF、补附到已存在的取引/振替伝票（電帳法）
# --------------------------------------------------------------------------- #
_MULTIPART_BOUNDARY = "----xyFreeeBoundaryR3c31ptF1l3B0x"


def _api_put(path: str, payload: dict) -> dict:
    token = ensure_token()
    return _http(
        "PUT",
        f"{API_BASE}{path}",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        body=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
    )


def _load_cache(name: str) -> dict:
    p = CACHE_DIR / f"{name}.json"
    return _read_json(p) if p.exists() else {}


def _account_name_map() -> dict:
    return {a["id"]: a.get("name", "") for a in _load_cache("account_items").get("account_items", [])}


def _upload_receipt(file_path: Path, *, description: str | None, issue_date: str | None) -> dict:
    """POST /api/1/receipts（multipart）把文件传进 ファイルボックス，返回 receipt。"""
    cfg = load_config()
    cid = _company_id(cfg)
    content = file_path.read_bytes()
    fields = {"company_id": str(cid)}
    if description:
        fields["description"] = description
    if issue_date:
        # 注：freee 已逐步弃用 receipts POST 的 issue_date；仅在显式指定时发送。
        fields["issue_date"] = issue_date

    token = ensure_token()
    b = _MULTIPART_BOUNDARY
    parts: list[bytes] = []
    for k, v in fields.items():
        parts.append(
            f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
        )
    parts.append(
        f'--{b}\r\nContent-Disposition: form-data; name="receipt"; '
        f'filename="{file_path.name}"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode()
    )
    parts.append(content)
    parts.append(f"\r\n--{b}--\r\n".encode())
    return _http(
        "POST",
        f"{API_BASE}/api/1/receipts",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": f"multipart/form-data; boundary={b}",
        },
        body=b"".join(parts),
    )


def cmd_receipt(args) -> None:
    resp = _upload_receipt(Path(args.file), description=args.memo, issue_date=args.date)
    rec = resp.get("receipt", resp)
    print(f"✅ 已上传 ファイルボックス。receipt_id={rec.get('id')}  文件={Path(args.file).name}")
    print("   把这个 id 放进伝票的 receipt_ids，或用 `attach` 直接补到已存在的伝票。")


def cmd_journals(args) -> None:
    """列出振替伝票，便于把 PDF 对到伝票。[📎n]=已附 n 个证憑。"""
    cfg = load_config()
    cid = _company_id(cfg)
    params: dict = {"company_id": cid, "limit": args.limit}
    if args.since:
        params["start_issue_date"] = args.since
    if args.until:
        params["end_issue_date"] = args.until
    data = _api_get("/api/1/manual_journals", params)
    names = _account_name_map()
    for mj in data.get("manual_journals", []):
        lines = [
            f"{'借' if d.get('entry_side') == 'debit' else '贷'}){names.get(d.get('account_item_id'), d.get('account_item_id'))} {d.get('amount')}"
            for d in mj.get("details", [])
        ]
        rids = mj.get("receipt_ids") or []
        flag = f"📎{len(rids)}" if rids else "—"
        descs = " / ".join(d.get("description", "") for d in mj.get("details", []) if d.get("description"))
        print(f"  id={mj.get('id')}  {mj.get('issue_date')}  [{flag}]  {'  '.join(lines)}  {descs}")


def cmd_attach(args) -> None:
    """把 PDF 补附到已存在的振替伝票/取引：GET→合并 receipt_ids→PUT。

    更新接口要求重发整张伝票（issue_date+details），本命令自动 GET 后整体回写，
    你只给伝票 id + PDF。默认 dry-run，--commit 才真写。
    """
    cfg = load_config()
    cid = _company_id(cfg)
    if not args.journal and not args.deal:
        sys.exit("必须指定 --journal <id> 或 --deal <id>。")
    files = list(args.file or [])
    new_ids = [int(x) for x in (args.receipt or [])]
    if not files and not new_ids:
        sys.exit("必须指定 --file <pdf...>（上传）或 --receipt <id...>（已有证憑）。")

    # 1) 上传待附文件，收集 receipt_ids（dry-run 不上传，仅提示）
    if files:
        if args.commit:
            for f in files:
                r = _upload_receipt(Path(f), description=args.memo, issue_date=args.date).get("receipt", {}).get("id")
                new_ids.append(r)
                print(f"  ↑ {Path(f).name} → receipt_id={r}")
        else:
            for f in files:
                print(f"  [dry-run] --commit 时上传并追加：{Path(f).name}")

    # 2) GET 现有记录，合并 receipt_ids，整体 PUT 回写
    if args.journal:
        rec = _api_get(f"/api/1/manual_journals/{args.journal}", {"company_id": cid}).get("manual_journal", {})
        keys = ("id", "entry_side", "account_item_id", "tax_code", "amount",
                "vat", "partner_id", "item_id", "section_id", "tag_ids", "description")
        body = {
            "company_id": cid,
            "issue_date": rec.get("issue_date"),
            "details": [{k: d[k] for k in keys if d.get(k) is not None} for d in rec.get("details", [])],
        }
        if "adjustment" in rec:
            body["adjustment"] = rec["adjustment"]
        target, label = f"/api/1/manual_journals/{args.journal}", "振替伝票"
    else:
        rec = _api_get(f"/api/1/deals/{args.deal}", {"company_id": cid}).get("deal", {})
        keys = ("id", "account_item_id", "tax_code", "amount", "vat",
                "item_id", "section_id", "tag_ids", "description")
        body = {
            "company_id": cid,
            "issue_date": rec.get("issue_date"),
            "type": rec.get("type"),
            "details": [{k: d[k] for k in keys if d.get(k) is not None} for d in rec.get("details", [])],
        }
        if rec.get("partner_id"):
            body["partner_id"] = rec["partner_id"]
        target, label = f"/api/1/deals/{args.deal}", "取引"

    existing = list(rec.get("receipt_ids") or [])
    body["receipt_ids"] = sorted(set(existing + new_ids))

    tail = "（+待上传文件）" if (files and not args.commit) else ""
    print(f"—— 将更新{label} id={args.journal or args.deal}：receipt_ids {existing} → "
          f"{body['receipt_ids']}{tail} ——")
    print(json.dumps(body, ensure_ascii=False, indent=2))
    if not args.commit:
        print("\n[dry-run] 没有提交。确认后加 --commit。")
        return
    _api_put(target, body)
    print(f"\n✅ 已补附。{label} id={args.journal or args.deal} 现 receipt_ids={body['receipt_ids']}")


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main() -> None:
    p = argparse.ArgumentParser(description="freee 会計 本地记账客户端")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("authurl", help="打印 OAuth 授权地址").set_defaults(func=cmd_authurl)

    sp = sub.add_parser("login", help="用授权 code 换 token")
    sp.add_argument("--code", required=True)
    sp.set_defaults(func=cmd_login)

    sub.add_parser("refresh", help="手动刷新 token").set_defaults(func=cmd_refresh)
    sub.add_parser("companies", help="列出可访问的公司及 company_id").set_defaults(func=cmd_companies)
    sub.add_parser("sync", help="拉主数据缓存到本地").set_defaults(func=cmd_sync)

    sp = sub.add_parser("deal", help="建一笔取引（默认 dry-run）")
    sp.add_argument("--file", help="取引 JSON 文件；省略则读 stdin")
    sp.add_argument("--commit", action="store_true", help="真正提交（否则仅预览）")
    sp.set_defaults(func=cmd_deal)

    sp = sub.add_parser("journal", help="建一张振替伝票/手动分录（默认 dry-run）")
    sp.add_argument("--file", help="振替伝票 JSON 文件；省略则读 stdin")
    sp.add_argument("--commit", action="store_true", help="真正提交（否则仅预览）")
    sp.set_defaults(func=cmd_journal)

    sp = sub.add_parser("receipt", help="上传 PDF 到 ファイルボックス，返回 receipt_id")
    sp.add_argument("--file", required=True, help="要上传的文件（PDF/图片）")
    sp.add_argument("--date", help="取引日 yyyy-mm-dd（可选，freee 渐弃用）")
    sp.add_argument("--memo", help="备注（≤255字）")
    sp.set_defaults(func=cmd_receipt)

    sp = sub.add_parser("journals", help="列出振替伝票（便于把 PDF 对到伝票）")
    sp.add_argument("--since", help="start_issue_date yyyy-mm-dd")
    sp.add_argument("--until", help="end_issue_date yyyy-mm-dd")
    sp.add_argument("--limit", type=int, default=50)
    sp.set_defaults(func=cmd_journals)

    sp = sub.add_parser("attach", help="把 PDF 补附到已存在的振替伝票/取引（默认 dry-run）")
    sp.add_argument("--journal", help="振替伝票 id")
    sp.add_argument("--deal", help="取引 id")
    sp.add_argument("--file", nargs="*", help="要上传并附上的 PDF（可多个）")
    sp.add_argument("--receipt", nargs="*", help="已有 receipt_id（可多个）")
    sp.add_argument("--date", help="上传时取引日（可选）")
    sp.add_argument("--memo", help="上传时备注（可选）")
    sp.add_argument("--commit", action="store_true", help="真正写入（否则仅预览）")
    sp.set_defaults(func=cmd_attach)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
