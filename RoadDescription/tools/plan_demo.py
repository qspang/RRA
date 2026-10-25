"""Reproduce the verified two-scheme demo, retaining its real HTTP evidence."""
import argparse
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))

from road_description.io import read_json, config_root
from road_description.pipeline import run
from road_description.planner import select_scheme


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default=str(root / 'configs/config.demo.json'))
    parser.add_argument('--replan', action='store_true', help='重新调用规划接口；默认复用已有可行结果')
    args = parser.parse_args()
    path = Path(args.config).resolve()
    config = read_json(path)
    out = config_root(path, config) / config['output_dir']
    reusable = len(config.get('schemes', [])) == 2
    for item in config.get('schemes', []):
        try:
            select_scheme(read_json(out / item['id'] / 'response.json'))
        except (OSError, ValueError, RuntimeError):
            reusable = False
    plan = args.replan or not reusable
    print('重新调用真实规划接口' if plan else '复用已校核的真实JSON，重新生成报告', flush=True)
    print(run(path, plan=plan))


if __name__ == '__main__':
    main()
