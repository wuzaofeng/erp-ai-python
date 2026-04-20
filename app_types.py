'''
Author: zack.wu zack.wu@zuru.com
Date: 2026-04-20 12:17:11
LastEditors: zack.wu zack.wu@zuru.com
LastEditTime: 2026-04-20 12:17:19
FilePath: \erp-ai-nodejsc:\WorkSpace\erp-ai-python\app_types.py
Description: 这是默认设置,请设置`customMade`, 打开koroFileHeader查看配置 进行设置: https://github.com/OBKoro1/koro1FileHeader/wiki/%E9%85%8D%E7%BD%AE
'''
"""
ERP 自定义类型定义 - 对应 src/types.ts
NOTE：此文件名为 app_types.py，避免与 Python 标准库 types 模块冲突
"""
from typing import Optional, List, Literal, Any
from pydantic import BaseModel, Field


# ===================== 请求/响应类型定义 =====================

class ChatMessage(BaseModel):
    """对话历史消息"""
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    """前端发送的对话请求体"""
    message: str = Field(..., min_length=1, max_length=500, description="用户输入的消息")
    history: Optional[List[ChatMessage]] = Field(None, description="对话历史（服务端 Memory 已替代，保留兼容）")
    page_context: Optional[str] = Field(None, alias="pageContext", description="当前 ERP 页面路径")
    erp_token: Optional[str] = Field(None, alias="erpToken", description="ERP 登录 Token（兼容字段）")
    model: Optional[str] = Field(None, description="用户指定的模型")
    skill_key: Optional[str] = Field(None, alias="skillKey", description="预设技能 Key")
    skill: Optional[str] = Field(None, max_length=2000, description="技能/处理规则（自由文本）")

    model_config = {"populate_by_name": True}


class SaveKeyRequest(BaseModel):
    """保存用户 OpenRouter Key 的请求体"""
    openrouterKey: str = Field(..., description="OpenRouter API Key，格式: sk-or-v1-xxxx")
    userId: str = Field(..., description="用户 ID")


class KeyStatusRequest(BaseModel):
    """检查 Key 状态的请求"""
    userId: str


# ===================== ERP CommonQuery 相关类型 =====================

class ErpFilter(BaseModel):
    """CommonQuery 过滤条件（AI Tool 描述格式，对人类友好）"""
    FieldName: str = Field(..., description="字段名，如 VendorName、OrderNo")
    Operator: Literal["=", "contains", ">", "<", ">=", "<=", "!=", "startsWith", "endsWith"]
    Value: str = Field(..., description="过滤值")
    Logic: Optional[Literal["AND", "OR"]] = Field(None, description="逻辑关系，多个条件时使用")


class ErpApiFilter(BaseModel):
    """ERP CommonQuery 接口实际接收的过滤条件格式"""
    fFeild: str = Field(..., description="字段名")
    fComparOperator: str = Field(..., description="ERP 操作符，如 Equal / Like / GreaterThan 等")
    fValue: str = Field(..., description="过滤值")


class CommonQueryRequest(BaseModel):
    """CommonQuery 请求体"""
    TableName: str
    Pagination: dict
    IsChild: bool = False
    Action: str = "GridBrowse"
    formData: dict = {}
    flag: str = "clickSearchBtn"


class ErpQueryToolArgs(BaseModel):
    """AI 调用 query_erp_data 工具时传入的参数"""
    tableName: str = Field(..., description="表名，从 System Prompt 的目录中选取")
    filters: Optional[List[dict]] = Field(None, description="过滤条件")
    pageSize: Optional[int] = Field(None, description="每页条数，默认 20")
    pageIndex: Optional[int] = Field(None, description="页码，默认 1")
    apiPath: Optional[str] = Field(None, description="可选：自定义接口路径（业务模块名）")
    extraBody: Optional[dict] = Field(None, description="可选：追加到请求体的额外字段")
