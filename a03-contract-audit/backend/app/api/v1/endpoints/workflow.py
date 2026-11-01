"""工作流快照与授权人工终审。"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session
from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.models import User
from app.services.audit.finalization import workflow_view, finalize_workflow

router=APIRouter()


class FinalReview(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
    expected_generation:int=Field(ge=0)
    expected_version:int=Field(ge=0)
    review_fingerprint:str=Field(min_length=64,max_length=64)
    comment:str=Field(min_length=2,max_length=2000)
    quality_comment:str=Field(default='',max_length=2000)
    conflict_resolutions:dict[str,str]=Field(default_factory=dict,max_length=100)


@router.get('/{contract_id}')
def get_workflow(contract_id:int,db:Session=Depends(get_db),user:User=Depends(get_current_user)):
    return workflow_view(db,contract_id,user)


@router.post('/{contract_id}/finalize')
def finalize(contract_id:int,payload:FinalReview,db:Session=Depends(get_db),user:User=Depends(get_current_user)):
    return finalize_workflow(db,contract_id,user,payload.model_dump())
