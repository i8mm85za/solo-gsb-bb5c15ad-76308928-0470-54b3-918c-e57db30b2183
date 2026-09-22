# 多轨录音节拍对齐 API

基于 **Python + FastAPI + SQLite** 的节拍对齐服务。客户端提交**参考节拍网格**与**演奏轨的音符起始时间（onset）**，服务端使用**带宽约束的动态时间规整（Sakoe-Chiba Band DTW）**处理演奏中的**漏拍、抢拍（提前）与插入拍**，回溯最优规整路径后生成：

- **一一对应映射（pairs）**：每个参考拍匹配到哪个 onset、偏差多少毫秒；未匹配的参考拍标记为 `missing_beat`（漏拍），未匹配的 onset 标记为 `inserted_beat`（插入拍）。
- **连续偏差区间（intervals）**：把连续匹配拍按偏差方向切分成 `rushed`（抢拍/偏早）、`dragging`（拖拍/偏晚）、`steady`（稳定）区间，并给出每段的均值/极值/标准差。

## 目录结构

```
.
├── app/
│   ├── main.py        # FastAPI 路由：创建 / 对齐 / 查询
│   ├── dtw.py         # 带宽约束 DTW 核心算法（纯标准库）
│   ├── service.py     # 对齐执行与结果序列化
│   ├── schemas.py     # Pydantic 请求/响应模型
│   └── database.py    # SQLite 连接与建表
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

## 一键启动（Docker Compose）

```bash
docker compose up --build -d
```

- 服务端口：**`8000`**（宿主机 `http://localhost:8000`）
- SQLite 数据文件：容器内 `/data/alignments.db`，通过命名卷 `align-data` 持久化
- 停止：`docker compose down`（加 `-v` 同时删除数据卷）

交互式文档：

- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## 本地运行（可选）

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
ALIGN_DB_PATH=./alignments.db uvicorn app.main:app --reload --port 8000
```

## 算法说明

代价均以毫秒计，在 Sakoe-Chiba 带 `|i - j| <= band` 内做 DP：

| 路径步 | 含义 | 代价 |
| --- | --- | --- |
| 对角 | 参考拍 i 匹配 onset j | `|O[j] - R[i]|` |
| 向下 | 漏拍（参考拍无对应 onset） | `gap_penalty_ms` |
| 向右 | 插入拍（多余 onset） | `gap_penalty_ms` |

采用**半全局（semi-global / 非锚定端点）DTW**：可从顶边或左边免费进入、在底边或右边选最优终点退出，因此片段开头/结尾的漏拍与插入拍（迟到起拍、开头装饰音、提前结束、尾音）不收费；要求路径必须覆盖完整参考网格或完整 onset 序列，避免两侧同时大量丢弃。回溯到边后，未覆盖的首尾拍分别标注为漏拍/插入拍。

- **band**：带宽（节拍索引半径，默认 `2`），约束匹配只可能发生在索引相近的拍之间，`|i - j| <= band`；
- **gap_penalty_ms**：漏拍/插入拍的附加代价（默认 `200ms`），防止路径免费跨越长时停顿；
- **deviation_threshold_ms**：抢拍/拖拍判定阈值（默认 `50ms`）：偏差 `< -50ms` 为 `rushed`，`> +50ms` 为 `dragging`，之间为 `steady`。

路径在底边/右边的最优终点结束、向边回溯，首尾未覆盖的拍/onset 免费标注为漏拍或插入拍，最终输出一一对应映射与连续偏差区间。

## API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `POST` | `/jobs` | 创建对齐任务（输入参考网格、onset、参数） |
| `POST` | `/jobs/{id}/align` | 执行对齐，可用请求体覆盖参数 |
| `GET`  | `/jobs/{id}` | 查询任务与对齐结果 |
| `GET`  | `/jobs` | 任务列表 |
| `GET`  | `/health` | 健康检查 |

## 示例请求

参考为 120 BPM 的 8 拍网格（每拍 500ms）；演奏在开头插入一个装饰音，第 4 拍（1500ms）漏掉，第 3 拍抢拍，后半段整体偏晚：

```bash
# 1) 创建任务
curl -s -X POST http://localhost:8000/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "name": "track-01 take 3",
    "reference_beats_ms": [0, 500, 1000, 1500, 2000, 2500, 3000, 3500],
    "onset_times_ms": [-220, 10, 455, 940, 2055, 2560, 3055, 3552],
    "band": 2,
    "gap_penalty_ms": 200.0,
    "deviation_threshold_ms": 50.0
  }'
```

响应（`201 Created`，节选）：

```json
{
  "id": "ab12...",
  "status": "pending",
  "params": { "band": 2, "gap_penalty_ms": 200.0, "deviation_threshold_ms": 50.0 }
}
```

```bash
# 2) 执行对齐（参数可选，不传则沿用创建时的值）
curl -s -X POST http://localhost:8000/jobs/ab12.../align \
  -H "Content-Type: application/json" -d '{}'
```

结果包含映射、偏差区间与统计：

```json
{
  "status": "aligned",
  "pairs": [
    { "ref_index": null, "onset_index": 0, "ref_time_ms": null, "onset_time_ms": -220.0, "deviation_ms": null, "kind": "inserted_beat" },
    { "ref_index": 0, "onset_index": 1, "ref_time_ms": 0.0,    "onset_time_ms": 10.0,   "deviation_ms": 10.0,  "kind": "match" },
    { "ref_index": 1, "onset_index": 2, "ref_time_ms": 500.0,  "onset_time_ms": 455.0,  "deviation_ms": -45.0, "kind": "match" },
    { "ref_index": 2, "onset_index": 3, "ref_time_ms": 1000.0, "onset_time_ms": 940.0,  "deviation_ms": -60.0, "kind": "match" },
    { "ref_index": 3, "onset_index": null, "ref_time_ms": 1500.0, "onset_time_ms": null, "deviation_ms": null, "kind": "missing_beat" },
    { "ref_index": 4, "onset_index": 4, "ref_time_ms": 2000.0, "onset_time_ms": 2055.0, "deviation_ms": 55.0,  "kind": "match" },
    { "ref_index": 5, "onset_index": 5, "ref_time_ms": 2500.0, "onset_time_ms": 2560.0, "deviation_ms": 60.0,  "kind": "match" },
    { "ref_index": 6, "onset_index": 6, "ref_time_ms": 3000.0, "onset_time_ms": 3055.0, "deviation_ms": 55.0,  "kind": "match" },
    { "ref_index": 7, "onset_index": 7, "ref_time_ms": 3500.0, "onset_time_ms": 3552.0, "deviation_ms": 52.0,  "kind": "match" }
  ],
  "intervals": [
    { "kind": "steady",   "ref_start_index": 0, "ref_end_index": 1, "beat_count": 2, "mean_deviation_ms": -17.5 },
    { "kind": "rushed",   "ref_start_index": 2, "ref_end_index": 2, "beat_count": 1, "mean_deviation_ms": -60.0 },
    { "kind": "dragging", "ref_start_index": 4, "ref_end_index": 7, "beat_count": 4, "mean_deviation_ms": 55.5 }
  ],
  "stats": {
    "matched_beats": 7,
    "missing_beats": 1,
    "inserted_beats": 1,
    "mean_deviation_ms": 18.143,
    "std_deviation_ms": 47.472,
    "total_cost": 537.0,
    "band": 2,
    "gap_penalty_ms": 200.0,
    "deviation_threshold_ms": 50.0
  }
}
```

> 说明：示例中 `-220ms` 的装饰音被识别为 `inserted_beat`（无对应参考拍），参考第 3 拍（1500ms）无对应 onset 被标记为 `missing_beat`；前 2 拍偏差在阈值内为 `steady`，第 3 拍提前 60ms 为 `rushed`，漏拍打断区间后，后 4 拍偏差均超过 +50ms 形成连续 `dragging` 区间。

```bash
# 3) 查询结果（随时可重复查询，结果持久化在 SQLite）
curl -s http://localhost:8000/jobs/ab12... | python -m json.tool
```

## 错误处理

- 时间戳必须严格递增且非空，否则创建任务时返回 `422`；
- 任务不存在返回 `404`；
- 极端情况下（如数据被外部破坏导致不可对齐），任务状态置为 `failed` 并在 `error` 字段说明原因；可调整参数后再次调用 `/align` 重新计算。
