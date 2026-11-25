"""Engineering language for presenting measured route/feature relationships."""
from docx.oxml.ns import qn
from docx.parts.hdrftr import FooterPart, HeaderPart


RELATION_RULE = (
    '描述线路与地物的空间关系时，优先使用“跨越、穿越、临近、占用”。'
    '线路越过道路、铁路、河流或电力线用“跨越”；中心线进入保护区、保护范围等面域用“穿越”。'
    '在附近但未进入用“临近”，有距离时保留距离。仅触及边界须明确仅触边，隧道段须注明平面投影。'
    '只有资料确认塔基或施工用地实际用地时才写“占用”。'
    '标题、图表、正文及审校建议均禁用“交叉”，角度称“跨越角”。'
)


def crossing_feature(category):
    """Physical infrastructure or watercourse, excluding its protection area."""
    if any(word in category for word in ('保护', '红线', '缓冲', '范围', '湿地', '公园')):
        return False
    return any(word in category for word in (
        '道路', '公路', '高速', '国道', '省道', '县道', '乡道', '铁路', '河流', '输电', '电力线',
    ))


def report_text(text):
    """Migrate unambiguous legacy phrases. Other ambiguous wording needs review."""
    return (text.replace('交叉跨越', '跨越')
            .replace('交叉角', '跨越角')
            .replace('邻近', '临近'))


def check_document(doc):
    """Check body, tables and existing headers/footers, including words split across runs."""
    roots = [doc.element.body]
    roots.extend(part.element for part in doc.part.related_parts.values()
                 if isinstance(part, (HeaderPart, FooterPart)))
    for root in roots:
        for paragraph in root.iter(qn('w:p')):
            text = ''.join(node.text or '' for node in paragraph.iter(qn('w:t')))
            if '交叉' in text:
                raise ValueError(f'报告出现禁用的空间关系术语，请核对来源或模板：{text[:120]}')
