"""使用 backend/.venv 运行；规模数据与报告只能写入新目录。"""

from relationship_query.benchmark.run import main

if __name__ == "__main__":
    raise SystemExit(main())
