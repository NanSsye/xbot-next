from __future__ import annotations

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CommunityConfig(BaseModel):
    model_config = ConfigDict(validate_default=True)

    enabled: bool = True
    enabled_adapters: list[str] = Field(default_factory=lambda: ["qq"])
    allowed_conversation_ids: list[str] = Field(default_factory=list)
    red_packet_admin_user_ids: list[str] = Field(default_factory=list)
    require_mention: bool = True
    timezone: str = "Asia/Shanghai"
    checkin_base_reward: int = Field(default=5, ge=0, le=10_000)
    checkin_streak_3_bonus: int = Field(default=3, ge=0, le=10_000)
    checkin_streak_7_bonus: int = Field(default=10, ge=0, le=10_000)
    checkin_streak_30_bonus: int = Field(default=50, ge=0, le=10_000)

    activity_enabled: bool = True
    activity_rewards: list[int] = Field(default_factory=lambda: [20, 15, 10, 5, 3])
    activity_min_messages: int = Field(default=3, ge=1, le=10_000)
    activity_settle_hour: int = Field(default=0, ge=0, le=23)
    activity_settle_minute: int = Field(default=5, ge=0, le=59)
    activity_announce: bool = True
    activity_milestone_enabled: bool = True
    activity_milestone_messages: int = Field(default=60, ge=1, le=100_000)
    activity_milestone_reward: int = Field(default=5, ge=0, le=100_000)

    rps_daily_limit: int = Field(default=5, ge=0, le=100)
    rps_win_reward: int = Field(default=3, ge=0, le=10_000)
    rps_draw_reward: int = Field(default=1, ge=0, le=10_000)
    fortune_min_reward: int = Field(default=0, ge=0, le=10_000)
    fortune_max_reward: int = Field(default=5, ge=0, le=10_000)
    treasure_enabled: bool = True
    treasure_min_reward: int = Field(default=5, ge=0, le=10_000)
    treasure_max_reward: int = Field(default=10, ge=0, le=10_000)
    boss_enabled: bool = True
    boss_daily_hp: int = Field(default=1_000, ge=1, le=10_000_000)
    boss_daily_attacks: int = Field(default=1, ge=1, le=1_000)
    boss_min_damage: int = Field(default=10, ge=1, le=10_000)
    boss_max_damage: int = Field(default=30, ge=1, le=10_000)
    boss_min_reward: int = Field(default=10, ge=0, le=100_000)
    boss_max_reward: int = Field(default=30, ge=0, le=100_000)
    boss_kill_reward_pool: int = Field(default=1_000, ge=0, le=100_000_000)
    horse_race_enabled: bool = True
    horse_race_start_hour: int = Field(default=9, ge=0, le=23)
    horse_race_end_hour: int = Field(default=22, ge=0, le=23)
    horse_race_interval_hours: int = Field(default=6, ge=1, le=24)
    horse_race_draw_minute: int = Field(default=55, ge=1, le=59)
    horse_race_prize_pool: int = Field(default=200, ge=0, le=100_000_000)
    high_low_enabled: bool = True
    high_low_stake: int = Field(default=5, ge=1, le=10_000)
    high_low_daily_limit: int = Field(default=5, ge=1, le=100)
    leaderboard_enabled: bool = True
    token_exchange_enabled: bool = False
    token_exchange_points: int = Field(default=100, ge=1, le=100_000)
    token_exchange_tokens: int = Field(default=100_000, ge=1, le=10_000_000_000)

    @field_validator(
        "enabled_adapters", "allowed_conversation_ids", "red_packet_admin_user_ids"
    )
    @classmethod
    def normalize_list(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(item.strip() for item in value if item.strip()))

    @field_validator("activity_rewards")
    @classmethod
    def validate_rewards(cls, value: list[int]) -> list[int]:
        if len(value) != 5:
            raise ValueError("发言榜奖励必须正好配置五个名次")
        if any(item < 0 or item > 100_000 for item in value):
            raise ValueError("发言榜奖励必须在 0 到 100000 之间")
        return value

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("无效时区") from exc
        return value

    def model_post_init(self, __context: object) -> None:
        if self.fortune_max_reward < self.fortune_min_reward:
            raise ValueError("运势奖励上限不能小于下限")
        if self.treasure_max_reward < self.treasure_min_reward:
            raise ValueError("宝箱奖励上限不能小于下限")
        if self.boss_max_damage < self.boss_min_damage:
            raise ValueError("Boss 伤害上限不能小于下限")
        if self.boss_max_reward < self.boss_min_reward:
            raise ValueError("Boss 积分奖励上限不能小于下限")
        if self.horse_race_end_hour < self.horse_race_start_hour:
            raise ValueError("赛马结束小时不能早于开始小时")
