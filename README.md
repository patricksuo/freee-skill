# freee 会計 本地记账工具（Claude Code skill）

把口述的一笔账录进 freee。因为 freee 有官方 API，不走浏览器/逆向，只有一个零依赖
`freee.py`（REST + OAuth2）+ `/freee` skill：自然语言 → 映射科目 → dry-run 预览 →
确认后写入。支持取引(deal)、振替伝票(manual_journal)、以及把 PDF 证憑附到伝票（電帳法）。

## 安装

```sh
git clone git@github.com:patricksuo/freee-skill.git ~/.claude/skills/freee
```
Claude Code 启动时会自动加载该 skill（`/freee`）。然后按下面做一次性设置。

## 一次性设置（只你能做，约 10 分钟）

### 1. 建 freee app 拿钥匙
1. 登录 <https://app.secure.freee.co.jp/developers/applications>（freee アプリストア → 开发者）
2. 新建 app（自用即可，**不需要**提交公开审核）
3. 回调 URL 填 `urn:ietf:wg:oauth:2.0:oob`
4. 记下 **client_id** 和 **client_secret**

### 2. 写凭据文件（不进任何 git）
```sh
mkdir -p ~/.config/freee
cat > ~/.config/freee/config.json <<'JSON'
{
  "client_id": "粘贴你的 client_id",
  "client_secret": "粘贴你的 client_secret",
  "redirect_uri": "urn:ietf:wg:oauth:2.0:oob"
}
JSON
chmod 600 ~/.config/freee/config.json
```

### 3. 授权你自己的公司
```sh
cd ~/.claude/skills/freee
python3 freee.py authurl          # 打印授权地址 → 浏览器打开登录授权 → 复制 code
python3 freee.py login --code <粘贴那串code>
python3 freee.py companies        # 查到 company_id，填回 config.json 的 "company_id"
python3 freee.py sync             # 拉主数据缓存
```

完成后 token 会自动续期，平时不用再管。失效（refresh 也过期）才需重跑第 3 步。

## 日常用法
直接跟我（Claude）说，比如：
> 「6/20 收到 shukudai 平台手数料 12000 円，记一笔」

`/freee` skill 会读主数据把「手数料」映射成科目，**先 dry-run 给你看**，确认后才提交。

## 文件位置
- `freee.py` / `SKILL.md` / `README.md` —— 本目录（可进 git）
- `~/.config/freee/config.json` `token.json` `cache/` —— 凭据与缓存，**绝不进 git**

## 安全
- access_token 6 小时过期，refresh_token 一次性、刷新即换新（`freee.py` 已处理存回）
- 所有写操作默认 dry-run，需 `--commit` 才真写
