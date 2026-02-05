"""
Market Insight Agent - Agent Nodes
===================================
LangGraph Agent 节点定义，实现工作流的各个处理步骤。

设计思想：
1. 每个节点是一个独立的处理单元
2. 节点间通过 State 传递数据
3. 节点可以被复用于不同的 Agent

这里定义的是通用节点，各 Agent 可以根据需要组合使用。
"""

# 节点模块包，包含以下子模块：
# - template_parser: 模板解析节点
# - data_collector: 数据采集节点
# - content_generator: 内容生成节点
# - report_renderer: 报告渲染节点

from app.agents.nodes.template_parser import TemplateParserNode
from app.agents.nodes.data_collector import DataCollectorNode
from app.agents.nodes.content_generator import ContentGeneratorNode
from app.agents.nodes.report_renderer import ReportRendererNode

__all__ = [
    "TemplateParserNode",
    "DataCollectorNode",
    "ContentGeneratorNode",
    "ReportRendererNode",
]
