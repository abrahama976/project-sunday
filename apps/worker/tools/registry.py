TOOLS = [
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
    }
]
