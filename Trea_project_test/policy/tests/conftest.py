"""
Pytest Configuration and Shared Fixtures

提供测试所需的共享 fixtures 和配置。
"""

import sys
import os
import tempfile
import logging

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.getLogger("jieba").setLevel(logging.WARNING)


@pytest.fixture(scope="session")
def test_data_dir():
    """测试数据目录"""
    return os.path.join(os.path.dirname(__file__), "fixtures")


@pytest.fixture
def temp_dir():
    """临时目录 fixture"""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def sample_short_text():
    """短文本样本（约200字）"""
    return """
中共中央办公厅 国务院办公厅印发《关于加强社会主义法治建设的意见》
为了全面贯彻党的二十大精神，深入推进社会主义法治建设，提出如下意见。
一、总体要求
坚持依法治国、依法执政、依法行政共同推进，坚持法治国家、法治政府、法治社会一体建设。
二、主要任务
（三）加强重点领域立法
完善国家安全领域法律制度，加强网络安全、数据安全、人工智能等领域立法。
"""


@pytest.fixture
def sample_medium_text():
    """中等文本样本（约1500字）"""
    base = """
中共中央 国务院关于新时代加快完善社会主义市场经济体制的意见

为贯彻落实党的二十大精神，构建更加系统完备、更加成熟定型的高水平社会主义市场经济体制，
提出如下意见。

一、总体要求
（1）指导思想
以习近平新时代中国特色社会主义思想为指导，全面贯彻党的基本理论、基本路线、基本方略，
统筹推进经济建设、政治建设、文化建设、社会建设、生态文明建设。

（2）基本原则
坚持公有制为主体、多种所有制经济共同发展，增强微观主体活力。
坚持按劳分配为主体、多种分配方式并存，增加城乡居民收入。
坚持发挥市场在资源配置中的决定性作用，更好发挥政府作用。

二、主要任务
（3）深化国有企业改革
加快国有经济布局优化和结构调整，积极稳妥推进混合所有制改革。

（4）完善支持非公有制经济发展的法治环境
依法保护各种所有制经济产权和合法权益，坚决破除制约市场竞争的各类障碍和隐性壁垒。

（5）推进要素市场化配置改革
建立健全统一开放的要素市场，促进劳动力、人才社会性流动。

三、保障措施
（6）加强党的领导
坚持党对经济工作的集中统一领导，确保社会主义市场经济体制改革方向。

（7）完善法律法规
加快形成以宪法为根本的法律体系，完善社会主义市场经济法律制度。
"""
    return base * 3


@pytest.fixture
def sample_policy_document(temp_dir, sample_short_text):
    """创建临时政策文档"""
    doc_path = os.path.join(temp_dir, "policy_test.txt")
    with open(doc_path, "w", encoding="utf-8") as f:
        f.write(sample_short_text)
    return doc_path


@pytest.fixture
def sample_medium_document(temp_dir, sample_medium_text):
    """创建中等大小临时政策文档"""
    doc_path = os.path.join(temp_dir, "policy_medium.txt")
    with open(doc_path, "w", encoding="utf-8") as f:
        f.write(sample_medium_text)
    return doc_path


@pytest.fixture
def main_window():
    """创建 MainWindow 实例"""
    from ui.main_window import MainWindow
    return MainWindow()


@pytest.fixture
def nlp_manager():
    """创建 NLPThreadManager 实例"""
    from core.nlp_thread import NLPThreadManager
    manager = NLPThreadManager()
    yield manager


@pytest.fixture
def document_loader():
    """创建 DocumentLoader 实例"""
    from importers.document_loader import DocumentLoader
    return DocumentLoader()


@pytest.fixture
def sample_analysis_result():
    """创建示例分析结果"""
    from core.algorithms import AnalysisResult
    return AnalysisResult(
        summary="这是一份关于社会主义法治建设的政策文件分析。",
        key_topics=["依法治国", "法治政府", "法治社会", "立法", "执法"],
        new_terms=[
            {"term": "社会主义法治体系", "frequency": 5, "category": "政策术语"},
            {"term": "法治中国", "frequency": 3, "category": "政策术语"}
        ],
        warnings=["注意：部分条款需进一步明确"],
        mode="offline",
        source_info={"word_count": 500}
    )
