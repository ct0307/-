"""ORM 模型定义。骨架：定义核心表结构，字段可随业务细化。

企业交付要点：合同敏感数据、完整审核链、审计日志留痕。
"""
from datetime import datetime

from sqlalchemy import String, Integer, Text, DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16), default="business")  # business/legal/finance/admin
    department: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Contract(Base):
    __tablename__ = "contracts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    filename: Mapped[str] = mapped_column(String(255))
    storage_path: Mapped[str] = mapped_column(String(512))  # 私有化本地存储路径
    contract_type: Mapped[str] = mapped_column(String(64), default="")
    department: Mapped[str] = mapped_column(String(64), default="")  # 访问隔离维度
    status: Mapped[str] = mapped_column(String(32), default="uploaded")  # uploaded/parsed/auditing/done
    uploaded_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    risks: Mapped[list["Risk"]] = relationship(back_populates="contract")


class Risk(Base):
    __tablename__ = "risks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    contract_id: Mapped[int] = mapped_column(ForeignKey("contracts.id"))
    level: Mapped[str] = mapped_column(String(8))  # high/medium/low
    category: Mapped[str] = mapped_column(String(64))
    agent: Mapped[str] = mapped_column(String(16), default="legal")  # 风险归属智能体：legal/finance
    original_text: Mapped[str] = mapped_column(Text)   # 原文引用
    basis: Mapped[str] = mapped_column(Text)           # 依据来源（法规/规则，来自 RAG）
    suggestion: Mapped[str] = mapped_column(Text)      # 建议修改
    confidence: Mapped[int] = mapped_column(Integer, default=0)  # 置信度 0-100
    review_status: Mapped[str] = mapped_column(String(16), default="pending")  # pending/confirmed/ignored/to_modify
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    contract: Mapped["Contract"] = relationship(back_populates="risks")


class KnowledgeChunk(Base):
    """知识库切片：法规/行业规则/合同模板，供 RAG 检索。

    向量以 JSON 文本存储，SQLite/PostgreSQL 通用、可移植。
    交付期在 PostgreSQL 上可另建 pgvector 原生 Vector 列 + 距离索引优化检索性能。
    """
    __tablename__ = "knowledge_chunks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    category: Mapped[str] = mapped_column(String(32), index=True)  # law/rule/template
    source: Mapped[str] = mapped_column(String(255), default="")   # 来源（法规名/文件名）
    content: Mapped[str] = mapped_column(Text)                     # 切片正文
    embedding: Mapped[str] = mapped_column(Text, default="")       # JSON 序列化的向量
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuditLog(Base):
    """审计日志：谁在何时对什么做了什么。企业追责与合规刚需。"""
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(64))       # login/upload/audit/update_risk/export...
    target: Mapped[str] = mapped_column(String(128), default="")
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
