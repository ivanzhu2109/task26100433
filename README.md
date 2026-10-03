# local_notify — 本地时间通知调度库

纯内存的通知投递候选生成库，由上层直接以 Python API 调用，无接口层、
无外部服务依赖（仅标准库 `zoneinfo`）。计划登记后不可修改；库只生成
投递候选，不负责实际发送。

## 功能

- 登记计划（IANA 时区、每日/每周指定星期几、本地发送时刻、含首尾的
  名义日期范围、可选每日免打扰起止时刻），并按 `[start, end)` 的 UTC
  区间查询候选。
- 每个符合频率的名义日期独立产生一个候选，身份为 `(plan_id,
  nominal_date)`，顺延不改变身份。
- 当地整日不存在（如 Pacific/Apia 2011-12-30）→ 跳过；发送时刻落入
  缺口 → 取不早于该本地日期时间的最早有效墙上时刻（可跨后续日期）；
  墙上时刻折回重复 → 取较早的 UTC 瞬间。
- 免打扰按实际 UTC 瞬间换算的当地时分秒判定（起点含、终点不含，
  起>终跨午夜，起=终关闭），命中则顺延到不在窗口内的最早 UTC 秒。
- 名义日期范围只约束名义日期，不限制顺延结果；查询只按最终 UTC 瞬间
  过滤，能找回查询开始前已安排但顺延进窗口的候选。

## 用法

```python
import datetime as dt
from local_notify import Frequency, Plan, QuietHours, Scheduler

s = Scheduler()
s.register(Plan(
    plan_id="promo",
    timezone="America/New_York",
    frequency=Frequency.WEEKLY,
    weekday=2,                      # 周三，0=周一
    send_time=dt.time(9, 30),
    nominal_start_date=dt.date(2024, 1, 1),
    nominal_end_date=dt.date(2024, 12, 31),
    quiet_hours=QuietHours(dt.time(22, 0), dt.time(7, 0)),  # 可 None
))
for c in s.query(dt.datetime(2024, 3, 1, tzinfo=dt.timezone.utc),
                 dt.datetime(2024, 4, 1, tzinfo=dt.timezone.utc)):
    print(c.plan_id, c.nominal_date, c.deliver_at_utc)
```

## 运行测试

```bash
python3 -m pytest tests/ -q
```

需要 Python 3.9+（含 `zoneinfo`）与系统时区数据库；测试依赖 pytest。

## 代码结构

- `local_notify/types.py` — `Frequency` / `QuietHours` / `Plan` / `Candidate`
- `local_notify/resolution.py` — 本地墙上时刻 → UTC 瞬间（缺口/折回/整日消失）
- `local_notify/quiet.py` — 免打扰判定与日历顺延
- `local_notify/scheduler.py` — 计划登记与 UTC 区间查询
- `tests/test_scheduler.py` — 规格场景与边界测试
