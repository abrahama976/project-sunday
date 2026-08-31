export const dynamic = 'force-dynamic';

import { getProfileContent, getDirectives } from "./actions";
import ProfileEditor from "./editor";
import BrainPanel from "./brain";

// Mirrors BRAIN_MAX_DIRECTIVES in apps/worker/config.py — the worker is the
// enforcer; this is display only.
const BRAIN_MAX_DIRECTIVES = 40;

export default async function ProfilePage() {
  const [content, directives] = await Promise.all([
    getProfileContent(),
    getDirectives(),
  ]);

  return (
    <div className="max-w-[390px] mx-auto p-4 pt-8 flex flex-col gap-10">
      <section>
        <h1 className="text-xl font-semibold mb-2 text-zinc-100">
          Profile Context
        </h1>
        <p className="text-sm text-zinc-400 mb-6">
          What Sunday knows about you. Facts, read on every request.
        </p>

        <ProfileEditor initialContent={content} />
      </section>

      <section className="border-t border-zinc-800 pt-8">
        <BrainPanel
          initialDirectives={directives}
          maxDirectives={BRAIN_MAX_DIRECTIVES}
        />
      </section>
    </div>
  );
}
