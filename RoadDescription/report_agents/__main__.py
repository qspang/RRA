import argparse
import json

from .registry import agent_ids, create_agent
from .runner import run_agents


def main():
    parser = argparse.ArgumentParser(description='可插拔的路径描述/方案比选/合规性分析三个Agent')
    parser.add_argument('--config', default='configs/config.agents.json')
    parser.add_argument('--agents', help='逗号分隔Agent ID；省略则使用配置enabled列表')
    parser.add_argument('--list', action='store_true', help='仅查看插件，不读取工程数据')
    args = parser.parse_args()
    if args.list:
        print(json.dumps([create_agent(i).manifest for i in agent_ids()], ensure_ascii=False, indent=2))
        return
    selected = [s.strip() for s in args.agents.split(',') if s.strip()] if args.agents is not None else None
    state = run_agents(args.config, selected)
    print(json.dumps({'status': state['status'], 'results': state['results']}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
