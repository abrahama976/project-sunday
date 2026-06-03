"use client";

import { useState } from "react";
import { saveProfileContent } from "./actions";

export default function ProfileEditor({ initialContent }: { initialContent: string }) {
  const [content, setContent] = useState(initialContent);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");

  async function handleSave() {
    setSaving(true);
    setMessage("");
    const result = await saveProfileContent(content);
    setSaving(false);
    if (result.success) {
      setMessage("Saved successfully.");
      setTimeout(() => setMessage(""), 3000);
    } else {
      setMessage(`Error: ${result.error}`);
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <textarea
        value={content}
        onChange={(e) => setContent(e.target.value)}
        className="w-full h-[400px] bg-zinc-900 text-zinc-100 border border-zinc-700 rounded-lg p-3 font-mono text-sm resize-y focus:outline-none focus:border-zinc-500"
      />
      <div className="flex items-center justify-between">
        <span className="text-xs text-zinc-400">
          {message}
        </span>
        <button
          onClick={handleSave}
          disabled={saving}
          className="bg-white text-black px-4 py-2 rounded font-medium disabled:opacity-50"
        >
          {saving ? "Saving..." : "Save Profile"}
        </button>
      </div>
    </div>
  );
}
