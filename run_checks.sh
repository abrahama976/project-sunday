#!/bin/bash
echo "### Verification Results" > pr_comment.txt

echo "#### 1. npx tsc --noEmit (apps/web)" >> pr_comment.txt
echo "\`\`\`" >> pr_comment.txt
cd apps/web && npx tsc --noEmit >> ../../pr_comment.txt 2>&1
echo "Exit Code: $?" >> ../../pr_comment.txt
echo "\`\`\`" >> ../../pr_comment.txt
cd ../..

echo "#### 2. python -m py_compile apps/worker/router.py" >> pr_comment.txt
echo "\`\`\`" >> pr_comment.txt
cd apps/worker && .venv/bin/python3 -m py_compile router.py >> ../../pr_comment.txt 2>&1
echo "Exit Code: $?" >> ../../pr_comment.txt
echo "\`\`\`" >> ../../pr_comment.txt
cd ../..

echo "#### 3. python apps/worker/tests/test_budget_gate_exhausted.py" >> pr_comment.txt
echo "\`\`\`" >> pr_comment.txt
cd apps/worker && PYTHONPATH=. .venv/bin/python3 tests/test_budget_gate_exhausted.py >> ../../pr_comment.txt 2>&1
echo "\`\`\`" >> ../../pr_comment.txt
cd ../..

echo "#### 4. messages table RLS policy" >> pr_comment.txt
echo "\`\`\`" >> pr_comment.txt
psql "postgresql://postgres:postgres@127.0.0.1:54322/postgres" -c "SELECT policyname, qual FROM pg_policies WHERE tablename = 'messages';" >> pr_comment.txt 2>&1
echo "\`\`\`" >> pr_comment.txt

