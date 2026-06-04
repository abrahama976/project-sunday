#!/bin/bash
echo "### Phase 5.5 Final Checklist Results" > pr_comment.txt

echo "#### 1. python -m py_compile apps/worker/config.py" >> pr_comment.txt
echo "\`\`\`" >> pr_comment.txt
cd apps/worker && .venv/bin/python3 -m py_compile config.py >> ../../pr_comment.txt 2>&1
echo "Exit Code: $?" >> ../../pr_comment.txt
echo "\`\`\`" >> ../../pr_comment.txt
cd ../..

echo "#### 2. python -m py_compile apps/worker/budget_gate.py" >> pr_comment.txt
echo "\`\`\`" >> pr_comment.txt
cd apps/worker && .venv/bin/python3 -m py_compile budget_gate.py >> ../../pr_comment.txt 2>&1
echo "Exit Code: $?" >> ../../pr_comment.txt
echo "\`\`\`" >> ../../pr_comment.txt
cd ../..

echo "#### 3. python -m py_compile apps/worker/router.py" >> pr_comment.txt
echo "\`\`\`" >> pr_comment.txt
cd apps/worker && .venv/bin/python3 -m py_compile router.py >> ../../pr_comment.txt 2>&1
echo "Exit Code: $?" >> ../../pr_comment.txt
echo "\`\`\`" >> ../../pr_comment.txt
cd ../..

echo "#### 4. PYTHONPATH=apps/worker .venv/bin/python apps/worker/tests/test_budget_gate_exhausted.py" >> pr_comment.txt
echo "\`\`\`" >> pr_comment.txt
cd apps/worker && PYTHONPATH=. .venv/bin/python3 tests/test_budget_gate_exhausted.py >> ../../pr_comment.txt 2>&1
echo "\`\`\`" >> ../../pr_comment.txt
cd ../..

echo "#### 5. grep -n 'GROQ_API_KEY' apps/worker/config.py" >> pr_comment.txt
echo "\`\`\`" >> pr_comment.txt
grep -n "GROQ_API_KEY" apps/worker/config.py >> pr_comment.txt 2>&1
echo "\`\`\`" >> pr_comment.txt

echo "#### 6. grep -n 'groq' apps/worker/requirements.txt" >> pr_comment.txt
echo "\`\`\`" >> pr_comment.txt
grep -n "groq" apps/worker/requirements.txt >> pr_comment.txt 2>&1
echo "\`\`\`" >> pr_comment.txt

echo "#### 7. git diff --stat" >> pr_comment.txt
echo "\`\`\`" >> pr_comment.txt
git status -s >> pr_comment.txt 2>&1
git diff --stat >> pr_comment.txt 2>&1
echo "\`\`\`" >> pr_comment.txt
