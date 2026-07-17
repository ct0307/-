"""给演示合同（storage/demo/ 占位路径，无真实文件）直接写入 elements_json。

真实上传合同（绝对路径）通过 LLM 回填脚本处理，此脚本只处理演示占位合同。
幂等：已有 party_a 的合同跳过。用法：./.venv/Scripts/python.exe -m scripts.seed_demo_elements
"""
import json
import os
import sys
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parent.parent
os.chdir(_BACKEND_DIR)
sys.path.insert(0, str(_BACKEND_DIR))

from app.db.session import SessionLocal
from app.models.models import Contract

# 演示合同要素：按 filename 设计真实可信的甲方/标的/收付款节点
_DEMO_ELEMENTS: dict[str, dict] = {
    "2026年度办公用品采购框架合同.pdf": {
        "party_a": "浙江宏达科技集团有限公司",
        "party_b": "杭州办公优品文具有限公司",
        "subject": "2026年度办公用品（文具、耗材、设备配件）采购，年采购总量不低于合同约定品类",
        "payment_terms": "按季度结算，每季末30日内支付当季货款，年末汇总核对后15日内结清尾款",
        "amount": "180万元",
        "duration": "2026年1月1日至2026年12月31日",
    },
    "XX园区安防设备采购合同.pdf": {
        "party_a": "浙江宏达科技集团有限公司",
        "party_b": "海康威视数字技术股份有限公司",
        "subject": "园区安防监控系统设备采购，含摄像头、门禁系统、控制主机及安装调试",
        "payment_terms": "合同签订后5个工作日内支付预付款30%，设备验收合格后30日内支付尾款70%",
        "amount": "320万元",
        "duration": "12个月（含安装调试及质保期）",
    },
    "原材料供应长期协议.docx": {
        "party_a": "浙江宏达科技集团有限公司",
        "party_b": "宁波兴业原材料贸易有限公司",
        "subject": "电子元器件、PCB基板等核心原材料长期稳定供应",
        "payment_terms": "月结，每月10日前结算上月货款；单笔超50万元须付30%预付款",
        "amount": "年度框架金额1200万元",
        "duration": "2025年7月1日至2027年6月30日",
    },
    "智能巡检系统软件外包开发合同.pdf": {
        "party_a": "浙江宏达科技集团有限公司",
        "party_b": "杭州智云软件科技有限公司",
        "subject": "工厂智能巡检管理系统软件开发，含移动端App、后台管理平台及数据分析模块",
        "payment_terms": "签约后30%预付款；需求评审通过付20%；测试通过付30%；验收合格付尾款20%",
        "amount": "85万元",
        "duration": "6个月",
    },
    "移动端App定制开发协议.docx": {
        "party_a": "浙江宏达科技集团有限公司",
        "party_b": "深圳腾越移动技术有限公司",
        "subject": "企业员工移动办公App定制开发，含考勤、审批、消息推送及ERP系统对接",
        "payment_terms": "签约后付首期款40%；UI评审通过付20%；功能完成付30%；验收后10日付尾款10%",
        "amount": "42万元",
        "duration": "4个月",
    },
    "算法模型联合研发合作合同.pdf": {
        "party_a": "浙江宏达科技集团有限公司",
        "party_b": "浙江大学计算机科学与技术学院",
        "subject": "工业质检图像识别算法模型联合研发，知识产权共同拥有，商业收益按6:4分成",
        "payment_terms": "研发经费分三期：启动时40%，中期评审通过30%，成果验收后30%",
        "amount": "150万元（研发经费）",
        "duration": "18个月",
    },
    "品牌年度推广服务合同.pdf": {
        "party_a": "浙江宏达科技集团有限公司",
        "party_b": "上海星耀广告传媒有限公司",
        "subject": "企业品牌年度整合营销推广，含线上媒体投放、活动策划执行及品牌内容制作",
        "payment_terms": "按季预付，每季初10日内支付当季服务费；KPI未达标下季扣减5%",
        "amount": "600万元/年",
        "duration": "12个月",
    },
    "线上渠道代运营合作协议.docx": {
        "party_a": "浙江宏达科技集团有限公司",
        "party_b": "杭州聚流电商运营有限公司",
        "subject": "天猫、京东、抖音等电商平台旗舰店代运营，含商品上架、活动推广及客服",
        "payment_terms": "基础服务费月结，GMV超保底目标部分3%提成，每月20日前结算上月费用",
        "amount": "基础服务费24万元/年+提成",
        "duration": "12个月，自动续约",
    },
    "会展活动策划执行合同.pdf": {
        "party_a": "浙江宏达科技集团有限公司",
        "party_b": "杭州盛典文化会展有限公司",
        "subject": "2026年企业年度峰会及行业展会参展全程策划、搭建、执行服务",
        "payment_terms": "签约后3个工作日内支付50%定金；活动结束后7个工作日内支付尾款50%",
        "amount": "58万元",
        "duration": "活动筹备及执行期共3个月",
    },
    "办公场地租赁合同.pdf": {
        "party_a": "浙江宏达科技集团有限公司",
        "party_b": "杭州西湖区国际商务中心有限公司",
        "subject": "杭州市西湖区某大厦12层整层办公场地租赁，建筑面积2800平方米",
        "payment_terms": "每季首月10日前预付当季租金；押金3个月租金，租约期满无损耗退还",
        "amount": "336万元/年",
        "duration": "3年，2024年1月1日至2026年12月31日",
    },
    "劳务派遣服务协议.docx": {
        "party_a": "浙江宏达科技集团有限公司",
        "party_b": "浙江众鑫人力资源服务有限公司",
        "subject": "派遣生产线操作工、仓储物流及行政辅助人员，常备派遣员工不少于50名",
        "payment_terms": "按月结算，每月5日前支付上月劳务费；新增派遣员工按实际到岗日计费",
        "amount": "约180万元/年（含服务费）",
        "duration": "2年",
    },
    "员工商业保险采购合同.pdf": {
        "party_a": "浙江宏达科技集团有限公司",
        "party_b": "平安财产保险股份有限公司浙江分公司",
        "subject": "企业员工团体意外险、商业补充医疗险及雇主责任险，覆盖全体在职员工",
        "payment_terms": "保费一次性缴清，合同签订后5个工作日内付款；中途增减人员按比例调整",
        "amount": "86.4万元（全年保费）",
        "duration": "2026年1月1日至2026年12月31日",
    },
}


def main() -> None:
    db = SessionLocal()
    try:
        ok = skip = 0
        for filename, elems in _DEMO_ELEMENTS.items():
            c = db.query(Contract).filter(Contract.filename == filename).first()
            if not c:
                print(f"  [SKIP] {filename[:30]} 合同记录不存在")
                continue
            try:
                existing = json.loads(c.elements_json or "{}")
            except Exception:
                existing = {}
            if existing.get("party_a"):
                print(f"  [SKIP] {filename[:30]} 已有要素，跳过")
                skip += 1
                continue
            c.elements_json = json.dumps(elems, ensure_ascii=False)
            ok += 1
            print(f"  [OK]   {filename[:40]}")
        db.commit()
        print(f"\n演示合同要素填充完成: 更新 {ok}  跳过(已有) {skip}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
