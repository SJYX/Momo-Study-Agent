# Makefile for Momo Study Agent
# 快捷命令集合，提升开发体验

.PHONY: help install dev-install format lint test test-cov clean run

# 默认目标：显示帮助
help:
	@echo "Momo Study Agent - 开发工具"
	@echo ""
	@echo "可用命令:"
	@echo "  make install      - 安装生产依赖"
	@echo "  make dev-install  - 安装开发依赖"
	@echo "  make format       - 格式化代码 (black + isort)"
	@echo "  make lint         - 代码质量检查"
	@echo "  make test         - 运行测试"
	@echo "  make test-cov     - 运行测试并生成覆盖率报告"
	@echo "  make clean        - 清理临时文件"
	@echo "  make run          - 运行主程序"
	@echo "  make run-dev      - 运行主程序（开发模式）"
	@echo "  make docs-check   - 检查文档质量"

# 安装生产依赖
install:
	pip install -r requirements.txt

# 安装开发依赖
dev-install:
	pip install -e ".[dev]"

# 格式化代码
format:
	@echo "格式化代码..."
	python -m black core/ main.py config.py --line-length 120
	python -m isort core/ main.py config.py --profile black

# 代码质量检查
lint:
	@echo "检查代码质量..."
	python -m flake8 core/ main.py config.py --max-line-length 120 --ignore=E203,W503
	python -m mypy core/ main.py config.py --ignore-missing-imports

# 运行测试
test:
	@echo "运行测试..."
	python -m pytest tests/ -v

# 运行测试并生成覆盖率报告
test-cov:
	@echo "运行测试并生成覆盖率报告..."
	python -m pytest tests/ -v --cov=core --cov=config --cov=main \
		--cov-report=html:htmlcov \
		--cov-report=term-missing \
		--cov-report=json:coverage.json
	@echo "覆盖率报告已生成到 htmlcov/index.html"

# 清理临时文件
clean:
	@echo "清理临时文件..."
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type f -name "*.pyo" -delete 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	rm -rf htmlcov/ .coverage coverage.json .pytest_cache/ .mypy_cache/ 2>/dev/null || true
	@echo "清理完成"

# 运行主程序
run:
	python main.py

# 运行主程序（开发模式）
run-dev:
	python main.py --env development --enable-stats

# 运行主程序（生产模式）
run-prod:
	python main.py --env production

# 检查文档质量
docs-check:
	python tools/check_docs_quality.py

# 检查 API 状态
api-check:
	python tools/check_api_status.py

# 数据库初始化
init-hub:
	python scripts/init_hub.py

# 生成评估报告
eval-report:
	python tests/generate_evaluation_report.py

# 性能测试
perf-test:
	python tests/test_performance.py

# 完整的 CI 流程
ci: clean lint test-cov
	@echo "✅ CI 检查完成"
