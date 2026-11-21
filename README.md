# memory-recon

给 agent 的会话库做**记忆对账**：把"聊过、但没落成文件"的决定找出来。

> 迁移搬得走文件，搬不走对话。

## 它解决什么问题

agent 用了几个月，记忆文件几百个，看着挺全。但总有些东西你记得说过、就是搜不到。

原因不复杂：**结论会被写下来，过程不会。**

你拍板时说一句"记住"，模型就写一篇记忆；你问"流程是什么"，它答一篇，你点头，然后这段就只活在对话里了。换产品、换机器、清会话，全都丢。

这个技能干一件事：扫会话库 → 抽候选 → 核到记忆库 → 输出缺失清单。

## 安装

放到你的技能目录即可，任选其一：

```bash
git clone https://github.com/istoolsfox/memory-recon.git ~/.agents/skills/memory-recon
# 或
git clone https://github.com/istoolsfox/memory-recon.git ~/.claude/skills/memory-recon
```

零依赖，Python 3.8+，只用标准库。

## 用法

```bash
python3 scripts/recon.py \
  --db ~/.zcode/cli/db/db.sqlite \
  --memory ~/workspace/.dsh/memory \
  --memory ~/workspace/AGENTS.md \
  --out report.md
```

输出：

```markdown
| 日期 | 会话 | 摘要 | 覆盖 |
|---|---|---|---|
| 2026-09-11 | GitHub修Bug流程探讨 | 你现在修bug的流程是什么… | 0.00 |
| 2026-09-23 | 查询语音识别资源包 | 以后记住，播放视频不要出声… | 1.00 |
```

`覆盖` 是候选里的英文实体在记忆库里出现的比例。0.00 最可疑，但要人工确认——中文主题会被误判。

支持两种数据源：

- `--db`：ZCode 的 `db.sqlite`（只读）
- `--jsonl`：任意会话导出，每行 `{"ts": ..., "text": ...}`

## 怎么判定

每条候选问两个问题：

1. 下次会话还会不会用到？
2. 这是结论，还是过程？

过程类（多步流程、判据、验证方法）优先级最高，因为它最不容易被写下来。

四种结果：已覆盖 / 部分覆盖 / 缺失 / 一次性。

## 实测

790 个会话、3279 条真人输入、451 条决策候选，全量扫完约 3 秒。一次真实对账里，25 条长期决定有 1 条完全缺失——正好是一套只在对话里讲过的流程。

细节见 [`references/method.md`](references/method.md)。

## 局限

- 覆盖率只认英文/数字实体，纯中文主题会漏判
- 找不出"从没提过要记住"的隐性知识
- 只回答"有没有"，不回答"还对不对"
- 扫不了没留存的对话

## 许可

MIT
