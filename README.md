# local_scheduler — 本地时间通知调度库

纯内存、纯 Python 标准库（`zoneinfo`）实现，无接口层、不发送实际通知，
只按 UTC 区间生成投递候选。计划登记后不可修改，查询不改变计划。

## 概念

- **名义日期（nominal date）**：顺延前的当地计划日期。候选身份由
  `(schedule_id, nominal_date)` 确定，顺延不改变身份。
- **频率**：`Frequency.DAILY` 或 `Frequency.WEEKLY`（需指定 `weekday`，
  周一为 0）。
- **日期范围**：`start_date` / `end_date` 含首尾，只约束名义日期，
  不限制顺延结果。
- **免打扰**：可选 `QuietHours(start, end)`，按实际 UTC 瞬间换算出的当地
  时分秒判定；起点包含、终点不含；起点晚于终点表示跨午夜；起终相同
  表示关闭。命中时顺延到不早于原瞬间且不在窗口内的最早 UTC 秒。
- **时区缝隙**：发送时刻不存在时取不早于该本地日期时间的最早有效墙上
  时刻（可跨到后续日期）；墙上时刻重复出现时取较早的 UTC 瞬间；当地
  整日不存在（如 Pacific/Apia 2011-12-30）时该名义日跳过。

## 用法

```python
from datetime import date, datetime, time, timezone
from local_scheduler import Frequency, QuietHours, Schedule, Scheduler

scheduler = Scheduler()
scheduler.register(Schedule(
    schedule_id="promo-us",
    timezone="America/New_York",
    frequency=Frequency.DAILY,
    send_at=time(9, 30),
    start_date=date(2024, 11, 1),
    end_date=date(2024, 11, 30),
    quiet_hours=QuietHours(time(22, 0), time(7, 0)),  # 跨午夜
))

candidates = scheduler.query(
    datetime(2024, 11, 3, tzinfo=timezone.utc),   # 含起点
    datetime(2024, 11, 4, tzinfo=timezone.utc),   # 不含终点
)
for c in candidates:
    print(c.schedule_id, c.nominal_date, c.deliver_at)
```

查询只按最终 UTC 瞬间筛选；查询开始前已安排但顺延进区间的候选也会被
找回。同一查询可重复执行，结果一致。

## 运行测试

无需任何第三方依赖（Python 3.9+，需系统时区数据）：

```bash
python3 -m unittest discover -s tests -v
```

覆盖场景：`America/Nuuk` 2024-03-30 23:30 缝隙顺延至
`2024-03-31T01:00:00Z`；`Pacific/Apia` 2011-12-30 整日消失跳过；
`America/New_York` 2024-11-03 01:45 取较早一次，免打扰 01:30-02:30 时
折回后于 `2024-11-03T06:00:00Z` 退出窗口；跨午夜免打扰、区间含起点不
含终点、顺延候选找回、同秒候选保留、每周频率、登记校验等。
