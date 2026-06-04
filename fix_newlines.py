import re

with open("apps/worker/jobs.py", "r") as f:
    content = f.read()

content = content.replace('sections["news"] = "\n".join(news_lines)', 'sections["news"] = "\\n".join(news_lines)')
content = content.replace('search_results.append(f"### {q}\n{res}")', 'search_results.append(f"### {q}\\n{res}")')
content = content.replace('search_results.append(f"### {q}\nFailed: {e}")', 'search_results.append(f"### {q}\\nFailed: {e}")')
content = content.replace('sections["web_news"] = "\n\n".join(search_results)', 'sections["web_news"] = "\\n\\n".join(search_results)')
content = content.replace('content": f"☀️ **Morning Briefing — {today.strftime(\'%A, %d %B\')}**\n\n{content}"', 'content": f"☀️ **Morning Briefing — {today.strftime(\'%A, %d %B\')}**\\n\\n{content}"')

content = content.replace('discussed.\n\n" + "\n".join(text_lines)', 'discussed.\\n\\n" + "\\n".join(text_lines)')

with open("apps/worker/jobs.py", "w") as f:
    f.write(content)
