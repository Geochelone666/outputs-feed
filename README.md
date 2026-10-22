# 公开产出 Feed

此仓库保存供外部页面读取的 JSON 快照，不包含生成程序。

## 文件

- `feed.json`：`updated` 表示产出列表更新时间，`outputs` 保存公开条目。条目包含稳定 `id`、时间 `ts`、项目、标题、类型、链接和摘要。
- `live-status.json`：`updated_utc` 表示状态快照更新时间，与产出列表更新时间独立。当前包含机器可达性、负载、内存、定时任务数量和产出计数。

两个文件的时间不同并不自动表示故障。读取方应显示各自的更新时间；旧快照不能被当作当前实时状态。`reachable` 只表示生成快照时的检查结果。

## 发布约定

这里的文件及 Git 历史均公开。生成端只应输出已批准公开的条目和汇总状态，不应包含凭据、个人资料、私有文件路径或内部网络地址。当前机器名称和运行指标也属于公开信息；需要减少字段时，应先修改外部生成端和消费端，再更新本仓库，避免下一次自动更新恢复旧字段。

更新时应先完整生成并验证 JSON，再替换文件。保持条目 ID 稳定，使用带时区的 ISO 8601 时间，并确保公开链接可访问。不要仅为表示程序仍在运行而改写 `feed.json` 的产出更新时间。

## 格式与校验

字段定义见 JSON Schema（Draft 2020-12）：

- `schema/feed.schema.json`
- `schema/live-status.schema.json`

Schema 允许额外字段，便于生成端新增数据而不破坏读取方；删除或改名字段前应先更新消费端。

`scripts/validate.py` 只依赖 Python 标准库，生成端可在替换文件前运行：

```bash
python3 scripts/validate.py            # 校验本仓库
python3 scripts/validate.py /path/dir  # 校验其他目录中的新快照
```

除 Schema 规则外，它还检查：条目 `id` 不重复、`updated_utc` 为 UTC、`mem` 与输出计数一致，
以及文件中不含内网/Tailscale IP、本地路径、私钥或令牌。`live-status.json` 的 `outputs.public`
与 `feed.json` 条目数不一致时只给出警告（两个文件独立生成）。返回码：0 通过，1 有错误。

测试：`python3 -m unittest discover -s tests`。GitHub Actions（`.github/workflows/validate.yml`）
在每次推送时运行校验和测试。

## 许可

本仓库尚未指定开源或数据许可证；公开访问不代表授予数据再分发许可。各外部链接内容遵循其各自的使用条款。
