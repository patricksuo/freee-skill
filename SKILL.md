---
name: freee
description: 把自然语言的一笔账录进 freee 会計（单公司自用）。当用户说要记账、入账、录一笔取引/収入/支出、振替伝票/借贷分录、freee、登记手数料/收入/费用、垫付/役員借入金、"记到 freee"、"这笔进账""这笔花销"之类时触发。底层调用本目录的 freee.py（freee 官方 API，token 自动续），默认 dry-run 预览、确认后才提交。
---

# freee 会計 记账

把用户口述的一笔交易，转成 freee 的**取引(deal)** 或 **振替伝票(manual_journal)** 写进账。底层是同目录 `freee.py`（freee 官方 REST API，token 自动刷新）。

## 前提
凭据在 `~/.config/freee/`（config.json + token.json）。若 `freee.py` 报「缺 config / 还没登录」，引导用户看本目录 `README.md` 的「一次性设置」，不要自己瞎猜 client_id。

## ★ 第 0 步：先判定用 deal 还是 journal

| 用哪种 | 适用 | 例子 |
|---|---|---|
| **deal（取引）** | 有实际收/付款、有对手方、**结算到某个口座**的日常收入/支出 | 收到平台手数料并入到某口座；公司卡付服务器费 |
| **journal（振替伝票）** | 借或贷**有一方不是口座科目**，或纯账户间结转/计提 | 你个人垫付公司开销（借)費用 / 贷)役員借入金）；计提未払金/前受金；決算整理；口座间振替 |

一句话：**钱真的从某个口座进出 → deal；否则（含役員借入金这种欠款）→ journal。** 拿不准就问用户。

## 记一笔账的标准流程

1. **主数据新鲜**：`~/.config/freee/cache/` 不存在、或涉及新科目/新取引先 → 先 `python3 ~/.claude/skills/freee/freee.py sync`。
2. **判定 deal / journal**（见上）。
3. **名称→id 映射**：读 `cache/account_items.json`(勘定科目)、`cache/taxes.json`(税区分)、`cache/partners.json`(取引先)、`cache/walletables.json`(口座)，把「手数料」「役員借入金」「課税仕入10%」等映射成 `id`/`tax_code`。匹配不唯一或找不到 → **问用户**，不要猜。
4. **拼 JSON** 写临时文件。
5. **dry-run**：`freee.py deal --file f.json` 或 `freee.py journal --file f.json`。把预览 JSON **翻成中文**给用户看（日期/借贷或收支/科目名/金额/税区分），请其确认。
6. **确认后提交**：同命令加 `--commit`，报回 id。

> 记账写错就要改账——**永远先 dry-run 给用户看，得到明确「确认/提交」才 --commit**。一次一笔，除非用户明确要批量。

## deal JSON（freee /api/1/deals）

```json
{
  "issue_date": "2026-06-20",
  "type": "income",
  "partner_id": 12345,
  "details": [
    { "account_item_id": 678, "tax_code": 21, "amount": 12000, "description": "shukudai 手数料" }
  ]
}
```
- `type`: `income`(収入) / `expense`(支出)；`amount`: 含税总额（円，整数）
- `tax_code`: 取自 `cache/taxes.json`，拿不准用该科目的 `default_tax_code`
- `company_id` 由 freee.py 自动补

## journal JSON（freee /api/1/manual_journals）

借贷自定义分录。**借方合计必须等于贷方合计（税込）**，freee.py 会本地预检。

```json
{
  "issue_date": "2026-06-20",
  "adjustment": false,
  "details": [
    { "entry_side": "debit",  "account_item_id": 111, "tax_code": 21, "amount": 1100, "description": "○○订阅" },
    { "entry_side": "credit", "account_item_id": 222, "tax_code": 0,  "amount": 1100, "description": "役員立替" }
  ]
}
```
- `entry_side`: `debit`(借) / `credit`(贷)；`amount`: 税込（整数）
- **税区分纪律**：负债/转账类科目（如 `役員借入金`/`未払金`）的那一行用「**対象外/不課税**」的 tax_code（多为 `0`，以 `cache/taxes.json` 为准），别误套課税
- 始终带 `"adjustment": false`（除非是決算整理仕訳才设 true）
- `company_id` 由 freee.py 自动补

> 典型「个人垫付」：借)費用科目(課税仕入) / 贷)役員借入金(対象外)，金额相等。

## 証憑 / 電帳法：把 PDF 附到伝票（ファイルボックス）

電子帳簿保存法：把请求书/领収书 PDF 存进 freee ファイルボックス 并钉到对应伝票。

- **新账一条龙**：先 `receipt --file x.pdf` 上传拿 `receipt_id` → 建 deal/journal 时在 JSON 里加 `"receipt_ids": [<id>]`。
- **给已存在伝票补 PDF**：`attach --journal <id> --file a.pdf b.pdf --commit`。它会 GET 该伝票 → 原样重发明细 → 只往 receipt_ids 追加（一次可附多份；取引用 `--deal <id>`）。
- 找伝票 id：`journals --since 2025-10-01 --until 2026-06-30`（`📎n` = 已附 n 份）。
- **写前务必 dry-run**：attach 会忠实保留原明细（detail id/科目/税区分/金额/vat），只改 receipt_ids；不破坏账。批量改真实账目前先备份（GET 存盘）。

## CLI 速查
- `freee.py authurl` / `login --code` — 一次性授权
- `freee.py companies` — 查 company_id
- `freee.py sync` — 刷新主数据缓存
- `freee.py deal --file f.json [--commit]` — 建取引（默认仅预览）
- `freee.py journal --file f.json [--commit]` — 建振替伝票（默认仅预览）
- `freee.py receipt --file x.pdf [--memo ..]` — 上传 PDF 到 ファイルボックス，返回 receipt_id
- `freee.py journals [--since --until]` — 列出振替伝票（📎=已附证憑）
- `freee.py attach --journal <id> --file a.pdf [b.pdf] [--commit]` — 给已存在伝票补附 PDF（默认 dry-run）
