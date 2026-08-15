from __future__ import annotations

import json
import random
from datetime import UTC, date, datetime, time, timedelta
from hashlib import sha256
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from xbot.community.config import CommunityConfig
from xbot.core.timeutils import utc_now
from xbot.storage.models import (
    EXTERNAL_MESSAGE_ID_LENGTH,
    CommunityAccountRecord,
    CommunityActivityAwardRecord,
    CommunityActivitySettlementRecord,
    CommunityBossAttackRecord,
    CommunityBossRecord,
    CommunityCharacterImageExchangeRecord,
    CommunityCheckinRecord,
    CommunityConfigRecord,
    CommunityGamePlayRecord,
    CommunityHighLowWagerRecord,
    CommunityHorseRaceBetRecord,
    CommunityHorseRaceRecord,
    CommunityIdentityRecord,
    CommunityPointLedgerRecord,
    CommunityRedPacketClaimRecord,
    CommunityRedPacketRecord,
    CommunityTokenExchangeRecord,
    CommunityTreasureClaimRecord,
    ConversationMessageRecord,
)

_RANDOM = random.SystemRandom()


class CommunityError(RuntimeError):
    pass


class CommunityConflictError(CommunityError):
    pass


class CommunityNotBoundError(CommunityError):
    pass


class CommunityFrozenError(CommunityError):
    pass


class CommunityInsufficientPointsError(CommunityError):
    pass


def local_date(config: CommunityConfig, value: datetime | None = None) -> date:
    return local_datetime(config, value).date()


def local_datetime(config: CommunityConfig, value: datetime | None = None) -> datetime:
    current = value or utc_now()
    aware = current.replace(tzinfo=UTC) if current.tzinfo is None else current.astimezone(UTC)
    return aware.astimezone(ZoneInfo(config.timezone))


def utc_day_bounds(config: CommunityConfig, target: date) -> tuple[datetime, datetime]:
    timezone = ZoneInfo(config.timezone)
    start = datetime.combine(target, time.min, tzinfo=timezone).astimezone(UTC).replace(tzinfo=None)
    end = datetime.combine(target + timedelta(days=1), time.min, tzinfo=timezone)
    return start, end.astimezone(UTC).replace(tzinfo=None)


class CommunityService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_config(self) -> tuple[CommunityConfig, CommunityConfigRecord]:
        record = await self.session.get(CommunityConfigRecord, 1)
        if record is None:
            now = utc_now()
            config = CommunityConfig()
            record = CommunityConfigRecord(
                id=1,
                config_json=config.model_dump_json(),
                created_at=now,
                updated_at=now,
            )
            self.session.add(record)
            await self.session.flush()
            return config, record
        try:
            return CommunityConfig.model_validate_json(record.config_json or "{}"), record
        except ValueError:
            return CommunityConfig(), record

    async def update_config(self, config: CommunityConfig) -> CommunityConfig:
        _, record = await self.get_config()
        record.config_json = config.model_dump_json()
        record.updated_at = utc_now()
        await self.session.flush()
        return config

    async def identity_account(
        self,
        platform: str,
        adapter: str,
        user_id: str,
        *,
        lock: bool = False,
    ) -> tuple[CommunityIdentityRecord, CommunityAccountRecord]:
        statement = (
            select(CommunityIdentityRecord, CommunityAccountRecord)
            .join(
                CommunityAccountRecord,
                CommunityAccountRecord.id == CommunityIdentityRecord.account_id,
            )
            .where(
                CommunityIdentityRecord.platform == platform,
                CommunityIdentityRecord.adapter == adapter,
                CommunityIdentityRecord.user_id == user_id,
            )
        )
        if lock:
            statement = statement.with_for_update(of=CommunityAccountRecord)
        row = (await self.session.execute(statement)).one_or_none()
        if row is None:
            raise CommunityNotBoundError("请先使用永久邀请码绑定微伴账号。")
        identity, account = row
        if account.frozen:
            raise CommunityFrozenError("账号积分功能已被冻结，请联系管理员。")
        return identity, account

    async def touch_identity(
        self,
        identity: CommunityIdentityRecord,
        *,
        nickname: str | None,
        conversation_id: str,
    ) -> None:
        if nickname:
            identity.nickname = nickname[:512]
        identity.last_conversation_id = conversation_id[:512]
        identity.last_seen_at = utc_now()

    async def bind(
        self,
        *,
        platform: str,
        adapter: str,
        user_id: str,
        nickname: str | None,
        conversation_id: str,
        invite_code: str,
    ) -> dict[str, Any]:
        existing_identity = (
            await self.session.execute(
                select(CommunityIdentityRecord).where(
                    CommunityIdentityRecord.platform == platform,
                    CommunityIdentityRecord.adapter == adapter,
                    CommunityIdentityRecord.user_id == user_id,
                )
            )
        ).scalar_one_or_none()
        if existing_identity is not None:
            account = await self.session.get(CommunityAccountRecord, existing_identity.account_id)
            if account is not None and account.invite_code == invite_code:
                await self.touch_identity(
                    existing_identity, nickname=nickname, conversation_id=conversation_id
                )
                return {"already_bound": True, "balance": account.points_balance}
            raise CommunityConflictError("当前 QQ 用户已经绑定其他微伴账号，换绑请联系管理员。")

        account = (
            await self.session.execute(
                select(CommunityAccountRecord)
                .where(CommunityAccountRecord.invite_code == invite_code)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if account is None:
            account = CommunityAccountRecord(
                invite_code=invite_code,
                points_balance=0,
                frozen=False,
                created_at=utc_now(),
                updated_at=utc_now(),
            )
            self.session.add(account)
            await self.session.flush()
        elif account.frozen:
            raise CommunityFrozenError("该微伴账号的积分功能已被冻结，请联系管理员。")

        channel_identity = (
            await self.session.execute(
                select(CommunityIdentityRecord).where(
                    CommunityIdentityRecord.account_id == account.id,
                    CommunityIdentityRecord.platform == platform,
                    CommunityIdentityRecord.adapter == adapter,
                )
            )
        ).scalar_one_or_none()
        if channel_identity is not None:
            raise CommunityConflictError("该邀请码已绑定其他 QQ 用户，请联系管理员处理。")

        now = utc_now()
        self.session.add(
            CommunityIdentityRecord(
                account_id=account.id,
                platform=platform,
                adapter=adapter,
                user_id=user_id,
                nickname=(nickname or "")[:512] or None,
                last_conversation_id=conversation_id[:512],
                bound_at=now,
                last_seen_at=now,
            )
        )
        await self.session.flush()
        return {"already_bound": False, "balance": account.points_balance}

    async def _apply_points(
        self,
        account: CommunityAccountRecord,
        *,
        delta: int,
        reason: str,
        reference_id: str,
        conversation_id: str | None,
        effective_date: date,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        existing = (
            await self.session.execute(
                select(CommunityPointLedgerRecord).where(
                    CommunityPointLedgerRecord.reference_id == reference_id
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return {
                "applied": existing.delta,
                "balance": existing.balance_after,
                "duplicate": True,
            }
        applied = int(delta)
        if applied < 0 and account.points_balance + applied < 0:
            raise CommunityInsufficientPointsError("积分不足。")
        if applied == 0:
            return {"applied": 0, "balance": account.points_balance, "duplicate": False}
        account.points_balance += applied
        account.updated_at = utc_now()
        ledger = CommunityPointLedgerRecord(
            account_id=account.id,
            delta=applied,
            balance_after=account.points_balance,
            reason=reason[:64],
            reference_id=reference_id[:256],
            conversation_id=(conversation_id or "")[:512] or None,
            effective_date=effective_date,
            metadata_json=json.dumps(metadata or {}, ensure_ascii=False),
            created_at=utc_now(),
        )
        self.session.add(ledger)
        await self.session.flush()
        return {"applied": applied, "balance": account.points_balance, "duplicate": False}

    async def checkin(
        self,
        *,
        platform: str,
        adapter: str,
        user_id: str,
        nickname: str | None,
        conversation_id: str,
        config: CommunityConfig,
    ) -> dict[str, Any]:
        identity, account = await self.identity_account(platform, adapter, user_id, lock=True)
        await self.touch_identity(identity, nickname=nickname, conversation_id=conversation_id)
        today = local_date(config)
        existing = (
            await self.session.execute(
                select(CommunityCheckinRecord).where(
                    CommunityCheckinRecord.account_id == account.id,
                    CommunityCheckinRecord.checkin_date == today,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return {
                "already": True,
                "streak": existing.streak,
                "reward": existing.reward,
                "balance": account.points_balance,
            }
        latest = (
            await self.session.execute(
                select(CommunityCheckinRecord)
                .where(CommunityCheckinRecord.account_id == account.id)
                .order_by(CommunityCheckinRecord.checkin_date.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        streak = latest.streak + 1 if latest and latest.checkin_date == today - timedelta(days=1) else 1
        bonus = 0
        if streak % 30 == 0:
            bonus = config.checkin_streak_30_bonus
        elif streak % 7 == 0:
            bonus = config.checkin_streak_7_bonus
        elif streak % 3 == 0:
            bonus = config.checkin_streak_3_bonus
        points = await self._apply_points(
            account,
            delta=config.checkin_base_reward + bonus,
            reason="checkin",
            reference_id=f"checkin:{account.id}:{today.isoformat()}",
            conversation_id=conversation_id,
            effective_date=today,
            metadata={"streak": streak},
        )
        self.session.add(
            CommunityCheckinRecord(
                account_id=account.id,
                checkin_date=today,
                streak=streak,
                reward=points["applied"],
                conversation_id=conversation_id,
                created_at=utc_now(),
            )
        )
        await self.session.flush()
        return {"already": False, "streak": streak, "reward": points["applied"], "balance": points["balance"]}

    async def account_summary(
        self,
        platform: str,
        adapter: str,
        user_id: str,
        *,
        nickname: str | None = None,
        conversation_id: str = "",
    ) -> dict[str, Any]:
        identity, account = await self.identity_account(platform, adapter, user_id)
        if conversation_id:
            await self.touch_identity(identity, nickname=nickname, conversation_id=conversation_id)
        return {
            "account_id": account.id,
            "invite_code": account.invite_code,
            "balance": account.points_balance,
            "bound_at": identity.bound_at,
        }

    async def ledger_for_user(
        self,
        platform: str,
        adapter: str,
        user_id: str,
        *,
        limit: int = 8,
    ) -> list[dict[str, Any]]:
        _, account = await self.identity_account(platform, adapter, user_id)
        records = list(
            (
                await self.session.execute(
                    select(CommunityPointLedgerRecord)
                    .where(CommunityPointLedgerRecord.account_id == account.id)
                    .order_by(CommunityPointLedgerRecord.created_at.desc())
                    .limit(max(1, min(limit, 50)))
                )
            ).scalars()
        )
        return [self._ledger_dict(item) for item in records]

    async def _existing_game(self, reference_id: str) -> dict[str, Any] | None:
        record = (
            await self.session.execute(
                select(CommunityGamePlayRecord).where(
                    CommunityGamePlayRecord.reference_id == reference_id
                )
            )
        ).scalar_one_or_none()
        if record is None:
            return None
        payload = json.loads(record.result_json or "{}")
        payload.update({"duplicate": True, "points_delta": record.points_delta})
        return payload

    async def _game_count(self, account_id: int, game: str, target: date) -> int:
        value = await self.session.scalar(
            select(func.count(CommunityGamePlayRecord.id)).where(
                CommunityGamePlayRecord.account_id == account_id,
                CommunityGamePlayRecord.game == game,
                CommunityGamePlayRecord.play_date == target,
            )
        )
        return int(value or 0)

    async def rock_paper_scissors(
        self,
        *,
        platform: str,
        adapter: str,
        user_id: str,
        conversation_id: str,
        choice: str,
        message_id: str,
        config: CommunityConfig,
    ) -> dict[str, Any]:
        reference = f"game:rps:{adapter}:{message_id}"
        duplicate = await self._existing_game(reference)
        if duplicate is not None:
            return duplicate
        _, account = await self.identity_account(platform, adapter, user_id, lock=True)
        today = local_date(config)
        played = await self._game_count(account.id, "rps", today)
        if played >= config.rps_daily_limit:
            raise CommunityConflictError("今天的石头剪刀布次数已经用完。")
        bot_choice = _RANDOM.choice(("石头", "剪刀", "布"))
        wins = {("石头", "剪刀"), ("剪刀", "布"), ("布", "石头")}
        outcome = "draw" if choice == bot_choice else "win" if (choice, bot_choice) in wins else "lose"
        requested = config.rps_win_reward if outcome == "win" else config.rps_draw_reward if outcome == "draw" else 0
        points = await self._apply_points(
            account,
            delta=requested,
            reason=f"game_rps_{outcome}",
            reference_id=f"{reference}:reward",
            conversation_id=conversation_id,
            effective_date=today,
        )
        result = {
            "choice": choice,
            "bot_choice": bot_choice,
            "outcome": outcome,
            "reward": points["applied"],
            "balance": points["balance"],
            "remaining": max(config.rps_daily_limit - played - 1, 0),
        }
        self.session.add(
            CommunityGamePlayRecord(
                account_id=account.id,
                game="rps",
                play_date=today,
                reference_id=reference,
                result_json=json.dumps(result, ensure_ascii=False),
                points_delta=points["applied"],
                conversation_id=conversation_id,
                created_at=utc_now(),
            )
        )
        await self.session.flush()
        return result

    async def fortune(
        self,
        *,
        platform: str,
        adapter: str,
        user_id: str,
        conversation_id: str,
        config: CommunityConfig,
    ) -> dict[str, Any]:
        _, account = await self.identity_account(platform, adapter, user_id, lock=True)
        today = local_date(config)
        reference = f"game:fortune:{account.id}:{today.isoformat()}"
        duplicate = await self._existing_game(reference)
        if duplicate is not None:
            return duplicate
        requested = _RANDOM.randint(config.fortune_min_reward, config.fortune_max_reward)
        score = _RANDOM.randint(60, 99)
        points = await self._apply_points(
            account,
            delta=requested,
            reason="game_fortune",
            reference_id=f"{reference}:reward",
            conversation_id=conversation_id,
            effective_date=today,
        )
        result = {"score": score, "reward": points["applied"], "balance": points["balance"]}
        self.session.add(
            CommunityGamePlayRecord(
                account_id=account.id,
                game="fortune",
                play_date=today,
                reference_id=reference,
                result_json=json.dumps(result, ensure_ascii=False),
                points_delta=points["applied"],
                conversation_id=conversation_id,
                created_at=utc_now(),
            )
        )
        await self.session.flush()
        return result

    async def activity_ranking(
        self,
        conversation_id: str,
        target: date,
        config: CommunityConfig,
        *,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        start, end = utc_day_bounds(config, target)
        count_value = func.count(ConversationMessageRecord.id)
        reached_at = func.max(ConversationMessageRecord.created_at)
        nickname = func.coalesce(
            func.max(ConversationMessageRecord.sender_name),
            func.max(CommunityIdentityRecord.nickname),
        )
        rows = (
            await self.session.execute(
                select(
                    CommunityIdentityRecord.account_id,
                    nickname.label("nickname"),
                    count_value.label("message_count"),
                    reached_at.label("reached_at"),
                )
                .join(
                    ConversationMessageRecord,
                    and_(
                        ConversationMessageRecord.platform == CommunityIdentityRecord.platform,
                        ConversationMessageRecord.adapter == CommunityIdentityRecord.adapter,
                        ConversationMessageRecord.sender_id == CommunityIdentityRecord.user_id,
                    ),
                )
                .join(
                    CommunityAccountRecord,
                    CommunityAccountRecord.id == CommunityIdentityRecord.account_id,
                )
                .where(
                    ConversationMessageRecord.conversation_id == conversation_id,
                    ConversationMessageRecord.created_at >= start,
                    ConversationMessageRecord.created_at < end,
                    ConversationMessageRecord.type == "text",
                    func.length(func.trim(func.coalesce(ConversationMessageRecord.content, ""))) > 0,
                    CommunityAccountRecord.frozen.is_(False),
                )
                .group_by(CommunityIdentityRecord.account_id)
                .having(count_value >= config.activity_min_messages)
                .order_by(count_value.desc(), reached_at.asc(), CommunityIdentityRecord.account_id.asc())
                .limit(max(1, min(limit, 20)))
            )
        ).all()
        return [
            {
                "account_id": int(row.account_id),
                "nickname": str(row.nickname or "群成员"),
                "message_count": int(row.message_count),
            }
            for row in rows
        ]

    async def award_activity_milestone(
        self,
        *,
        platform: str,
        adapter: str,
        user_id: str,
        conversation_id: str,
        config: CommunityConfig,
    ) -> dict[str, Any]:
        if not config.activity_milestone_enabled or config.activity_milestone_reward <= 0:
            return {"awarded": False, "message_count": 0}
        _, account = await self.identity_account(platform, adapter, user_id)
        target = local_date(config)
        start, end = utc_day_bounds(config, target)
        message_count = int(
            await self.session.scalar(
                select(func.count(ConversationMessageRecord.id)).where(
                    ConversationMessageRecord.conversation_id == conversation_id,
                    ConversationMessageRecord.platform == platform,
                    ConversationMessageRecord.adapter == adapter,
                    ConversationMessageRecord.sender_id == user_id,
                    ConversationMessageRecord.created_at >= start,
                    ConversationMessageRecord.created_at < end,
                    ConversationMessageRecord.type == "text",
                    func.length(
                        func.trim(func.coalesce(ConversationMessageRecord.content, ""))
                    )
                    > 0,
                )
            )
            or 0
        )
        if message_count < config.activity_milestone_messages:
            return {"awarded": False, "message_count": message_count}
        account = (
            await self.session.execute(
                select(CommunityAccountRecord)
                .where(CommunityAccountRecord.id == account.id)
                .with_for_update()
            )
        ).scalar_one()
        conversation_hash = sha256(conversation_id.encode()).hexdigest()[:20]
        points = await self._apply_points(
            account,
            delta=config.activity_milestone_reward,
            reason="daily_activity_milestone",
            reference_id=(
                f"activity_milestone:{conversation_hash}:{target.isoformat()}:{account.id}"
            ),
            conversation_id=conversation_id,
            effective_date=target,
            metadata={
                "message_count": message_count,
                "threshold": config.activity_milestone_messages,
            },
        )
        return {
            "awarded": not points["duplicate"] and points["applied"] > 0,
            "message_count": message_count,
            "reward": points["applied"],
            "balance": points["balance"],
        }

    async def settle_activity_day(
        self,
        target: date,
        config: CommunityConfig,
    ) -> list[dict[str, Any]]:
        if not config.activity_enabled:
            return []
        start, end = utc_day_bounds(config, target)
        rows = (
            await self.session.execute(
                select(
                    ConversationMessageRecord.conversation_id,
                    ConversationMessageRecord.platform,
                    ConversationMessageRecord.adapter,
                )
                .where(
                    ConversationMessageRecord.created_at >= start,
                    ConversationMessageRecord.created_at < end,
                    ConversationMessageRecord.type == "text",
                )
                .distinct()
            )
        ).all()
        results: list[dict[str, Any]] = []
        for conversation_id, platform, adapter in rows:
            if adapter not in config.enabled_adapters:
                continue
            if config.allowed_conversation_ids and conversation_id not in config.allowed_conversation_ids:
                continue
            existing = (
                await self.session.execute(
                    select(CommunityActivitySettlementRecord.id).where(
                        CommunityActivitySettlementRecord.conversation_id == conversation_id,
                        CommunityActivitySettlementRecord.activity_date == target,
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                continue
            self.session.add(
                CommunityActivitySettlementRecord(
                    conversation_id=conversation_id,
                    activity_date=target,
                    config_json=config.model_dump_json(),
                    settled_at=utc_now(),
                )
            )
            await self.session.flush()
            ranking = await self.activity_ranking(conversation_id, target, config, limit=5)
            awards: list[dict[str, Any]] = []
            conversation_hash = sha256(conversation_id.encode()).hexdigest()[:20]
            for rank, item in enumerate(ranking, start=1):
                account = (
                    await self.session.execute(
                        select(CommunityAccountRecord)
                        .where(CommunityAccountRecord.id == item["account_id"])
                        .with_for_update()
                    )
                ).scalar_one()
                points = await self._apply_points(
                    account,
                    delta=config.activity_rewards[rank - 1],
                    reason="daily_activity_rank",
                    reference_id=f"activity:{conversation_hash}:{target.isoformat()}:{rank}",
                    conversation_id=conversation_id,
                    effective_date=target,
                    metadata={"rank": rank, "message_count": item["message_count"]},
                )
                award = {**item, "rank": rank, "reward": points["applied"]}
                awards.append(award)
                self.session.add(
                    CommunityActivityAwardRecord(
                        conversation_id=conversation_id,
                        activity_date=target,
                        account_id=account.id,
                        rank=rank,
                        message_count=item["message_count"],
                        reward=points["applied"],
                        nickname=item["nickname"][:512],
                        created_at=utc_now(),
                    )
                )
            results.append(
                {
                    "conversation_id": conversation_id,
                    "platform": platform,
                    "adapter": adapter,
                    "date": target,
                    "awards": awards,
                }
            )
        await self.session.flush()
        return results

    async def points_leaderboard(
        self,
        conversation_id: str,
        config: CommunityConfig,
        *,
        period: str = "total",
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        today = local_date(config)
        if period == "day":
            start_date = today
        elif period == "week":
            start_date = today - timedelta(days=today.weekday())
        elif period == "month":
            start_date = today.replace(day=1)
        else:
            start_date = None
        if start_date is None:
            score = CommunityAccountRecord.points_balance
            statement = (
                select(
                    CommunityIdentityRecord.account_id,
                    CommunityIdentityRecord.nickname,
                    score.label("score"),
                )
                .join(CommunityAccountRecord, CommunityAccountRecord.id == CommunityIdentityRecord.account_id)
                .where(
                    CommunityAccountRecord.frozen.is_(False),
                    select(ConversationMessageRecord.id)
                    .where(
                        ConversationMessageRecord.conversation_id == conversation_id,
                        ConversationMessageRecord.platform == CommunityIdentityRecord.platform,
                        ConversationMessageRecord.adapter == CommunityIdentityRecord.adapter,
                        ConversationMessageRecord.sender_id == CommunityIdentityRecord.user_id,
                    )
                    .exists(),
                )
                .order_by(score.desc(), CommunityIdentityRecord.account_id.asc())
                .limit(max(1, min(limit, 50)))
            )
        else:
            score = func.coalesce(func.sum(CommunityPointLedgerRecord.delta), 0)
            statement = (
                select(
                    CommunityIdentityRecord.account_id,
                    CommunityIdentityRecord.nickname,
                    score.label("score"),
                )
                .join(CommunityAccountRecord, CommunityAccountRecord.id == CommunityIdentityRecord.account_id)
                .join(CommunityPointLedgerRecord, CommunityPointLedgerRecord.account_id == CommunityAccountRecord.id)
                .where(
                    CommunityAccountRecord.frozen.is_(False),
                    CommunityPointLedgerRecord.conversation_id == conversation_id,
                    CommunityPointLedgerRecord.effective_date >= start_date,
                )
                .group_by(CommunityIdentityRecord.account_id, CommunityIdentityRecord.nickname)
                .order_by(score.desc(), CommunityIdentityRecord.account_id.asc())
                .limit(max(1, min(limit, 50)))
            )
        rows = (await self.session.execute(statement)).all()
        return [
            {"rank": index, "nickname": row.nickname or "群成员", "points": int(row.score or 0)}
            for index, row in enumerate(rows, start=1)
        ]

    async def overview(self, config: CommunityConfig) -> dict[str, int]:
        account_count = await self.session.scalar(select(func.count(CommunityAccountRecord.id)))
        identity_count = await self.session.scalar(select(func.count(CommunityIdentityRecord.id)))
        total_points = await self.session.scalar(
            select(func.coalesce(func.sum(CommunityAccountRecord.points_balance), 0))
        )
        today = local_date(config)
        checkins_today = await self.session.scalar(
            select(func.count(CommunityCheckinRecord.id)).where(
                CommunityCheckinRecord.checkin_date == today
            )
        )
        return {
            "accounts": int(account_count or 0),
            "identities": int(identity_count or 0),
            "points": int(total_points or 0),
            "checkins_today": int(checkins_today or 0),
        }

    async def admin_users(self, *, limit: int = 100) -> list[dict[str, Any]]:
        rows = (
            await self.session.execute(
                select(CommunityIdentityRecord, CommunityAccountRecord)
                .join(CommunityAccountRecord, CommunityAccountRecord.id == CommunityIdentityRecord.account_id)
                .order_by(CommunityIdentityRecord.last_seen_at.desc())
                .limit(max(1, min(limit, 500)))
            )
        ).all()
        return [
            {
                "identity_id": identity.id,
                "account_id": account.id,
                "platform": identity.platform,
                "adapter": identity.adapter,
                "user_id": identity.user_id,
                "nickname": identity.nickname,
                "last_conversation_id": identity.last_conversation_id,
                "points_balance": account.points_balance,
                "frozen": account.frozen,
                "bound_at": identity.bound_at,
                "last_seen_at": identity.last_seen_at,
            }
            for identity, account in rows
        ]

    async def admin_ledger(self, *, limit: int = 100) -> list[dict[str, Any]]:
        latest_nickname = (
            select(CommunityIdentityRecord.nickname)
            .where(
                CommunityIdentityRecord.account_id == CommunityPointLedgerRecord.account_id
            )
            .order_by(CommunityIdentityRecord.last_seen_at.desc())
            .limit(1)
            .correlate(CommunityPointLedgerRecord)
            .scalar_subquery()
        )
        rows = (
            await self.session.execute(
                select(CommunityPointLedgerRecord, latest_nickname.label("nickname"))
                .order_by(CommunityPointLedgerRecord.created_at.desc())
                .limit(max(1, min(limit, 500)))
            )
        ).all()
        return [
            {**self._ledger_dict(record), "nickname": nickname or "未绑定账号"}
            for record, nickname in rows
        ]

    async def unbind(self, identity_id: int) -> bool:
        identity = await self.session.get(CommunityIdentityRecord, identity_id)
        if identity is None:
            return False
        await self.session.delete(identity)
        await self.session.flush()
        return True

    async def set_frozen(self, account_id: int, frozen: bool) -> bool:
        account = await self.session.get(CommunityAccountRecord, account_id)
        if account is None:
            return False
        account.frozen = frozen
        account.updated_at = utc_now()
        return True

    async def adjust_points(self, account_id: int, delta: int, reason: str) -> dict[str, Any]:
        account = (
            await self.session.execute(
                select(CommunityAccountRecord)
                .where(CommunityAccountRecord.id == account_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if account is None:
            raise CommunityNotBoundError("积分账号不存在。")
        return await self._apply_points(
            account,
            delta=delta,
            reason="admin_adjustment",
            reference_id=f"admin:{uuid4().hex}",
            conversation_id=None,
            effective_date=utc_now().date(),
            metadata={"reason": reason[:256]},
        )

    async def claim_treasure(
        self,
        *,
        platform: str,
        adapter: str,
        user_id: str,
        nickname: str | None,
        conversation_id: str,
        box_number: int,
        config: CommunityConfig,
    ) -> dict[str, Any]:
        if not config.treasure_enabled:
            raise CommunityError("幸运宝箱暂未开放。")
        if box_number not in {1, 2, 3}:
            raise CommunityError("宝箱不存在。")
        identity, account = await self.identity_account(platform, adapter, user_id, lock=True)
        await self.touch_identity(identity, nickname=nickname, conversation_id=conversation_id)
        today = local_date(config)
        existing = (
            await self.session.execute(
                select(CommunityTreasureClaimRecord).where(
                    CommunityTreasureClaimRecord.account_id == account.id,
                    CommunityTreasureClaimRecord.claim_date == today,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return {
                "reward": existing.reward,
                "box_number": existing.box_number,
                "balance": account.points_balance,
                "duplicate": True,
            }
        reward = _RANDOM.randint(config.treasure_min_reward, config.treasure_max_reward)
        points = await self._apply_points(
            account,
            delta=reward,
            reason="game_treasure",
            reference_id=f"treasure:{account.id}:{today.isoformat()}",
            conversation_id=conversation_id,
            effective_date=today,
            metadata={"box_number": box_number},
        )
        self.session.add(
            CommunityTreasureClaimRecord(
                account_id=account.id,
                claim_date=today,
                conversation_id=conversation_id[:512],
                box_number=box_number,
                reward=int(points["applied"]),
                created_at=utc_now(),
            )
        )
        await self.session.flush()
        return {
            "reward": int(points["applied"]),
            "box_number": box_number,
            "balance": int(points["balance"]),
            "duplicate": False,
        }

    async def daily_boss(
        self,
        conversation_id: str,
        config: CommunityConfig,
        *,
        lock: bool = False,
    ) -> CommunityBossRecord:
        today = local_date(config)
        statement = select(CommunityBossRecord).where(
            CommunityBossRecord.conversation_id == conversation_id,
            CommunityBossRecord.boss_date == today,
        )
        if lock:
            statement = statement.with_for_update()
        boss = (await self.session.execute(statement)).scalar_one_or_none()
        if boss is None:
            boss = CommunityBossRecord(
                conversation_id=conversation_id[:512],
                boss_date=today,
                max_hp=config.boss_daily_hp,
                remaining_hp=config.boss_daily_hp,
                status="active",
                participant_count=0,
                payout_total=0,
                created_at=utc_now(),
            )
            self.session.add(boss)
            await self.session.flush()
        return boss

    async def boss_status(
        self,
        conversation_id: str,
        config: CommunityConfig,
    ) -> dict[str, Any]:
        if not config.boss_enabled:
            raise CommunityError("每日 Boss 暂未开放。")
        boss = await self.daily_boss(conversation_id, config)
        attack_count = int(
            await self.session.scalar(
                select(func.count(CommunityBossAttackRecord.id)).where(
                    CommunityBossAttackRecord.boss_id == boss.id
                )
            )
            or 0
        )
        return self._boss_dict(boss, attack_count=attack_count)

    async def attack_boss(
        self,
        *,
        platform: str,
        adapter: str,
        user_id: str,
        nickname: str | None,
        conversation_id: str,
        event_id: str,
        config: CommunityConfig,
    ) -> dict[str, Any]:
        if not config.boss_enabled:
            raise CommunityError("每日 Boss 暂未开放。")
        identity, identity_account = await self.identity_account(platform, adapter, user_id)
        boss = await self.daily_boss(conversation_id, config, lock=True)
        account = (
            await self.session.execute(
                select(CommunityAccountRecord)
                .where(CommunityAccountRecord.id == identity_account.id)
                .with_for_update()
            )
        ).scalar_one()
        if account.frozen:
            raise CommunityFrozenError("账号积分功能已被冻结，请联系管理员。")
        await self.touch_identity(identity, nickname=nickname, conversation_id=conversation_id)
        normalized_event_id = str(event_id or "").strip()[:EXTERNAL_MESSAGE_ID_LENGTH]
        if not normalized_event_id:
            raise CommunityError("攻击事件缺少唯一标识，请重试。")
        existing = (
            await self.session.execute(
                select(CommunityBossAttackRecord).where(
                    CommunityBossAttackRecord.event_id == normalized_event_id
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return {
                **self._boss_dict(boss),
                "damage": existing.damage,
                "reward": existing.reward,
                "pool_reward": existing.pool_reward,
                "balance": account.points_balance,
                "attack_index": existing.attack_index,
                "attacks_left": max(config.boss_daily_attacks - existing.attack_index, 0),
                "duplicate": True,
            }
        used = int(
            await self.session.scalar(
                select(func.count(CommunityBossAttackRecord.id)).where(
                    CommunityBossAttackRecord.boss_id == boss.id,
                    CommunityBossAttackRecord.account_id == account.id,
                )
            )
            or 0
        )
        if used >= config.boss_daily_attacks:
            raise CommunityConflictError(
                f"今天已经攻击 {config.boss_daily_attacks} 次了，明天再来。"
            )
        if boss.status != "active" or boss.remaining_hp <= 0:
            raise CommunityConflictError("今天的 Boss 已经被击败了，明天再来。")
        roll = _RANDOM.randint(config.boss_min_damage, config.boss_max_damage)
        damage = min(roll, boss.remaining_hp)
        reward = _RANDOM.randint(config.boss_min_reward, config.boss_max_reward)
        attack_index = used + 1
        points = await self._apply_points(
            account,
            delta=reward,
            reason="game_boss_attack",
            reference_id=f"boss:{boss.id}:attack:{account.id}:{attack_index}",
            conversation_id=conversation_id,
            effective_date=boss.boss_date,
            metadata={"boss_id": boss.id, "damage": damage},
        )
        attack = CommunityBossAttackRecord(
            boss_id=boss.id,
            account_id=account.id,
            event_id=normalized_event_id,
            attack_index=attack_index,
            damage=damage,
            reward=int(points["applied"]),
            pool_reward=0,
            created_at=utc_now(),
        )
        self.session.add(attack)
        boss.remaining_hp -= damage
        await self.session.flush()

        pool_reward = 0
        participant_count = 0
        if boss.remaining_hp == 0:
            participant_rows = (
                await self.session.execute(
                    select(
                        CommunityBossAttackRecord.account_id,
                        func.min(CommunityBossAttackRecord.created_at).label("first_attack_at"),
                    )
                    .where(CommunityBossAttackRecord.boss_id == boss.id)
                    .group_by(CommunityBossAttackRecord.account_id)
                    .order_by("first_attack_at", CommunityBossAttackRecord.account_id)
                )
            ).all()
            participant_ids = [int(row.account_id) for row in participant_rows]
            participant_count = len(participant_ids)
            accounts = (
                await self.session.execute(
                    select(CommunityAccountRecord)
                    .where(CommunityAccountRecord.id.in_(participant_ids))
                    .order_by(CommunityAccountRecord.id)
                    .with_for_update()
                )
            ).scalars().all()
            account_by_id = {item.id: item for item in accounts}
            base, remainder = divmod(config.boss_kill_reward_pool, participant_count)
            for index, participant_id in enumerate(participant_ids):
                share = base + (1 if index < remainder else 0)
                if share:
                    await self._apply_points(
                        account_by_id[participant_id],
                        delta=share,
                        reason="game_boss_kill",
                        reference_id=f"boss:{boss.id}:kill:{participant_id}",
                        conversation_id=conversation_id,
                        effective_date=boss.boss_date,
                        metadata={
                            "boss_id": boss.id,
                            "participant_count": participant_count,
                        },
                    )
                if participant_id == account.id:
                    pool_reward = share
                    attack.pool_reward = share
            boss.status = "defeated"
            boss.participant_count = participant_count
            boss.payout_total = config.boss_kill_reward_pool
            boss.defeated_at = utc_now()
            await self.session.flush()
            await self.session.refresh(account)

        total_attacks = int(
            await self.session.scalar(
                select(func.count(CommunityBossAttackRecord.id)).where(
                    CommunityBossAttackRecord.boss_id == boss.id
                )
            )
            or 0
        )
        return {
            **self._boss_dict(boss, attack_count=total_attacks),
            "damage": damage,
            "reward": int(points["applied"]),
            "pool_reward": pool_reward,
            "balance": account.points_balance,
            "attack_index": attack_index,
            "attacks_left": config.boss_daily_attacks - attack_index,
            "duplicate": False,
        }

    @staticmethod
    def _boss_dict(
        boss: CommunityBossRecord,
        *,
        attack_count: int | None = None,
    ) -> dict[str, Any]:
        return {
            "boss_id": boss.id,
            "boss_date": boss.boss_date.isoformat(),
            "max_hp": boss.max_hp,
            "remaining_hp": boss.remaining_hp,
            "status": boss.status,
            "participant_count": boss.participant_count,
            "payout_total": boss.payout_total,
            "attack_count": attack_count,
        }

    @staticmethod
    def _horse_race_hours(config: CommunityConfig) -> range:
        return range(
            config.horse_race_start_hour,
            config.horse_race_end_hour + 1,
            config.horse_race_interval_hours,
        )

    @classmethod
    def _horse_race_slot(
        cls, config: CommunityConfig, value: datetime | None = None
    ) -> tuple[date, int] | None:
        current = local_datetime(config, value)
        if not (
            current.hour in cls._horse_race_hours(config)
            and current.minute < config.horse_race_draw_minute
        ):
            return None
        return current.date(), current.hour

    async def horse_race_round(
        self,
        *,
        platform: str,
        adapter: str,
        conversation_id: str,
        config: CommunityConfig,
        now: datetime | None = None,
        lock: bool = False,
    ) -> CommunityHorseRaceRecord:
        if not config.horse_race_enabled:
            raise CommunityError("群体赛马暂未开放。")
        slot = self._horse_race_slot(config, now)
        if slot is None:
            draw_times = "、".join(
                f"{hour:02d}:{config.horse_race_draw_minute:02d}"
                for hour in self._horse_race_hours(config)
            )
            raise CommunityConflictError(
                f"赛马每天 {draw_times} 开奖，每场在开奖前开放参与。"
            )
        race_date, race_hour = slot
        statement = select(CommunityHorseRaceRecord).where(
            CommunityHorseRaceRecord.conversation_id == conversation_id,
            CommunityHorseRaceRecord.race_date == race_date,
            CommunityHorseRaceRecord.race_hour == race_hour,
        )
        if lock:
            statement = statement.with_for_update()
        race = (await self.session.execute(statement)).scalar_one_or_none()
        if race is None:
            race = CommunityHorseRaceRecord(
                conversation_id=conversation_id[:512],
                platform=platform[:64],
                adapter=adapter[:64],
                race_date=race_date,
                race_hour=race_hour,
                status="active",
                winning_horse=None,
                participant_count=0,
                winner_count=0,
                payout_total=0,
                opened_at=utc_now(),
            )
            self.session.add(race)
            await self.session.flush()
        if race.status != "active":
            raise CommunityConflictError("本轮赛马已经开奖，请等待下一场。")
        return race

    async def horse_race_status(
        self,
        *,
        platform: str,
        adapter: str,
        conversation_id: str,
        config: CommunityConfig,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        race = await self.horse_race_round(
            platform=platform,
            adapter=adapter,
            conversation_id=conversation_id,
            config=config,
            now=now,
        )
        bets = (
            await self.session.execute(
                select(CommunityHorseRaceBetRecord).where(
                    CommunityHorseRaceBetRecord.race_id == race.id
                )
            )
        ).scalars().all()
        result = self._horse_race_dict(race, bets, config)
        result["previous"] = await self._previous_horse_race_result(race, config)
        return result

    async def join_horse_race(
        self,
        *,
        platform: str,
        adapter: str,
        user_id: str,
        nickname: str | None,
        conversation_id: str,
        horse_number: int,
        config: CommunityConfig,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        if horse_number not in {1, 2, 3, 4}:
            raise CommunityError("赛马编号不存在。")
        identity, account = await self.identity_account(platform, adapter, user_id, lock=True)
        await self.touch_identity(identity, nickname=nickname, conversation_id=conversation_id)
        race = await self.horse_race_round(
            platform=platform,
            adapter=adapter,
            conversation_id=conversation_id,
            config=config,
            now=now,
            lock=True,
        )
        existing = (
            await self.session.execute(
                select(CommunityHorseRaceBetRecord).where(
                    CommunityHorseRaceBetRecord.race_id == race.id,
                    CommunityHorseRaceBetRecord.account_id == account.id,
                )
            )
        ).scalar_one_or_none()
        duplicate = existing is not None
        if existing is not None and existing.horse_number != horse_number:
            raise CommunityConflictError(
                f"本轮已经支持 {existing.horse_number} 号马，不能修改。"
            )
        if existing is None:
            existing = CommunityHorseRaceBetRecord(
                race_id=race.id,
                account_id=account.id,
                horse_number=horse_number,
                nickname=(nickname or identity.nickname or "")[:512] or None,
                reward=0,
                created_at=utc_now(),
            )
            self.session.add(existing)
            await self.session.flush()
        bets = (
            await self.session.execute(
                select(CommunityHorseRaceBetRecord)
                .where(CommunityHorseRaceBetRecord.race_id == race.id)
                .order_by(CommunityHorseRaceBetRecord.created_at, CommunityHorseRaceBetRecord.id)
            )
        ).scalars().all()
        result = {
            **self._horse_race_dict(race, bets, config),
            "horse_number": existing.horse_number,
            "duplicate": duplicate,
        }
        result["previous"] = await self._previous_horse_race_result(race, config)
        return result

    async def _previous_horse_race_result(
        self,
        current: CommunityHorseRaceRecord,
        config: CommunityConfig,
    ) -> dict[str, Any] | None:
        previous = (
            await self.session.execute(
                select(CommunityHorseRaceRecord)
                .where(
                    CommunityHorseRaceRecord.conversation_id == current.conversation_id,
                    CommunityHorseRaceRecord.status == "settled",
                    or_(
                        CommunityHorseRaceRecord.race_date < current.race_date,
                        and_(
                            CommunityHorseRaceRecord.race_date == current.race_date,
                            CommunityHorseRaceRecord.race_hour < current.race_hour,
                        ),
                    ),
                )
                .order_by(
                    CommunityHorseRaceRecord.race_date.desc(),
                    CommunityHorseRaceRecord.race_hour.desc(),
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        if previous is None:
            return None
        bets = (
            await self.session.execute(
                select(CommunityHorseRaceBetRecord)
                .where(CommunityHorseRaceBetRecord.race_id == previous.id)
                .order_by(
                    CommunityHorseRaceBetRecord.reward.desc(),
                    CommunityHorseRaceBetRecord.created_at,
                    CommunityHorseRaceBetRecord.id,
                )
            )
        ).scalars().all()
        return self._horse_race_dict(previous, bets, config)

    async def open_current_horse_races(
        self,
        config: CommunityConfig,
        *,
        now: datetime | None = None,
    ) -> list[dict[str, Any]]:
        if not config.horse_race_enabled or self._horse_race_slot(config, now) is None:
            return []
        rows = (
            await self.session.execute(
                select(
                    CommunityIdentityRecord.last_conversation_id,
                    CommunityIdentityRecord.platform,
                    CommunityIdentityRecord.adapter,
                )
                .where(CommunityIdentityRecord.last_conversation_id.is_not(None))
                .distinct()
            )
        ).all()
        opened: list[dict[str, Any]] = []
        for conversation_id, platform, adapter in rows:
            if adapter not in config.enabled_adapters:
                continue
            if config.allowed_conversation_ids and conversation_id not in config.allowed_conversation_ids:
                continue
            slot = self._horse_race_slot(config, now)
            if slot is None:
                continue
            race_date, race_hour = slot
            existing = await self.session.scalar(
                select(CommunityHorseRaceRecord.id).where(
                    CommunityHorseRaceRecord.conversation_id == conversation_id,
                    CommunityHorseRaceRecord.race_date == race_date,
                    CommunityHorseRaceRecord.race_hour == race_hour,
                )
            )
            if existing is not None:
                continue
            race = await self.horse_race_round(
                platform=platform,
                adapter=adapter,
                conversation_id=conversation_id,
                config=config,
                now=now,
            )
            opened.append(self._horse_race_dict(race, [], config))
        return opened

    async def settle_due_horse_races(
        self,
        config: CommunityConfig,
        *,
        now: datetime | None = None,
    ) -> list[dict[str, Any]]:
        if not config.horse_race_enabled:
            return []
        current = local_datetime(config, now)
        races = (
            await self.session.execute(
                select(CommunityHorseRaceRecord)
                .where(CommunityHorseRaceRecord.status == "active")
                .order_by(
                    CommunityHorseRaceRecord.race_date,
                    CommunityHorseRaceRecord.race_hour,
                )
                .with_for_update()
            )
        ).scalars().all()
        settled: list[dict[str, Any]] = []
        timezone = ZoneInfo(config.timezone)
        for race in races:
            draw_at = datetime.combine(
                race.race_date,
                time(race.race_hour, config.horse_race_draw_minute),
                tzinfo=timezone,
            )
            if current < draw_at:
                continue
            bets = (
                await self.session.execute(
                    select(CommunityHorseRaceBetRecord)
                    .where(CommunityHorseRaceBetRecord.race_id == race.id)
                    .order_by(
                        CommunityHorseRaceBetRecord.created_at,
                        CommunityHorseRaceBetRecord.id,
                    )
                )
            ).scalars().all()
            race.participant_count = len(bets)
            race.settled_at = utc_now()
            if not bets:
                race.status = "cancelled"
                continue
            supported_horses = sorted({bet.horse_number for bet in bets})
            winning_horse = int(_RANDOM.choice(supported_horses))
            winners = [bet for bet in bets if bet.horse_number == winning_horse]
            base, remainder = divmod(config.horse_race_prize_pool, len(winners))
            for index, bet in enumerate(winners):
                reward = base + (1 if index < remainder else 0)
                account = (
                    await self.session.execute(
                        select(CommunityAccountRecord)
                        .where(CommunityAccountRecord.id == bet.account_id)
                        .with_for_update()
                    )
                ).scalar_one()
                points = await self._apply_points(
                    account,
                    delta=reward,
                    reason="game_horse_race",
                    reference_id=f"horse_race:{race.id}:winner:{account.id}",
                    conversation_id=race.conversation_id,
                    effective_date=race.race_date,
                    metadata={"race_id": race.id, "horse_number": winning_horse},
                )
                bet.reward = int(points["applied"])
            race.status = "settled"
            race.winning_horse = winning_horse
            race.winner_count = len(winners)
            race.payout_total = sum(bet.reward for bet in winners)
            settled.append(self._horse_race_dict(race, bets, config))
        await self.session.flush()
        return settled

    @staticmethod
    def _horse_race_dict(
        race: CommunityHorseRaceRecord,
        bets: list[CommunityHorseRaceBetRecord],
        config: CommunityConfig,
    ) -> dict[str, Any]:
        counts = {horse: 0 for horse in range(1, 5)}
        for bet in bets:
            counts[bet.horse_number] += 1
        return {
            "race_id": race.id,
            "conversation_id": race.conversation_id,
            "platform": race.platform,
            "adapter": race.adapter,
            "race_date": race.race_date.isoformat(),
            "race_hour": race.race_hour,
            "draw_minute": config.horse_race_draw_minute,
            "status": race.status,
            "winning_horse": race.winning_horse,
            "participant_count": len(bets) if bets else race.participant_count,
            "winner_count": race.winner_count,
            "payout_total": race.payout_total,
            "counts": counts,
            "winners": [
                {
                    "nickname": bet.nickname or "群成员",
                    "reward": bet.reward,
                }
                for bet in bets
                if bet.reward > 0
            ],
        }

    async def play_high_low(
        self,
        *,
        platform: str,
        adapter: str,
        user_id: str,
        nickname: str | None,
        conversation_id: str,
        choice: str,
        event_id: str,
        config: CommunityConfig,
    ) -> dict[str, Any]:
        if not config.high_low_enabled:
            raise CommunityError("押大小暂未开放。")
        if choice not in {"大", "小"}:
            raise CommunityError("请选择大或小。")
        normalized_event_id = str(event_id or "").strip()
        if not normalized_event_id:
            raise CommunityError("押大小事件缺少唯一标识，请重试。")
        wager_id = sha256(f"{adapter}:{normalized_event_id}".encode()).hexdigest()
        amount = config.high_low_stake
        identity, account = await self.identity_account(platform, adapter, user_id, lock=True)
        await self.touch_identity(identity, nickname=nickname, conversation_id=conversation_id)
        wager = (
            await self.session.execute(
                select(CommunityHighLowWagerRecord)
                .where(CommunityHighLowWagerRecord.wager_id == wager_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if wager is not None:
            if wager.account_id != account.id or wager.conversation_id != conversation_id:
                raise CommunityError("押大小事件归属不一致。")
            today = local_date(config)
            day_start, day_end = utc_day_bounds(config, today)
            played = int(
                await self.session.scalar(
                    select(func.count(CommunityHighLowWagerRecord.id)).where(
                        CommunityHighLowWagerRecord.account_id == account.id,
                        CommunityHighLowWagerRecord.status == "settled",
                        CommunityHighLowWagerRecord.created_at >= day_start,
                        CommunityHighLowWagerRecord.created_at < day_end,
                    )
                )
                or 0
            )
            return {
                **self._high_low_dict(wager, balance=account.points_balance),
                "duplicate": True,
                "remaining": max(config.high_low_daily_limit - played, 0),
            }
        today = local_date(config)
        day_start, day_end = utc_day_bounds(config, today)
        played = int(
            await self.session.scalar(
                select(func.count(CommunityHighLowWagerRecord.id)).where(
                    CommunityHighLowWagerRecord.account_id == account.id,
                    CommunityHighLowWagerRecord.status == "settled",
                    CommunityHighLowWagerRecord.created_at >= day_start,
                    CommunityHighLowWagerRecord.created_at < day_end,
                )
            )
            or 0
        )
        if played >= config.high_low_daily_limit:
            raise CommunityConflictError(
                f"今天已经玩过 {config.high_low_daily_limit} 次押大小，明天再来。"
            )
        debit = await self._apply_points(
            account,
            delta=-amount,
            reason="game_high_low_stake",
            reference_id=f"high_low:{wager_id}:stake",
            conversation_id=conversation_id,
            effective_date=local_date(config),
            metadata={"wager_id": wager_id, "choice": choice},
        )
        roll = _RANDOM.randint(1, 100)
        result_side = "小" if roll <= 50 else "大"
        won = choice == result_side
        payout = amount * 2 if won else 0
        balance = int(debit["balance"])
        if payout:
            credit = await self._apply_points(
                account,
                delta=payout,
                reason="game_high_low_payout",
                reference_id=f"high_low:{wager_id}:payout",
                conversation_id=conversation_id,
                effective_date=local_date(config),
                metadata={"wager_id": wager_id, "roll": roll},
            )
            balance = int(credit["balance"])
        now = utc_now()
        wager = CommunityHighLowWagerRecord(
            wager_id=wager_id,
            account_id=account.id,
            conversation_id=conversation_id[:512],
            amount=amount,
            choice=choice,
            status="settled",
            roll=roll,
            won=won,
            payout=payout,
            net_points=payout - amount,
            created_at=now,
            expires_at=now,
            settled_at=now,
        )
        self.session.add(wager)
        await self.session.flush()
        return {
            **self._high_low_dict(wager, balance=balance),
            "duplicate": False,
            "remaining": max(config.high_low_daily_limit - played - 1, 0),
        }

    @staticmethod
    def _high_low_dict(
        wager: CommunityHighLowWagerRecord,
        *,
        balance: int,
    ) -> dict[str, Any]:
        return {
            "wager_id": wager.wager_id,
            "amount": wager.amount,
            "choice": wager.choice,
            "status": wager.status,
            "roll": wager.roll,
            "result_side": None if wager.roll is None else "小" if wager.roll <= 50 else "大",
            "won": wager.won,
            "payout": wager.payout,
            "net_points": wager.net_points,
            "balance": balance,
        }

    async def create_red_packet(
        self,
        *,
        platform: str,
        adapter: str,
        user_id: str,
        nickname: str | None,
        conversation_id: str,
        system_funded: bool,
    ) -> dict[str, Any]:
        account_id: int | None = None
        if not system_funded:
            identity, account = await self.identity_account(platform, adapter, user_id)
            await self.touch_identity(identity, nickname=nickname, conversation_id=conversation_id)
            account_id = account.id
        packet_count = _RANDOM.randint(5, 10)
        allocations = [_RANDOM.randint(1, 10) for _ in range(packet_count)]
        total_points = sum(allocations)
        now = utc_now()
        packet = CommunityRedPacketRecord(
            packet_id=uuid4().hex,
            creator_account_id=account_id,
            creator_user_id=user_id[:256],
            creator_name=(nickname or "")[:512] or None,
            conversation_id=conversation_id[:512],
            source_type="system" if system_funded else "user",
            status="active" if system_funded else "pending_confirmation",
            total_points=total_points,
            packet_count=packet_count,
            remaining_points=total_points,
            remaining_count=packet_count,
            allocations_json=json.dumps(allocations),
            created_at=now,
            activated_at=now if system_funded else None,
        )
        self.session.add(packet)
        await self.session.flush()
        return self._red_packet_dict(packet)

    async def confirm_red_packet(
        self,
        *,
        packet_id: str,
        platform: str,
        adapter: str,
        user_id: str,
        nickname: str | None,
        conversation_id: str,
        config: CommunityConfig,
    ) -> dict[str, Any]:
        packet = (
            await self.session.execute(
                select(CommunityRedPacketRecord)
                .where(CommunityRedPacketRecord.packet_id == packet_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if packet is None or packet.conversation_id != conversation_id:
            raise CommunityError("红包不存在或不属于当前群。")
        if packet.source_type != "user" or packet.creator_user_id != user_id:
            raise CommunityError("只能确认自己发起的红包。")
        if packet.status != "pending_confirmation":
            return self._red_packet_dict(packet, existing=True)
        identity, account = await self.identity_account(platform, adapter, user_id, lock=True)
        if packet.creator_account_id != account.id:
            raise CommunityError("红包发起账号不一致。")
        await self.touch_identity(identity, nickname=nickname, conversation_id=conversation_id)
        await self._apply_points(
            account,
            delta=-packet.total_points,
            reason="red_packet_send",
            reference_id=f"red_packet:{packet.packet_id}:debit",
            conversation_id=conversation_id,
            effective_date=local_date(config),
            metadata={"packet_id": packet.packet_id, "packet_count": packet.packet_count},
        )
        packet.status = "active"
        packet.activated_at = utc_now()
        await self.session.flush()
        return self._red_packet_dict(packet)

    async def claim_red_packet(
        self,
        *,
        packet_id: str,
        platform: str,
        adapter: str,
        user_id: str,
        nickname: str | None,
        conversation_id: str,
        config: CommunityConfig,
    ) -> dict[str, Any]:
        packet = (
            await self.session.execute(
                select(CommunityRedPacketRecord)
                .where(CommunityRedPacketRecord.packet_id == packet_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if packet is None or packet.conversation_id != conversation_id:
            raise CommunityError("红包不存在或不属于当前群。")
        if packet.status == "pending_confirmation":
            raise CommunityError("红包还没有确认发出。")
        identity, account = await self.identity_account(platform, adapter, user_id, lock=True)
        await self.touch_identity(identity, nickname=nickname, conversation_id=conversation_id)
        existing = (
            await self.session.execute(
                select(CommunityRedPacketClaimRecord).where(
                    CommunityRedPacketClaimRecord.packet_id == packet.packet_id,
                    CommunityRedPacketClaimRecord.account_id == account.id,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return {
                **self._red_packet_dict(packet),
                "amount": existing.amount,
                "balance": account.points_balance,
                "duplicate": True,
            }
        if packet.status != "active" or packet.remaining_count <= 0:
            raise CommunityConflictError("红包已经被抢完了。")
        allocations = json.loads(packet.allocations_json or "[]")
        if not isinstance(allocations, list) or not allocations:
            raise CommunityError("红包数据异常，请联系管理员。")
        amount = int(allocations.pop(0))
        points = await self._apply_points(
            account,
            delta=amount,
            reason="red_packet_claim",
            reference_id=f"red_packet:{packet.packet_id}:claim:{account.id}",
            conversation_id=conversation_id,
            effective_date=local_date(config),
            metadata={"packet_id": packet.packet_id, "source_type": packet.source_type},
        )
        packet.allocations_json = json.dumps(allocations)
        packet.remaining_count -= 1
        packet.remaining_points -= amount
        if packet.remaining_count == 0:
            packet.status = "completed"
            packet.completed_at = utc_now()
        self.session.add(
            CommunityRedPacketClaimRecord(
                packet_id=packet.packet_id,
                account_id=account.id,
                amount=amount,
                created_at=utc_now(),
            )
        )
        await self.session.flush()
        return {
            **self._red_packet_dict(packet),
            "amount": amount,
            "balance": points["balance"],
            "duplicate": False,
        }

    @staticmethod
    def _red_packet_dict(
        packet: CommunityRedPacketRecord,
        *,
        existing: bool = False,
    ) -> dict[str, Any]:
        return {
            "packet_id": packet.packet_id,
            "source_type": packet.source_type,
            "status": packet.status,
            "total_points": packet.total_points,
            "packet_count": packet.packet_count,
            "remaining_points": packet.remaining_points,
            "remaining_count": packet.remaining_count,
            "creator_name": packet.creator_name,
            "existing": existing,
        }

    async def begin_token_exchange(
        self,
        *,
        platform: str,
        adapter: str,
        user_id: str,
        nickname: str | None,
        conversation_id: str,
        points_cost: int,
        token_amount: int,
        config: CommunityConfig,
    ) -> dict[str, Any]:
        identity, account = await self.identity_account(platform, adapter, user_id, lock=True)
        await self.touch_identity(identity, nickname=nickname, conversation_id=conversation_id)
        pending = (
            await self.session.execute(
                select(CommunityTokenExchangeRecord)
                .where(
                    CommunityTokenExchangeRecord.account_id == account.id,
                    CommunityTokenExchangeRecord.status == "pending",
                )
                .order_by(CommunityTokenExchangeRecord.id.asc())
                .with_for_update()
            )
        ).scalars().first()
        if pending is not None:
            return self._exchange_dict(pending, invite_code=account.invite_code, existing=True)

        exchange_id = uuid4().hex
        await self._apply_points(
            account,
            delta=-int(points_cost),
            reason="token_exchange",
            reference_id=f"token_exchange:{exchange_id}:debit",
            conversation_id=conversation_id,
            effective_date=local_date(config),
            metadata={"exchange_id": exchange_id, "token_amount": int(token_amount)},
        )
        record = CommunityTokenExchangeRecord(
            exchange_id=exchange_id,
            account_id=account.id,
            points_cost=int(points_cost),
            token_amount=int(token_amount),
            status="pending",
            idempotency_key=f"xbot-token-exchange:{exchange_id}",
            conversation_id=conversation_id,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        self.session.add(record)
        await self.session.flush()
        return self._exchange_dict(record, invite_code=account.invite_code, existing=False)

    async def begin_character_image_exchange(
        self,
        *,
        platform: str,
        adapter: str,
        user_id: str,
        nickname: str | None,
        conversation_id: str,
        points_cost: int,
        image_amount: int,
        config: CommunityConfig,
    ) -> dict[str, Any]:
        identity, account = await self.identity_account(platform, adapter, user_id, lock=True)
        await self.touch_identity(identity, nickname=nickname, conversation_id=conversation_id)
        pending = (
            await self.session.execute(
                select(CommunityCharacterImageExchangeRecord)
                .where(
                    CommunityCharacterImageExchangeRecord.account_id == account.id,
                    CommunityCharacterImageExchangeRecord.status == "pending",
                )
                .order_by(CommunityCharacterImageExchangeRecord.id.asc())
                .with_for_update()
            )
        ).scalars().first()
        if pending is not None:
            return self._character_image_exchange_dict(
                pending, invite_code=account.invite_code, existing=True
            )
        exchange_id = uuid4().hex
        await self._apply_points(
            account,
            delta=-int(points_cost),
            reason="character_image_exchange",
            reference_id=f"character_image_exchange:{exchange_id}:debit",
            conversation_id=conversation_id,
            effective_date=local_date(config),
            metadata={"exchange_id": exchange_id, "image_amount": int(image_amount)},
        )
        record = CommunityCharacterImageExchangeRecord(
            exchange_id=exchange_id,
            account_id=account.id,
            points_cost=int(points_cost),
            image_amount=int(image_amount),
            status="pending",
            idempotency_key=f"xbot-character-image-exchange:{exchange_id}",
            conversation_id=conversation_id,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        self.session.add(record)
        await self.session.flush()
        return self._character_image_exchange_dict(
            record, invite_code=account.invite_code, existing=False
        )

    async def complete_character_image_exchange(self, exchange_id: str) -> dict[str, Any]:
        record = (
            await self.session.execute(
                select(CommunityCharacterImageExchangeRecord)
                .where(CommunityCharacterImageExchangeRecord.exchange_id == exchange_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if record is None:
            raise CommunityError("兑换记录不存在。")
        if record.status == "pending":
            record.status = "completed"
            record.error_code = None
            record.updated_at = utc_now()
            record.completed_at = utc_now()
            await self.session.flush()
        return self._character_image_exchange_dict(record)

    async def fail_character_image_exchange(
        self, exchange_id: str, error_code: str
    ) -> dict[str, Any]:
        record = (
            await self.session.execute(
                select(CommunityCharacterImageExchangeRecord)
                .where(CommunityCharacterImageExchangeRecord.exchange_id == exchange_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if record is None:
            raise CommunityError("兑换记录不存在。")
        if record.status != "pending":
            return self._character_image_exchange_dict(record)
        account = (
            await self.session.execute(
                select(CommunityAccountRecord)
                .where(CommunityAccountRecord.id == record.account_id)
                .with_for_update()
            )
        ).scalar_one()
        await self._apply_points(
            account,
            delta=record.points_cost,
            reason="character_image_exchange_refund",
            reference_id=f"character_image_exchange:{record.exchange_id}:refund",
            conversation_id=record.conversation_id,
            effective_date=utc_now().date(),
            metadata={"exchange_id": record.exchange_id, "error_code": error_code[:64]},
        )
        record.status = "failed"
        record.error_code = error_code[:64]
        record.updated_at = utc_now()
        await self.session.flush()
        return self._character_image_exchange_dict(record)

    async def complete_token_exchange(self, exchange_id: str) -> dict[str, Any]:
        record = (
            await self.session.execute(
                select(CommunityTokenExchangeRecord)
                .where(CommunityTokenExchangeRecord.exchange_id == exchange_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if record is None:
            raise CommunityError("兑换记录不存在。")
        if record.status == "pending":
            record.status = "completed"
            record.error_code = None
            record.updated_at = utc_now()
            record.completed_at = utc_now()
            await self.session.flush()
        return self._exchange_dict(record)

    async def fail_token_exchange(self, exchange_id: str, error_code: str) -> dict[str, Any]:
        record = (
            await self.session.execute(
                select(CommunityTokenExchangeRecord)
                .where(CommunityTokenExchangeRecord.exchange_id == exchange_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if record is None:
            raise CommunityError("兑换记录不存在。")
        if record.status != "pending":
            return self._exchange_dict(record)
        account = (
            await self.session.execute(
                select(CommunityAccountRecord)
                .where(CommunityAccountRecord.id == record.account_id)
                .with_for_update()
            )
        ).scalar_one()
        await self._apply_points(
            account,
            delta=record.points_cost,
            reason="token_exchange_refund",
            reference_id=f"token_exchange:{record.exchange_id}:refund",
            conversation_id=record.conversation_id,
            effective_date=utc_now().date(),
            metadata={"exchange_id": record.exchange_id, "error_code": error_code[:64]},
        )
        record.status = "failed"
        record.error_code = error_code[:64]
        record.updated_at = utc_now()
        await self.session.flush()
        return self._exchange_dict(record)

    @staticmethod
    def _exchange_dict(
        record: CommunityTokenExchangeRecord,
        *,
        invite_code: str | None = None,
        existing: bool = False,
    ) -> dict[str, Any]:
        return {
            "exchange_id": record.exchange_id,
            "account_id": record.account_id,
            "points_cost": record.points_cost,
            "token_amount": record.token_amount,
            "status": record.status,
            "idempotency_key": record.idempotency_key,
            "conversation_id": record.conversation_id,
            "error_code": record.error_code,
            "invite_code": invite_code,
            "existing": existing,
        }

    @staticmethod
    def _character_image_exchange_dict(
        record: CommunityCharacterImageExchangeRecord,
        *,
        invite_code: str | None = None,
        existing: bool = False,
    ) -> dict[str, Any]:
        return {
            "exchange_id": record.exchange_id,
            "account_id": record.account_id,
            "points_cost": record.points_cost,
            "image_amount": record.image_amount,
            "status": record.status,
            "idempotency_key": record.idempotency_key,
            "conversation_id": record.conversation_id,
            "error_code": record.error_code,
            "invite_code": invite_code,
            "existing": existing,
        }

    @staticmethod
    def _ledger_dict(item: CommunityPointLedgerRecord) -> dict[str, Any]:
        return {
            "id": item.id,
            "account_id": item.account_id,
            "delta": item.delta,
            "balance_after": item.balance_after,
            "reason": item.reason,
            "conversation_id": item.conversation_id,
            "effective_date": item.effective_date,
            "created_at": item.created_at,
        }
