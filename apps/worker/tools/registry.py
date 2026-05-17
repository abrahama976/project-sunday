TOOLS = [
    {
        "name": "file_write",
        "description": "Write text content to a file. Always requires user approval.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute or ~ path to write to"},
                "content": {"type": "string", "description": "Text content to write"},
                "append": {"type": "boolean", "description": "If true, append to file instead of overwriting (default false)"}
            },
            "required": ["path", "content"]
        }
    },
    {
        "name": "file_read",
        "description": "Read the contents of a file on the Mac.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute or ~ path to the file"}
            },
            "required": ["path"]
        }
    },
    {
        "name": "file_list",
        "description": "List files in a directory on the Mac.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Directory path to list"}
            },
            "required": ["path"]
        }
    },
    {
        "name": "update_profile",
        "description": "Propose an addition to the user profile context file.",
        "parameters": {
            "type": "object",
            "properties": {
                "section": {"type": "string", "description": "Section heading to add under"},
                "content": {"type": "string", "description": "Content to append"}
            },
            "required": ["section", "content"]
        }
    },
    {
        "name": "web_fetch",
        "description": "Fetch the contents of a public HTTPS URL and return readable text. Use for looking up documentation, articles, or any public web page.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Full HTTPS URL to fetch"}
            },
            "required": ["url"]
        }
    },
    {
        "name": "calendar_query",
        "description": "Query Google Calendar for upcoming events. Can filter by keyword and number of days ahead.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Optional keyword to filter events by title"},
                "days_ahead": {"type": "integer", "description": "Number of days ahead to look (default 7, max 30)"}
            },
            "required": []
        }
    },
    {
        "name": "gmail_search",
        "description": "Search Gmail inbox using Gmail search syntax. Returns email list with date, sender, and subject.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Gmail search query e.g. 'from:boss@company.com is:unread'"},
                "max_results": {"type": "integer", "description": "Max emails to return (default 10, max 10)"}
            },
            "required": ["query"]
        }
    },
    {
        "name": "gmail_draft",
        "description": "Create a Gmail draft (does NOT send). Requires approval before execution.",
        "parameters": {
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Recipient email address"},
                "subject": {"type": "string", "description": "Email subject"},
                "body": {"type": "string", "description": "Email body text"}
            },
            "required": ["to", "subject", "body"]
        }
    },
]
