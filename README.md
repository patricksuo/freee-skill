# freee 会計 本地记账工具（Claude Code skill）

把口述的一笔账录进 freee。因为 freee 有官方 API，不走浏览器/逆向，只有一个零依赖
`freee.py`（REST + OAuth2）+ `/freee` skill：自然语言 → 映射科目 → dry-run 预览 →
确认后写入。支持取引(deal)、振替伝票(manual_journal)、以及把 PDF 证憑附到伝票（電帳法）。

## 安装

```sh
git clone git@github.com:patricksuo/freee-skill.git ~/.claude/skills/freee
```
Claude Code 启动时会自动加载该 skill（`/freee`）。然后按下面做一次性设置。

## 一次性设置

只有两件事必须**你本人在浏览器里做**（它们在你的 freee 登录态背后，Claude 登不进你的账号）：

- **A. 建 app 拿钥匙**：登录 <https://app.secure.freee.co.jp/developers/applications>，
  新建一个 app（自用，**不必**提交公开审核），回调 URL 填 `urn:ietf:wg:oauth:2.0:oob`，
  复制 **client_id** 和 **client_secret**。
- **B. 点同意拿 code**：在授权页面登录、点「同意」，复制页面显示的那串授权 code。

**其余 Claude 都能代跑**——你把上面的 client_id/secret 和 code 贴给它即可。整套流程是：

```sh
# 1) 写凭据文件（你给字符串，Claude 可代写；绝不进 git）
mkdir -p ~/.config/freee && chmod 700 ~/.config/freee
cat > ~/.config/freee/config.json <<'JSON'
{ "client_id": "...", "client_secret": "...", "redirect_uri": "urn:ietf:wg:oauth:2.0:oob" }
JSON
chmod 600 ~/.config/freee/config.json

# 2) Claude 跑这条，打印授权地址 → 你照「B」拿到 code
python3 ~/.claude/skills/freee/freee.py authurl

# 3) 你给 code，Claude 跑剩下这些：换 token → 查 company_id → 拉缓存
python3 ~/.claude/skills/freee/freee.py login --code <你贴的 code>
python3 ~/.claude/skills/freee/freee.py companies   # 拿到 company_id 填回 config.json
python3 ~/.claude/skills/freee/freee.py sync         # 把科目/取引先等抓到本地
```

完成后 token 自动续期，平时不用再管。只有 refresh token 也过期了，才需重跑第 2、3 步。

## 日常用法
直接跟我（Claude）说，比如：
> 「6/20 收到 shukudai 平台手数料 12000 円，记一笔」

`/freee` skill 会用本地缓存的科目档案把「手数料」对成对应科目，**先把要记的账打给你看（dry-run）**，确认后才真正提交。

## 文件位置
- `freee.py` / `SKILL.md` / `README.md` —— 本目录（可进 git）
- `~/.config/freee/config.json` `token.json` `cache/` —— 凭据与缓存，**绝不进 git**

## 安全
- access_token 6 小时过期，refresh_token 一次性、刷新即换新（`freee.py` 已处理存回）
- 所有写操作默认 dry-run，需 `--commit` 才真写

## License
MIT — 见 [LICENSE](LICENSE)。
