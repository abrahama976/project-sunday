export const dynamic = 'force-dynamic';

import { getProfileContent } from "./actions";
import ProfileEditor from "./editor";

export default async function ProfilePage() {
  const content = await getProfileContent();

  return (
    <div className="max-w-[390px] mx-auto p-4 pt-8">
      <h1 className="text-xl font-semibold mb-2 text-zinc-100">
        Profile Context
      </h1>
      <p className="text-sm text-zinc-400 mb-6">
        Edit the core memory file the AI reads on every request.
      </p>
      
      <ProfileEditor initialContent={content} />
    </div>
  );
}
