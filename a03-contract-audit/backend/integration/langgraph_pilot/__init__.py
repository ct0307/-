"""隔离的 LangGraph 编排原型；正式 API 不导入此包。"""
import os

# 本原型只做本地流程验证，禁止继承宿主的云追踪开关。
os.environ['LANGSMITH_TRACING'] = 'false'
os.environ['LANGCHAIN_TRACING_V2'] = 'false'
os.environ['LANGCHAIN_TRACING'] = 'false'
