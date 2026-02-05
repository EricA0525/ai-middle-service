"""
Market Insight Agent - Base Agent
==================================
LangGraph Agent 基类，定义统一的 Agent 接口和状态管理。

设计思想：
1. 所有 Agent 继承自 BaseAgent，保证接口一致性
2. 使用 LangGraph 的 StateGraph 进行工作流编排
3. 统一的状态定义和进度回调机制

LangGraph 核心概念：
- State: 工作流状态，在节点间传递
- Node: 处理节点，执行具体逻辑
- Edge: 连接节点，控制流转
- Graph: 状态图，编排整个工作流
"""

from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, List, Optional, TypedDict

from loguru import logger


class AgentState(TypedDict, total=False):
    """
    Agent 状态定义
    
    所有节点共享此状态，通过键值传递数据。
    设计为 TypedDict 以获得类型提示支持。
    """
    
    # ========== 输入参数 ==========
    task_id: str                    # 任务 ID
    task_type: str                  # 任务类型
    params: Dict[str, Any]          # 用户输入参数
    
    # ========== 模板相关 ==========
    template_path: str              # 模板文件路径
    template_structure: Dict        # 解析后的模板结构
    report_sections: List[Dict]     # 报告各板块定义
    
    # ========== 数据采集 ==========
    collected_data: Dict[str, Any]  # 采集到的原始数据
    # - tavily_results: 全网搜索结果
    # - xiaohongshu_data: 小红书数据
    # - douyin_data: 抖音数据
    
    # ========== 内容生成 ==========
    generated_content: Dict[str, str]  # 各板块生成的内容
    svg_charts: Dict[str, str]         # 生成的 SVG 图表
    
    # ========== 输出 ==========
    html_report: str                # 最终生成的 HTML 报告
    
    # ========== 进度追踪 ==========
    current_step: str               # 当前步骤名称
    progress: int                   # 进度百分比 (0-100)
    error: Optional[str]            # 错误信息


class BaseAgent(ABC):
    """
    Agent 基类
    
    定义了 Agent 的基本结构和生命周期方法。
    子类需要实现 build_graph() 方法来定义具体的工作流。
    """
    
    def __init__(
        self,
        progress_callback: Optional[Callable[[int, str], None]] = None,
    ):
        """
        初始化 Agent
        
        Args:
            progress_callback: 进度回调函数，参数为 (progress, message)
        """
        self.progress_callback = progress_callback
        self.graph = None
    
    @abstractmethod
    def build_graph(self):
        """
        构建 LangGraph 状态图
        
        子类必须实现此方法，定义：
        1. 节点 (Nodes)
        2. 边 (Edges)
        3. 条件分支 (Conditional Edges)
        
        示例：
            graph = StateGraph(AgentState)
            graph.add_node("parse_template", self.parse_template_node)
            graph.add_node("collect_data", self.collect_data_node)
            graph.add_edge("parse_template", "collect_data")
            ...
            return graph.compile()
        """
        pass
    
    @abstractmethod
    async def run(self, params: Dict[str, Any]) -> str:
        """
        执行 Agent 工作流
        
        Args:
            params: 用户输入参数
            
        Returns:
            生成的 HTML 报告内容
        """
        pass
    
    def update_progress(self, progress: int, message: str) -> None:
        """
        更新进度
        
        Args:
            progress: 进度百分比 (0-100)
            message: 当前步骤描述
        """
        logger.debug(f"Progress: {progress}% - {message}")
        if self.progress_callback:
            self.progress_callback(progress, message)
    
    def _create_initial_state(
        self,
        task_id: str,
        task_type: str,
        params: Dict[str, Any],
    ) -> AgentState:
        """
        创建初始状态
        
        Args:
            task_id: 任务 ID
            task_type: 任务类型
            params: 用户输入参数
            
        Returns:
            初始化的 AgentState
        """
        return AgentState(
            task_id=task_id,
            task_type=task_type,
            params=params,
            collected_data={},
            generated_content={},
            svg_charts={},
            progress=0,
            current_step="初始化",
        )
