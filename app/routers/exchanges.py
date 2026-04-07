from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from datetime import datetime
from ..database import get_db
from .. import models, schemas

router = APIRouter()


@router.post("/", response_model=schemas.ExchangeRequestResponse, status_code=status.HTTP_201_CREATED)
def create_exchange_request(
    exchange: schemas.ExchangeRequestCreate,
    db: Session = Depends(get_db)
):
    # 验证班次
    shift = db.query(models.Shift).filter(models.Shift.id == exchange.shift_id).first()
    if not shift:
        raise HTTPException(status_code=404, detail="班次不存在")
    
    # 验证请求人必须是当前班次的负责人
    if shift.user_id != exchange.requester_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="您不是当前班次的负责人"
        )

    if exchange.requester_id == exchange.responder_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="请求人与接班人不能相同"
        )

    responder = db.query(models.User).filter(
        models.User.id == exchange.responder_id,
        models.User.is_active == True,
    ).first()
    if not responder:
        raise HTTPException(status_code=404, detail="接班人不存在或不可用")

    existing_pending = db.query(models.ExchangeRequest).filter(
        models.ExchangeRequest.shift_id == exchange.shift_id,
        models.ExchangeRequest.status == "pending",
    ).first()
    if existing_pending:
        raise HTTPException(status_code=400, detail="该班次已有待处理调班申请")
    
    db_exchange = models.ExchangeRequest(
        requester_id=exchange.requester_id,
        responder_id=exchange.responder_id,
        shift_id=exchange.shift_id,
        reason=exchange.reason
    )
    
    db.add(db_exchange)
    db.commit()
    db.refresh(db_exchange)
    
    return db_exchange


@router.get("/", response_model=List[schemas.ExchangeRequestResponse])
def list_exchange_requests(
    user_id: int = None,
    status: str = None,
    db: Session = Depends(get_db)
):
    query = db.query(models.ExchangeRequest)
    
    if user_id:
        query = query.filter(
            (models.ExchangeRequest.requester_id == user_id) |
            (models.ExchangeRequest.responder_id == user_id)
        )
    if status:
        query = query.filter(models.ExchangeRequest.status == status)
    
    return query.all()


@router.post("/{exchange_id}/respond")
def respond_exchange_request(
    exchange_id: int,
    response: schemas.ExchangeRequestUpdate,
    db: Session = Depends(get_db)
):
    exchange = db.query(models.ExchangeRequest).filter(
        models.ExchangeRequest.id == exchange_id
    ).first()
    
    if not exchange:
        raise HTTPException(status_code=404, detail="换班申请不存在")
    
    if exchange.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="该申请已处理"
        )
    
    # 更新申请状态
    exchange.status = response.status
    exchange.responded_at = datetime.now()
    
    # 如果同意，交换班次
    if response.status == "approved":
        shift = db.query(models.Shift).filter(models.Shift.id == exchange.shift_id).first()
        # 创建新的班次记录（交换后的）
        original_user_id = shift.user_id
        shift.user_id = exchange.responder_id
        
        # 这里可以添加更复杂的逻辑，比如创建对等的换班记录
        # 或者创建一个临时的班次调整
    
    db.commit()
    db.refresh(exchange)
    
    return exchange


@router.delete("/{exchange_id}")
def cancel_exchange_request(exchange_id: int, db: Session = Depends(get_db)):
    exchange = db.query(models.ExchangeRequest).filter(
        models.ExchangeRequest.id == exchange_id
    ).first()
    
    if not exchange:
        raise HTTPException(status_code=404, detail="换班申请不存在")
    
    if exchange.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="只能取消待处理的申请"
        )
    
    db.delete(exchange)
    db.commit()
    
    return {"message": "换班申请已取消"}
