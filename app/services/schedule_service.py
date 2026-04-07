from collections import defaultdict
from datetime import date, datetime, time, timedelta
from typing import Dict, List, Optional, Set, Tuple
from sqlalchemy import and_, or_, case
from sqlalchemy.orm import Session
from .. import models
from ..models import ShiftRole, ShiftType


class ScheduleService:
    def __init__(self, db: Session):
        self.db = db
    
    def _get_rule(self, schedule_id: int) -> models.ScheduleRule:
        rule = self.db.query(models.ScheduleRule).filter(models.ScheduleRule.schedule_id == schedule_id).first()
        if not rule:
            rule = models.ScheduleRule(schedule_id=schedule_id)
            self.db.add(rule)
            self.db.commit()
            self.db.refresh(rule)
        return rule

    def generate_shifts(self, schedule: models.Schedule, regenerate: bool = False):
        """兼容旧接口：按架构规则生成 day/night primary 班次。"""
        self.generate_mvp(schedule=schedule, regenerate=regenerate)

    def upsert_rule(self, schedule_id: int, payload: Dict) -> models.ScheduleRule:
        rule = self._get_rule(schedule_id)
        for key, value in payload.items():
            setattr(rule, key, value)
        self.db.commit()
        self.db.refresh(rule)
        return rule

    def generate_mvp(
        self,
        schedule: models.Schedule,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        include_secondary: bool = False,
        regenerate: bool = True,
    ) -> Dict:
        members = self.db.query(models.ScheduleMember).join(models.User).filter(
            models.ScheduleMember.schedule_id == schedule.id,
            models.ScheduleMember.is_active == True,
            models.User.is_active == True,
        ).order_by(models.ScheduleMember.order).all()

        if not members:
            return {"generated_count": 0, "unassigned_slots": []}

        period_start = start_date or schedule.start_date.date()
        if end_date:
            period_end = end_date
        elif schedule.repeat_count and schedule.repeat_count > 0:
            period_end = period_start + timedelta(days=schedule.repeat_count - 1)
        elif schedule.end_date:
            period_end = schedule.end_date.date()
        else:
            # 无限重复排班需要一个可计算窗口，默认向后生成 180 天
            period_end = period_start + timedelta(days=180)

        self._get_rule(schedule.id)

        if regenerate:
            self.db.query(models.Shift).filter(
                models.Shift.schedule_id == schedule.id,
                models.Shift.is_locked == False,
                or_(
                    models.Shift.shift_date.is_(None),
                    and_(
                        models.Shift.shift_date >= period_start,
                        models.Shift.shift_date <= period_end,
                    ),
                ),
            ).delete(synchronize_session=False)

        existing_shifts = self.db.query(models.Shift).filter(
            models.Shift.schedule_id == schedule.id,
            models.Shift.shift_date >= period_start,
            models.Shift.shift_date <= period_end,
        ).all()

        # 7x24 模式：按排班组(每行主备)轮转，成员顺序决定配对且顺序有意义。
        pair_rows: List[Tuple[int, Optional[int]]] = []
        for idx in range(0, len(members), 2):
            primary_id = members[idx].user_id
            secondary_id = members[idx + 1].user_id if idx + 1 < len(members) else None
            pair_rows.append((primary_id, secondary_id))

        generated_count = 0
        unassigned_slots = []
        current_date = period_start

        while current_date <= period_end:
            if not pair_rows:
                break

            base_day = start_date or (schedule.start_date.date() if schedule.start_date else period_start)
            pair_idx = (current_date - base_day).days % len(pair_rows)
            pair_primary, pair_secondary = pair_rows[pair_idx]

            has_primary = any(
                s.shift_date == current_date and s.shift_type == ShiftType.FULL_DAY and s.role == ShiftRole.PRIMARY
                for s in existing_shifts
            )
            if not has_primary:
                self.db.add(self._build_shift(schedule, pair_primary, current_date, ShiftType.FULL_DAY, ShiftRole.PRIMARY))
                generated_count += 1

            if include_secondary:
                has_secondary = any(
                    s.shift_date == current_date and s.shift_type == ShiftType.FULL_DAY and s.role == ShiftRole.SECONDARY
                    for s in existing_shifts
                )
                if not has_secondary:
                    if pair_secondary is not None:
                        self.db.add(self._build_shift(schedule, pair_secondary, current_date, ShiftType.FULL_DAY, ShiftRole.SECONDARY))
                        generated_count += 1


            current_date += timedelta(days=1)

        self.db.commit()
        return {"generated_count": generated_count, "unassigned_slots": unassigned_slots}

    def _build_shift(
        self,
        schedule: models.Schedule,
        user_id: int,
        shift_date: date,
        shift_type: ShiftType,
        role: ShiftRole,
    ) -> models.Shift:
        handover_hour = schedule.handover_hour if schedule.handover_hour is not None else 9
        day_start = time(hour=handover_hour, minute=0)
        start = datetime.combine(shift_date, day_start)
        end = datetime.combine(shift_date + timedelta(days=1), day_start)

        return models.Shift(
            schedule_id=schedule.id,
            user_id=user_id,
            shift_type=shift_type,
            role=role,
            shift_date=shift_date,
            start_time=start,
            end_time=end,
        )

    def _week_key(self, target_date: date) -> str:
        iso_year, iso_week, _ = target_date.isocalendar()
        return f"{iso_year}-W{iso_week}"

    def _consecutive_days_if_assign(self, worked_dates: Set[date], target_date: date) -> int:
        consecutive = 1
        cursor = target_date - timedelta(days=1)
        while cursor in worked_dates:
            consecutive += 1
            cursor -= timedelta(days=1)
        return consecutive

    def _can_assign(
        self,
        user_id: int,
        user: models.User,
        target_date: date,
        shift_type: ShiftType,
        role: ShiftRole,
        assigned_today: Set[int],
        stats: Dict,
        rule: models.ScheduleRule,
        volunteers: Set[int],
        holiday_set: Set[str],
        blackout_map: Dict,
        night_primary_by_date: Dict[date, int],
    ) -> bool:
        if user_id in assigned_today:
            return False

        max_shifts = user.max_shifts_per_week if user.max_shifts_per_week is not None else rule.max_shifts_per_week
        max_nights = (
            user.max_night_shifts_per_week
            if user.max_night_shifts_per_week is not None
            else rule.max_night_shifts_per_week
        )
        week_key = self._week_key(target_date)

        if stats[user_id]["weekly"][week_key] >= max_shifts:
            return False

        if shift_type == ShiftType.NIGHT:
            if user.no_nights:
                return False
            if stats[user_id]["night_weekly"][week_key] >= max_nights:
                return False

        blackout = blackout_map.get(str(target_date))
        if blackout:
            if user_id in blackout.get("disallow_members", []):
                return False
            if shift_type == ShiftType.NIGHT and blackout.get("disallow_nights"):
                return False

        if rule.use_volunteers_only and str(target_date) in holiday_set and user_id not in volunteers:
            return False

        if (
            shift_type == ShiftType.NIGHT
            and role == ShiftRole.PRIMARY
            and rule.avoid_consecutive_nights
            and night_primary_by_date.get(target_date - timedelta(days=1)) == user_id
        ):
            return False

        consecutive_days = self._consecutive_days_if_assign(stats[user_id]["worked_dates"], target_date)
        if consecutive_days > rule.max_consecutive_work_days:
            return False

        return True

    def validate_mvp(
        self,
        schedule: models.Schedule,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> Dict:
        period_start = start_date or schedule.start_date.date()
        if end_date:
            period_end = end_date
        elif schedule.repeat_count and schedule.repeat_count > 0:
            period_end = period_start + timedelta(days=schedule.repeat_count - 1)
        elif schedule.end_date:
            period_end = schedule.end_date.date()
        else:
            period_end = period_start + timedelta(days=180)
        rule = self._get_rule(schedule.id)

        shifts = self.db.query(models.Shift).filter(
            models.Shift.schedule_id == schedule.id,
            models.Shift.shift_date >= period_start,
            models.Shift.shift_date <= period_end,
        ).all()

        members = self.db.query(models.ScheduleMember).join(models.User).filter(
            models.ScheduleMember.schedule_id == schedule.id,
            models.ScheduleMember.is_active == True,
            models.User.is_active == True,
        ).all()
        member_ids = {m.user_id for m in members}

        self.db.query(models.ValidationIssue).filter(models.ValidationIssue.schedule_id == schedule.id).delete()

        errors = []
        warnings = []
        by_date: Dict[date, Dict[Tuple[ShiftType, ShiftRole], models.Shift]] = defaultdict(dict)
        weekly_total = defaultdict(lambda: defaultdict(int))
        weekly_night = defaultdict(lambda: defaultdict(int))
        worked_dates = defaultdict(set)
        night_primary_by_date: Dict[date, int] = {}

        def add_issue(level: str, issue_type: str, message: str, member_id: Optional[int] = None, issue_date: Optional[date] = None):
            payload = {"type": issue_type, "member_id": member_id, "date": issue_date, "message": message}
            if level == "error":
                errors.append(payload)
            else:
                warnings.append(payload)

            self.db.add(models.ValidationIssue(
                schedule_id=schedule.id,
                issue_level=level,
                issue_type=issue_type,
                member_id=member_id,
                issue_date=issue_date,
                message=message,
            ))

        for shift in shifts:
            shift_day = shift.shift_date or shift.start_time.date()
            by_date[shift_day][(shift.shift_type, shift.role)] = shift

            if shift.user_id not in member_ids:
                add_issue("error", "INVALID_MEMBER", "班次引用了不在排班成员中的用户", shift.user_id, shift_day)

            week_key = self._week_key(shift_day)
            weekly_total[shift.user_id][week_key] += 1
            if shift.shift_type == ShiftType.NIGHT:
                weekly_night[shift.user_id][week_key] += 1
            worked_dates[shift.user_id].add(shift_day)

            if shift.shift_type == ShiftType.NIGHT and shift.role == ShiftRole.PRIMARY:
                night_primary_by_date[shift_day] = shift.user_id

        cursor = period_start
        while cursor <= period_end:
            day_items = by_date.get(cursor, {})
            if (ShiftType.FULL_DAY, ShiftRole.PRIMARY) not in day_items:
                add_issue("error", "MISSING_REQUIRED_SHIFT", "缺少 full_day.primary", issue_date=cursor)
            cursor += timedelta(days=1)

        users = {member.user_id: member.user for member in members}
        for user_id, user in users.items():
            user_weekly = weekly_total[user_id]
            user_night_weekly = weekly_night[user_id]
            max_shifts = user.max_shifts_per_week if user.max_shifts_per_week is not None else rule.max_shifts_per_week
            max_nights = (
                user.max_night_shifts_per_week
                if user.max_night_shifts_per_week is not None
                else rule.max_night_shifts_per_week
            )

            for week, value in user_weekly.items():
                if value > max_shifts:
                    add_issue("error", "WEEKLY_LIMIT_EXCEEDED", f"周班次 {value} 超过上限 {max_shifts}", user_id)

            for week, value in user_night_weekly.items():
                if value > max_nights:
                    add_issue("error", "WEEKLY_NIGHT_LIMIT_EXCEEDED", f"周夜班 {value} 超过上限 {max_nights}", user_id)

            dates = sorted(worked_dates[user_id])
            streak = 0
            prev = None
            for d in dates:
                if prev and d == prev + timedelta(days=1):
                    streak += 1
                else:
                    streak = 1
                if streak > rule.max_consecutive_work_days:
                    add_issue("error", "CONSECUTIVE_WORK_DAYS", "连续工作天数超过上限", user_id, d)
                prev = d

        if rule.avoid_consecutive_nights:
            pass

        total_per_member = {
            uid: sum(weekly_total[uid].values())
            for uid in member_ids
        }
        if total_per_member:
            max_total = max(total_per_member.values())
            min_total = min(total_per_member.values())
            if max_total - min_total > rule.fairness_threshold:
                overloaded = [uid for uid, value in total_per_member.items() if value == max_total]
                add_issue(
                    "warning",
                    "FAIRNESS_VIOLATION",
                    f"班次分布差值 {max_total - min_total} 超过阈值 {rule.fairness_threshold}",
                    overloaded[0],
                )

        holiday_set = {str(item) for item in (rule.holiday_dates or [])}
        volunteers = set(rule.volunteer_member_ids or [])
        blackout_map = {
            item["date"]: item for item in (rule.blackout_dates or []) if isinstance(item, dict) and item.get("date")
        }
        for shift in shifts:
            shift_day = shift.shift_date or shift.start_time.date()
            day_str = str(shift_day)
            if rule.use_volunteers_only and day_str in holiday_set and shift.user_id not in volunteers:
                add_issue("error", "HOLIDAY_POLICY_VIOLATION", "节假日班次仅允许志愿者", shift.user_id, shift_day)

            blackout = blackout_map.get(day_str)
            if blackout and shift.user_id in blackout.get("disallow_members", []):
                add_issue("error", "BLACKOUT_MEMBER_VIOLATION", "blackout 日期包含禁排成员", shift.user_id, shift_day)
            if blackout and blackout.get("disallow_nights") and shift.shift_type == ShiftType.NIGHT:
                add_issue("error", "BLACKOUT_NIGHT_VIOLATION", "blackout 日期禁止夜班", shift.user_id, shift_day)

        self.db.commit()
        return {"is_valid": len(errors) == 0, "errors": errors, "warnings": warnings}
    
    def get_current_oncall(self, schedule_id: int) -> models.Shift:
        """获取当前值班的班次"""
        context = self.get_current_oncall_context(schedule_id)
        return context["shift"] if context else None

    def get_current_oncall_context(self, schedule_id: int, at_time: Optional[datetime] = None) -> Optional[Dict]:
        now = at_time or datetime.now()

        def query_current(model, shift_kind: str):
            role_priority = case(
                (model.role == ShiftRole.PRIMARY, 0),
                (model.role == ShiftRole.SECONDARY, 1),
                else_=99,
            )
            shift = self.db.query(model).filter(
                model.schedule_id == schedule_id,
                model.start_time <= now,
                model.end_time >= now,
            ).order_by(role_priority.asc(), model.start_time.desc()).first()
            if not shift:
                return None
            return {
                "shift": shift,
                "shift_kind": shift_kind,
                "role": shift.role,
                "user": shift.user,
            }

        return query_current(models.SpecialShift, "special") or query_current(models.Shift, "normal")
    
    def get_next_oncall(self, schedule_id: int) -> models.Shift:
        """获取下一个值班班次"""
        now = datetime.now()
        shift = self.db.query(models.Shift).filter(
            models.Shift.schedule_id == schedule_id,
            models.Shift.start_time > now
        ).order_by(models.Shift.start_time).first()
        
        return shift

    def get_member_shifts(
        self,
        schedule_id: int,
        user_id: int,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> List[models.Shift]:
        query = self.db.query(models.Shift).filter(
            models.Shift.schedule_id == schedule_id,
            models.Shift.user_id == user_id,
        )
        if start_date:
            query = query.filter(models.Shift.shift_date >= start_date)
        if end_date:
            query = query.filter(models.Shift.shift_date <= end_date)
        return query.order_by(models.Shift.start_time).all()

    def get_today_assignments(self, schedule: models.Schedule, target_date: Optional[date] = None) -> Dict:
        day = target_date or datetime.now().date()
        shifts = self.db.query(models.Shift).filter(
            models.Shift.schedule_id == schedule.id,
            models.Shift.shift_date == day,
        ).all()
        special_shifts = self.db.query(models.SpecialShift).filter(
            models.SpecialShift.schedule_id == schedule.id,
            models.SpecialShift.shift_date == day,
        ).all()

        assignments = {
            "full_day": {"primary": None, "secondary": None},
        }
        for shift in shifts:
            shift_key = shift.shift_type.value if shift.shift_type == ShiftType.FULL_DAY else "full_day"
            role_key = shift.role.value
            assignments.setdefault(shift_key, {})[role_key] = shift.user
        for shift in special_shifts:
            shift_key = shift.shift_type.value if shift.shift_type == ShiftType.FULL_DAY else "full_day"
            role_key = shift.role.value
            assignments.setdefault(shift_key, {})[role_key] = shift.user
        return assignments

