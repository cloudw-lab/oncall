#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
初始化测试数据脚本
"""
import sys
from datetime import datetime, timedelta
sys.path.append('.')

from app.database import SessionLocal, engine, Base
from app import models
from app.security import hash_password
from app.utils.crypto import encrypt_phone

# 创建所有表
Base.metadata.create_all(bind=engine)

def init_data():
    db = SessionLocal()
    default_password_hash = hash_password("password123")
    
    try:
        # 创建或复用测试用户（幂等）
        print("创建测试用户...")
        seed_users = [
            {
                "username": "zhangsan",
                "email": "zhangsan@example.com",
                "full_name": "张三",
                "phone": "13800138001",
                "team": "SRE",
                "role": "admin",
                "skills": ["linux", "k8s"],
                "no_nights": False,
            },
            {
                "username": "lisi",
                "email": "lisi@example.com",
                "full_name": "李四",
                "phone": "13800138002",
                "team": "SRE",
                "role": "operator",
                "skills": ["db", "sql"],
                "no_nights": False,
            },
            {
                "username": "wangwu",
                "email": "wangwu@example.com",
                "full_name": "王五",
                "phone": "13800138003",
                "team": "Network",
                "role": "operator",
                "skills": ["network"],
                "no_nights": True,
            },
            {
                "username": "zhaoliu",
                "email": "zhaoliu@example.com",
                "full_name": "赵六",
                "phone": "13800138004",
                "team": "DBA",
                "role": "operator",
                "skills": ["mysql", "backup"],
                "no_nights": False,
            },
            {
                "username": "qianqi",
                "email": "qianqi@example.com",
                "full_name": "钱七",
                "phone": "13800138005",
                "team": "SRE",
                "role": "operator",
                "skills": ["monitoring", "automation"],
                "no_nights": False,
            },
        ]

        users = []
        for item in seed_users:
            db_user = db.query(models.User).filter(models.User.username == item["username"]).first()
            if not db_user:
                db_user = models.User(
                    username=item["username"],
                    email=item["email"],
                    full_name=item["full_name"],
                    phone=encrypt_phone(item["phone"]),
                    team=item["team"],
                    role=item.get("role", "operator"),
                    skills=item["skills"],
                    no_nights=item["no_nights"],
                    hashed_password=default_password_hash,
                    is_active=True,
                )
                db.add(db_user)
            else:
                db_user.email = item["email"]
                db_user.full_name = item["full_name"]
                db_user.phone = encrypt_phone(item["phone"])
                db_user.team = item["team"]
                db_user.role = item.get("role", db_user.role or "operator")
                db_user.skills = item["skills"]
                db_user.no_nights = item["no_nights"]
                db_user.hashed_password = default_password_hash
                db_user.is_active = True
            users.append(db_user)

        db.commit()
        for user in users:
            db.refresh(user)

        print(f"✓ 已准备 {len(users)} 个测试用户")
        for user in users:
            print(f"  - {user.full_name} ({user.username})")
        
        # 创建或复用测试排班表
        print("\n创建测试排班表...")
        schedule = db.query(models.Schedule).filter(models.Schedule.name == "一线值班").first()
        if not schedule:
            schedule = models.Schedule(
                name="一线值班",
                description="工作日白天值班安排",
                rotation_type=models.RotationType.WEEKLY,
                rotation_interval=1,
                handover_hour=9,
                repeat_count=0,
                start_date=datetime.now().replace(hour=0, minute=0, second=0, microsecond=0),
                end_date=None
            )
            db.add(schedule)
        else:
            schedule.description = "工作日白天值班安排"
            schedule.rotation_type = models.RotationType.WEEKLY
            schedule.rotation_interval = 1
            schedule.handover_hour = 9
            schedule.repeat_count = 0
            schedule.start_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            schedule.end_date = None
            schedule.is_active = True

        db.commit()
        db.refresh(schedule)
        
        print(f"✓ 已创建排班表：{schedule.name}")
        
        # 添加排班成员
        print("\n添加排班成员...")
        for idx, user in enumerate(users):
            member = db.query(models.ScheduleMember).filter(
                models.ScheduleMember.schedule_id == schedule.id,
                models.ScheduleMember.user_id == user.id,
            ).first()
            if not member:
                member = models.ScheduleMember(
                    schedule_id=schedule.id,
                    user_id=user.id,
                    order=idx,
                    is_active=True,
                )
                db.add(member)
            else:
                member.order = idx
                member.is_active = True
        
        db.commit()
        print(f"✓ 已添加 {len(users)} 个成员到排班表")
        
        # 生成班次
        print("\n生成班次...")
        from app.services.schedule_service import ScheduleService
        schedule_service = ScheduleService(db)
        schedule_service.upsert_rule(schedule.id, {
            "max_shifts_per_week": 7,
            "max_night_shifts_per_week": 4,
            "avoid_consecutive_nights": True,
            "max_consecutive_work_days": 7,
            "fairness_threshold": 2,
        })
        schedule_service.generate_mvp(schedule, include_secondary=True, regenerate=True)
        
        # 统计生成的班次数量
        shifts_count = db.query(models.Shift).filter(
            models.Shift.schedule_id == schedule.id
        ).count()
        
        print(f"✓ 已生成 {shifts_count} 个班次")
        
        # 获取当前值班人员
        current_shift = schedule_service.get_current_oncall(schedule.id)
        if current_shift:
            current_user = db.query(models.User).filter(
                models.User.id == current_shift.user_id
            ).first()
            print(f"\n📅 当前值班人员：{current_user.full_name}")
            print(f"   时间：{current_shift.start_time.strftime('%Y-%m-%d')} 至 {current_shift.end_time.strftime('%Y-%m-%d')}")
        
        print("\n✅ 测试数据初始化完成！")
        
    except Exception as e:
        print(f"\n❌ 初始化失败：{e}")
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    init_data()
